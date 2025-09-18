# -*- coding: utf-8 -*-


##########################################################
#################    绝缘子清洗机器人项目    #################
#################      2025年9月17日      #################
#################         国信类脑①       #################
#################         尔行智能②       #################
#################   绝缘子清洗机器人项目组   #################
#################     特别鸣谢:ChatGPT    #################
##########################################################


from __future__ import annotations
import argparse, logging, os, csv

from core.config import Config
from core.logger import setup_logger
from vision.detector import Detector
from pipeline.postprocess import postprocess_sequences, postprocess_sequences_ex
from pipeline.sampler import run_sampling
from pipeline.state_machine import negotiate_stop, descend_execute
from comms.modbus import ModbusClient

def save_csv(path: str, flags, zs, ds):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline='', encoding='utf-8') as f:
        w = csv.writer(f);
        w.writerow(["flag", "z", "dis"]);
        w.writerows([[f, z, d] for f, z, d in zip(flags, zs, ds)])


# 1) 头部已有: import csv, os
def save_segments_csv(path: str, segments):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline='', encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["flag", "z_start_mm", "z_end_mm", "dis_mm"])
        for fflag, s, e, dis in segments:
            w.writerow([int(fflag), round(float(s), 3), round(float(e), 3), round(float(dis), 3)])


def main(cfg_path: str, video_path: str | None):
    cfg = Config.load(cfg_path)
    log_cfg = cfg.section("logging")
    setup_logger(level=log_cfg.get("level", "INFO"), logfile=log_cfg.get("file", None))

    # 视觉配置
    vcfg = cfg.section("vision")
    weight = vcfg.get("weight_path")
    conf_thr = vcfg.get("conf_thr", {})
    center_band_px = int(vcfg.get("center_band_px", 20))
    vote_k = int(vcfg.get("vote_k", 5));
    vote_t = int(vcfg.get("vote_t", 3))

    # 采样配置
    scfg = cfg.section("sampling")
    period_s = float(scfg.get("period_s", 1.0))

    # 后处理配置
    pcfg = cfg.section("postproc")
    open_close_win = int(pcfg.get("open_close_win", 3))
    min_segment_mm = float(pcfg.get("min_segment_mm", 60))
    safety_delta_mm = float(pcfg.get("safety_delta_mm", 25))
    brush_offset_mm = float(pcfg.get("brush_offset_mm", 0))
    merge_gap_mm = float(pcfg.get("merge_gap_mm", 30))
    output_mode = pcfg.get("output_mode", "segments")

    # Modbus
    mcfg = cfg.section("modbus")
    host = mcfg.get("host", "127.0.0.1")
    port = int(mcfg.get("port", 15020))
    unit_id = int(mcfg.get("unit_id", 1))
    reg_base = int(mcfg.get("reg_base", 0))

    # dis
    max_jump_mm = float(mcfg.get("distance.max_jump_mm", 150))
    bfill_enabled = mcfg.get("distance.bfill_enabled", True)
    ffill_tail = mcfg.get("distance.ffill_tail", True)
    interp_gap_max = int(mcfg.get("distance.interp_gap_max", 0))

    # 清洗配置
    brush_width_mm = int(cfg.get("cleaning.brush_width_mm", 200))
    overlap_pct = float(cfg.get("cleaning.overlap_pct", 0.20))
    min_step_mm = int(cfg.get("cleaning.min_step_mm", 150))
    max_step_mm = int(cfg.get("cleaning.max_step_mm", 180))

    # 初始化
    det = Detector(weight)
    mod = ModbusClient(host, port, unit_id, timeout=2.0)

    # Phase-1 上升采样
    flags, zs, ds, stop_reason = run_sampling(mod, reg_base, det, video_path,
                                              period_s, conf_thr, center_band_px, vote_k, vote_t,
                                              distance_cfg=cfg.get("distance", {}))

    # 保存原始采样
    csv_path = log_cfg.get("csv_path", "logs/sample.csv")
    save_csv(csv_path, flags, zs, ds)

    # Phase-2 终止协商
    negotiate_stop(mod, reg_base, reason=stop_reason, timeout=3.0)

    # 后处理（段模式，输出含 dis 的段表）
    segments_with_dis = postprocess_sequences_ex(
        flags, zs, ds,
        open_close_win=open_close_win,
        min_segment_mm=min_segment_mm,
        safety_delta_mm=safety_delta_mm,
        brush_offset_mm=brush_offset_mm,
        merge_gap_mm=merge_gap_mm,
        output_mode="segments",
        dis_method="median", dis_trim_ratio=0.1,
        interp_gap_max=interp_gap_max,
        ffill_tail=ffill_tail,
    )

    # 保存后处理结果
    seg_csv_path = log_cfg.get("segments_csv_path", "logs/segments.csv")
    save_segments_csv(seg_csv_path, segments_with_dis)
    print("后处理结果：", segments_with_dis)

    # Phase-3 逐段执行
    descend_execute(mod, reg_base, segments_with_dis, dis_mm=-1.0, brush_width_mm=brush_width_mm,
                    min_step_mm=min_step_mm, max_step_mm=max_step_mm, overlap_pct=overlap_pct)

    logging.info("流程结束。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--video", default="videos/demo1-0.mp4")
    a = ap.parse_args()
    main(a.config, a.video)
