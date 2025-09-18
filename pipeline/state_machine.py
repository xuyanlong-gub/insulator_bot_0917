# -*- coding: utf-8 -*-
from __future__ import annotations
import logging, time, math
from typing import List

from comms.modbus import (
    ModbusClient,
    CMD_STOP_ASC, CMD_START_SEG, CMD_FINISH_ALL,
    ST_STOPPED, ST_CLEANING, ST_WAIT_SEG, ST_DONE,
)
from pipeline.segments import segments_to_commands

def _wait_status(mod: ModbusClient, reg_base: int, expect: int, timeout: float, poll_s: float=0.05) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        st, _ = mod.read_status_and_z(reg_base)
        if st == expect:
            return True
        time.sleep(poll_s)
    return False

def negotiate_stop(mod: ModbusClient, reg_base: int, reason: float = 2.0, timeout: float = 3.0) -> bool:
    mod.write_cmd(reg_base, CMD_STOP_ASC)
    ok = _wait_status(mod, reg_base, ST_STOPPED, timeout)
    logging.info("停止上升 STATUS=3 达成=%s", ok)
    return ok

def descend_execute(mod: ModbusClient, reg_base: int, segments: List[List[float]], dis_mm: float = -1.0,
                    ack_timeout: float = 3.0,
                    seg_timeout_base: float = 3.0,
                    brush_width_mm: int = 200,
                    min_step_mm: int = 150,
                    max_step_mm: int = 180,
                    overlap_pct: float = 0.20) -> None:
    """
    每段初始清洗点 = 该段最上端的 z（上边界 e）。
    segments 支持：
      - [flag, z_start, z_end]
      - [flag, z_start, z_end, dis]
    仅对 flag==1 的段下发。
    """
    # 仅保留可清段，抽出 (s, e, dis)
    seg_pairs = []
    for seg in segments:
        if len(seg) >= 4:
            f, s, e, d = seg[:4]
            if int(f) != 1:
                continue
            seg_pairs.append((float(s), float(e), float(d)))
        else:
            f, s, e = seg[:3]
            if int(f) != 1:
                continue
            seg_pairs.append((float(s), float(e), float(dis_mm)))

    # 自上而下：按上边界 e 降序
    seg_pairs.sort(key=lambda x: x[1], reverse=True)

    # 为步距与次数计算生成三元段（顺序保持为高→低）
    seg_triplets = [(1, s, e) for (s, e, _) in seg_pairs]
    seg_dis_list = [d for (_, _, d) in seg_pairs]

    # 计算步距/次数（不决定起始点）
    cmds = segments_to_commands(
        seg_triplets,
        dis_mm=dis_mm,
        brush_width_mm=brush_width_mm,
        min_step_mm=min_step_mm,
        max_step_mm=max_step_mm,
        overlap_pct=overlap_pct
    )
    logging.info("下发段数：%d", len(cmds))

    # 起始点改为：每段最上端 e（满足“从最上面一点开始”）
    # 如若 PLC 的 h0 语义是“首刷覆盖区的下边界”，改为：h0_top = e - brush_width_mm
    for idx, (z_start_calc, step, n, dis_calc, is_last_calc) in enumerate(cmds):
        e_top = seg_pairs[idx][1]
        dis_seg = seg_dis_list[idx] if idx < len(seg_dis_list) else dis_calc
        if (isinstance(dis_seg, float) and math.isnan(dis_seg)) or dis_seg < 0:
            dis_seg = dis_calc if dis_calc >= 0 else dis_mm

        h0_top = float(e_top)                 # 方案A：h0 为段上端“点”
        # h0_top = float(e_top - brush_width_mm)  # 方案B：若 h0 表示首刷下边界，请改用这一行

        logging.info("START_SEG h0=%.1f step=%.1f n=%d dis=%.1f last=%d",
                     h0_top, step, n, dis_seg, 1 if idx == len(cmds)-1 else 0)

        mod.write_segment_params(reg_base, h0_top, step, n, dis_seg)
        mod.write_cmd(reg_base, CMD_START_SEG)

        # 等待进入清洗
        if not _wait_status(mod, reg_base, ST_CLEANING, ack_timeout):
            logging.warning("等待进入STATUS=6超时，重试一次CMD=5")
            mod.write_cmd(reg_base, CMD_START_SEG)
            _ = _wait_status(mod, reg_base, ST_CLEANING, ack_timeout)

        # 段完成后回到等待分段
        ok = _wait_status(mod, reg_base, ST_WAIT_SEG, max(seg_timeout_base, 0.1 * max(1, n)))
        logging.info("段完成返回STATUS=5：%s", ok)

    # 完成
    mod.write_cmd(reg_base, CMD_FINISH_ALL)
    _ = _wait_status(mod, reg_base, ST_DONE, 5.0)
    logging.info("流程结束，STATUS=7")
