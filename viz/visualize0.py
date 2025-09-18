# -*- coding: utf-8 -*-
from __future__ import annotations
import csv, cv2, numpy as np, argparse

def draw_center_band(img: np.ndarray, band_px: int = 20):
    h, w = img.shape[:2]
    cy = h//2; b=band_px//2
    cv2.rectangle(img, (0, cy-b), (w-1, cy+b), (0,255,0), 1)

def main(csv_path: str, video_path: str):
    caps = cv2.VideoCapture(video_path)
    flags = []
    with open(csv_path, newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            flags.append(int(float(row['flag'])))
    i=0
    while True:
        ok, frame = caps.read()
        if not ok: break
        frame = cv2.resize(frame, (640,480))
        draw_center_band(frame, 20)
        if i < len(flags):
            cv2.putText(frame, f"flag={flags[i]}", (10,30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
        cv2.imshow("viz", frame); i+=1
        if cv2.waitKey(1) == 27: break
    caps.release(); cv2.destroyAllWindows()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv",default=r"D:\workspace\绝缘子清洗机器人\项目代码\草稿版本0908-3\insulator_bot\logs\sample.csv")
    ap.add_argument("--video", default="videos/demo1-0.mp4")
    a = ap.parse_args()
    main(a.csv, a.video)
