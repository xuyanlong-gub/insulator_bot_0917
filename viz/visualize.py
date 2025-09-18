# -*- coding: utf-8 -*-
"""视频可视化：显示中心带与类别框（实时推理）。"""
from __future__ import annotations
import cv2, time, argparse, os
from core.config import Config
from vision.detector import Detector
from overlay import overlay_frame

def run(cfg_path: str, video_path: str, save_path: str | None):
    cfg = Config.load(cfg_path)
    vcfg = cfg.section("vision")
    weight = vcfg.get("weight_path")
    conf_thr = vcfg.get("conf_thr", {})
    center_band_px = int(vcfg.get("center_band_px", 20))

    det = Detector(weight)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {video_path}")

    writer = None
    if save_path:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        writer = cv2.VideoWriter(save_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))

    t_last = time.time()
    count=0
    while True:
        count+=1
        ok, frame = cap.read()
        if not ok: break
        print("当前帧数:",count)
        dets = Detector.detect(det, frame)  # [x1,y1,x2,y2,cls,conf]
        overlay_frame(frame, dets, center_band_px=center_band_px, conf_thr=conf_thr, show_score=True, show_legend=True)

        now = time.time()
        fps = 1.0 / max(1e-6, now - t_last)
        t_last = now
        cv2.putText(frame, f"FPS {fps:.1f}", (10, frame.shape[0]-12), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2, cv2.LINE_AA)

        cv2.imshow("insulator-viz", frame)
        if writer: writer.write(frame)
        if cv2.waitKey(1) == 27: break

    cap.release()
    if writer: writer.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=r"D:\workspace\绝缘子清洗机器人\项目代码\草稿版本0908-3\insulator_bot\config.yaml")
    ap.add_argument("--video", default=r"D:\workspace\绝缘子清洗机器人\项目代码\草稿版本0908-3\insulator_bot\videos\demo1-0.mp4")
    ap.add_argument("--save", default="viz", help="可选：保存输出视频路径")
    a = ap.parse_args()
    run(a.config, a.video, a.save)
