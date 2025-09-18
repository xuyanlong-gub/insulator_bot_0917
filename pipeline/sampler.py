# -*- coding: utf-8 -*-
from __future__ import annotations
import time, logging, cv2, numpy as np
from typing import List, Tuple, Optional

from vision.detector import Detector
from vision.center_band1 import judge_center_band
from vision.kf_vote import VotingBuffer
from core.utils import Ticker
from comms.modbus import ModbusClient, CMD_SAMPLE_UP, ST_SAMPLING, ST_AT_TOP
from sensors.distance_provider import DistanceProvider  # 新增

def run_sampling(mod: ModbusClient, reg_base: int, detector: Detector, video: str | None,
                 period_s: float, conf_thr: dict, center_band_px: int,
                 vote_k: int, vote_t: int,
                 distance_cfg: Optional[dict] = None
                 ) -> tuple[list[int], list[float], list[float], float]:

    stop_reason = 0.0
    voter = VotingBuffer(window_size=vote_k, vote_threshold=vote_t)

    flags: list[int] = []
    zs: list[float] = []
    ds: list[Optional[float]] = []     # 可能出现 None，占位等待回填
    last_filled = -1
    last_dis_val: Optional[float] = None
    z=1000 # 模拟上升

    cap = None
    if video:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            logging.error("无法打开视频：%s", video)
            cap = None

    dis_provider = DistanceProvider(distance_cfg or {})
    ticker = Ticker(period_s)
    logging.info("开始采样...")

    while True:
        if cap:
            ret, frame = cap.read()
            if not ret:
                logging.info("视频结束，停止采样")
                break
            frame = cv2.resize(frame, (640, 480))
        else:
            frame = np.zeros((640, 480, 3), dtype=np.uint8)

        dets = Detector.detect(detector, frame)
        flag_frame, cls_ins = judge_center_band(dets, conf_thr, frame.shape[0], center_band_px)
        flag = voter.update(flag_frame)

        if ticker.ready():
            # 每周期：Z_SIGNAL++ → CMD_SAMPLE_UP
            mod.write_z_signal_inc_then_sample(reg_base)
            st, z_ = mod.read_status_and_z(reg_base)
            z+=50
            # 记录 Z/flag
            flags.append(int(flag))
            zs.append(float(z))
            ds.append(None)  # 先占位，等 dis 到来后回填
            logging.info("采样 flag=%d, z=%.2f, STATUS=%d", flag, z, st)

            # 获取 dis（慢速/异步）
            new_dis = dis_provider.try_get_distance_mm(frame)
            if new_dis is not None:
                # 回填所有尚未填充的位置
                for i in range(last_filled + 1, len(ds)):
                    if ds[i] is None:
                        ds[i] = float(new_dis)
                last_filled = len(ds) - 1

            # TODO:现场测试的时候取消注释
            # # 触顶或视觉 top 结束（按需启用）
            # if st == ST_AT_TOP or cls_ins == 'top':
            #     stop_reason = 1.0 if st == ST_AT_TOP else 2.0
            #     break

    if cap: cap.release()

    # 采样结束后的尾部处理：若末尾仍有 None，用最后一个已知值前向填充；没有已知值则用 NaN。
    last = next((v for v in reversed(ds) if v is not None), None)
    ds = [ (last if (v is None and last is not None) else (float('nan') if v is None else v)) for v in ds ]

    return flags, zs, ds, stop_reason
