# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List

def judge_center_band(detections: List[List[float]], conf_thr: dict[str, float],
                      img_height: int, band_width: int) -> int:
    """中心带可清判定。禁清类优先，其次片体。完全覆盖优先于部分覆盖。"""
    class_mapping = {0: 'top', 1: 'body', 2: 'flange', 3: 'base'}
    center_y = img_height // 2
    band_half = max(1, band_width // 2)
    band_y1 = center_y - band_half
    band_y2 = center_y + band_half

    # 完全包含优先
    for x1, y1, x2, y2, cls_id, conf in detections:
        cls = int(cls_id); name = class_mapping.get(cls, '')
        thr = conf_thr.get(name, 0.0)
        if conf < thr: continue
        if y1 <= band_y1 and band_y2 <= y2:
            if cls in (0,2,3): return 0
            if cls == 1: return 1

    # 禁清类部分覆盖
    for x1, y1, x2, y2, cls_id, conf in detections:
        cls = int(cls_id); name = class_mapping.get(cls, '')
        thr = conf_thr.get(name, 0.0)
        if conf < thr: continue
        overlap_y1 = max(band_y1, y1)
        overlap_y2 = min(band_y2, y2)
        if overlap_y1 < overlap_y2:
            box_h = max(1.0, y2-y1)
            if (overlap_y2-overlap_y1)/box_h > 0.5 and cls in (0,2,3):
                return 0

    # 片体部分覆盖
    for x1, y1, x2, y2, cls_id, conf in detections:
        cls = int(cls_id); name = class_mapping.get(cls, '')
        thr = conf_thr.get(name, 0.0)
        if conf < thr: continue
        overlap_y1 = max(band_y1, y1)
        overlap_y2 = min(band_y2, y2)
        if overlap_y1 < overlap_y2:
            box_h = max(1.0, y2-y1)
            if (overlap_y2-overlap_y1)/box_h > 0.5 and cls == 1:
                return 1
    return 0
