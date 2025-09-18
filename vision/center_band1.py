# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Tuple

def judge_center_band(
    detections: List[List[float]],
    conf_thr: dict[str, float],
    img_height: int,
    band_width: int,
    overlap_thr: float = 0.5,
) -> Tuple[int, str]:
    """
    中心带可清判定 + 当前中心带部件返回。

    输入
    ----
    detections: [ [x1,y1,x2,y2,cls_id,conf], ... ]
    conf_thr : 各类置信度阈值，如 {'top':0.25,'body':0.25,'flange':0.25,'base':0.25}
    img_height: 图像高度
    band_width: 中心带像素宽度
    overlap_thr: 认为“覆盖充分”的阈值（相对 box 高度的重叠比例）

    返回
    ----
    (flag, part)
    flag: 1=可清洗，0=不可清洗
    part: 'top' | 'body' | 'flange' | 'base' | 'none'
    """
    class_mapping = {0: 'top', 1: 'body', 2: 'flange', 3: 'base'}
    banned = {0, 2, 3}  # 禁清类
    center_y = img_height // 2
    band_half = max(1, band_width // 2)
    band_y1 = center_y - band_half
    band_y2 = center_y + band_half

    # 预筛：按阈值过滤，并计算基础量
    items = []
    for x1, y1, x2, y2, cls_id, conf in detections:
        cls = int(cls_id)
        name = class_mapping.get(cls, '')
        if not name:
            continue
        if conf < float(conf_thr.get(name, 0.0)):
            continue
        y1f, y2f = float(y1), float(y2)
        if y2f <= y1f:
            continue
        box_h = max(1.0, y2f - y1f)
        ovl_y1 = max(band_y1, y1f)
        ovl_y2 = min(band_y2, y2f)
        overlap_h = max(0.0, ovl_y2 - ovl_y1)
        ratio_box = overlap_h / box_h
        full_contain = (y1f <= band_y1) and (band_y2 <= y2f)
        if full_contain and cls in banned:
            return 0, name

        items.append({
            "cls": cls, "name": name, "conf": float(conf),
            "y1": y1f, "y2": y2f, "box_h": box_h,
            "overlap_h": overlap_h, "ratio_box": ratio_box,
            "full": full_contain,
        })

    if not items:
        return 0, "none"

    # 1) 完全包含优先：若被禁清类完全覆盖，直接不可清，若 body 完全覆盖则可清
    fulls = [it for it in items if it["full"]]
    if fulls:
        # 选择高度更大或置信度更高者
        fulls.sort(key=lambda it: (it["box_h"], it["conf"]), reverse=True)
        part = fulls[0]["name"]
        if fulls[0]["cls"] in banned:
            return 0, part
        if fulls[0]["cls"] == 1:
            return 1, "body"

    # 2) 部分覆盖：若禁清类覆盖充分则不可清
    banned_parts = [it for it in items if (it["cls"] in banned and it["ratio_box"] > overlap_thr)]
    if banned_parts:
        banned_parts.sort(key=lambda it: (it["ratio_box"], it["conf"]), reverse=True)
        return 0, banned_parts[0]["name"]

    # 3) 部分覆盖：若 body 覆盖充分则可清
    body_parts = [it for it in items if (it["cls"] == 1 and it["ratio_box"] > overlap_thr)]
    if body_parts:
        body_parts.sort(key=lambda it: (it["ratio_box"], it["conf"]), reverse=True)
        return 1, "body"

    # 4) 无充分覆盖：按最大重叠比估计“当前中心带部件”，默认不可清
    items.sort(key=lambda it: (it["ratio_box"], it["conf"]), reverse=True)
    part = items[0]["name"] if items[0]["overlap_h"] > 0 else "none"
    return 0, part


if __name__ == "__main__":
    # 简单自测样例
    # 图像高 480，中带宽 20，中心在 y=240±10
    img_h = 480
    band_w = 20
    thr = {'top': 0.25, 'body': 0.25, 'flange': 0.25, 'base': 0.25}

    # 构造三组情形：
    cases = {
        "A_body_full": [
            # 一个 body 完全覆盖中心带
            [100, 100, 540, 380, 1, 0.9],
        ],
        "B_flange_partial_strong": [
            # flange 与中心带有较强重叠
            [120, 230, 520, 300, 2, 0.8],
        ],
        "C_weak_overlap": [
            # 各类与中心带重叠都很弱，返回最大重叠的类别作为“当前部件”，flag=0
            [50, 50, 200, 120, 3, 0.9],
            [60, 350, 220, 420, 1, 0.9],
        ],
    }

    for name, dets in cases.items():
        flag, part = judge_center_band(dets, thr, img_h, band_w)
        print(f"{name}: flag={flag}, part={part}")
