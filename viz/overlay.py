# -*- coding: utf-8 -*-
"""可视化叠加模块：中心带 + 类别框 + 置信度 + 图例。"""
from __future__ import annotations
import cv2
import numpy as np
from typing import List, Dict

CLASS_NAMES = {0:'top', 1:'body', 2:'flange', 3:'base'}
CLASS_COLORS = {
    'top':    (0, 165, 255),
    'body':   (0, 255, 0),
    'flange': (255, 0, 0),
    'base':   (0, 255, 255),
}

def draw_center_band(img: np.ndarray, band_px: int = 20, color=(0,255,0), thickness: int = 2):
    h, w = img.shape[:2]
    cy = h // 2; b = max(1, band_px // 2)
    cv2.rectangle(img, (0, cy-b), (w-1, cy+b), color, thickness)

def draw_detections(img: np.ndarray, detections: List[List[float]],
                    conf_thr: Dict[str, float] | None = None, show_score: bool = True):
    if conf_thr is None: conf_thr = {}
    for x1, y1, x2, y2, cls_id, conf in detections:
        cls_id = int(cls_id)
        name = CLASS_NAMES.get(cls_id, str(cls_id))
        if conf < conf_thr.get(name, 0.0): continue
        color = CLASS_COLORS.get(name, (200,200,200))
        p1 = (int(x1), int(y1)); p2 = (int(x2), int(y2))
        cv2.rectangle(img, p1, p2, color, 2)
        label = f"{name} {conf:.2f}" if show_score else name
        (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(img, (p1[0], p1[1]-th-6), (p1[0]+tw+6, p1[1]), color, -1)
        cv2.putText(img, label, (p1[0]+3, p1[1]-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,0), 1, cv2.LINE_AA)

def draw_legend(img: np.ndarray, conf_thr: Dict[str, float] | None = None, x: int = 10, y: int = 10):
    if conf_thr is None: conf_thr = {}
    y0 = y
    for cls_id in sorted(CLASS_NAMES.keys()):
        name = CLASS_NAMES[cls_id]
        color = CLASS_COLORS.get(name, (220,220,220))
        thr = conf_thr.get(name, 0.0)
        cv2.rectangle(img, (x, y0+4), (x+14, y0+18), color, -1)
        cv2.putText(img, f"{name} thr={thr:.2f}", (x+22, y0+18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1, cv2.LINE_AA)
        y0 += 22

def overlay_frame(img: np.ndarray, detections: List[List[float]], center_band_px: int = 20,
                  conf_thr: Dict[str, float] | None = None, show_score: bool = True, show_legend: bool = True) -> np.ndarray:
    draw_center_band(img, band_px=center_band_px)
    draw_detections(img, detections, conf_thr=conf_thr, show_score=show_score)
    if show_legend:
        panel = img.copy()
        h = 24*len(CLASS_NAMES)+20
        cv2.rectangle(panel, (6, 6), (250, 6+h), (0,0,0), -1)
        alpha = 0.35
        img[:] = (alpha * panel + (1-alpha) * img).astype(img.dtype)
        draw_legend(img, conf_thr, x=12, y=10)
    return img
