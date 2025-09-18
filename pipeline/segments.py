# # -*- coding: utf-8 -*-
# """将段表转换为下发参数 (Z_start, step, n_steps, dis, is_last)。"""
# from __future__ import annotations
# from typing import List, Tuple
# import math
#
# def _clamp(x: float, lo: float, hi: float) -> float:
#     return max(lo, min(hi, x))
#
# def segments_to_commands(segments: List[Tuple[int, float, float]], dis_mm: float,
#                          brush_width_mm: float = 200.0,
#                          min_step_mm: float = 150.0,
#                          max_step_mm: float = 180.0,
#                          overlap_pct: float = 0.20) -> List[tuple[float, float, int, float, int]]:
#     """
#     仅对 flag==1 的段生成参数。
#     step 由刷头宽度与重叠率确定：step = clamp(brush_width_mm * (1-overlap_pct), 150, 180)。
#     n = 1 + ceil(max(0, L - brush_width_mm) / step)。
#     为减少末端“多刷/漏刷”，对给定 n 再做一次均分微调 step'，并仍限制在 [min_step_mm, max_step_mm]。
#     """
#     step_pref = _clamp(brush_width_mm * (1.0 - overlap_pct), min_step_mm, max_step_mm)
#
#     cmds: list[tuple[float, float, int, float, int]] = []
#     clean = [(s, e) for f, s, e in segments if int(f) == 1]
#     for i, (s, e) in enumerate(clean):
#         L = max(0.0, float(e) - float(s))
#         if L <= brush_width_mm:
#             n = 1
#             step_use = step_pref   # 单次即可覆盖，step 取默认值
#         else:
#             n = 1 + int(math.ceil((L - brush_width_mm) / step_pref))
#             # 均分微调：让覆盖更“整齐”，再约束回合法区间
#             step_even = (L - brush_width_mm) / max(1, n - 1)
#             step_use = _clamp(step_even, min_step_mm, max_step_mm)
#
#         is_last = 1 if i == len(clean) - 1 else 0
#         cmds.append((float(s), float(step_use), int(n), float(dis_mm), is_last))
#
#     return cmds


# -*- coding: utf-8 -*-
from __future__ import annotations
import math
from typing import List, Tuple

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def _qceil(x: float, q: int) -> int:
    return int(math.ceil(x / q) * q)

def _qfloor(x: float, q: int) -> int:
    return int(math.floor(x / q) * q)

def segments_to_commands(
    segments: List[Tuple[int, float, float]],
    dis_mm: float,
    *,
    brush_width_mm: int = 200,
    overlap_pct: float = 0.20,
    min_step_mm: int = 150,
    max_step_mm: int = 180,
    guard_start_mm: int = 5,
    guard_end_mm: int = 10,
    quant_mm: int = 1,
) -> List[tuple[int, int, int, int, int]]:
    """
    将 [flag, z_start, z_end] 段表转换为整数命令 (Z_start, step, n_steps, dis, is_last)。
    - 全部返回为整数毫米。
    - 覆盖保障：W + step*(n-1) >= (L + guard_start + guard_end)。
    - 步距整数化后仍不足覆盖则增大 n。
    """
    assert quant_mm >= 1 and min_step_mm <= max_step_mm
    W = int(brush_width_mm)

    step_pref = int(_clamp(round(W * (1.0 - overlap_pct)), min_step_mm, max_step_mm))

    cmds: list[tuple[int, int, int, int, int]] = []
    clean = [(s, e) for f, s, e in segments if int(f) == 1]

    for i, (s, e) in enumerate(clean):
        s = float(s); e = float(e)
        L = max(0.0, e - s)
        L_eff = L + guard_start_mm + guard_end_mm

        if L_eff <= W:
            n = 1
            step_use = _qceil(step_pref, quant_mm)
        else:
            # 先按期望步距估算 n
            n = 1 + int(math.ceil((L_eff - W) / step_pref))
            # 均分步距并向上取整到量化单位，保证覆盖
            step_even = (L_eff - W) / max(1, n - 1)
            step_use = _qceil(step_even, quant_mm)
            step_use = int(_clamp(step_use, min_step_mm, max_step_mm))
            # 若仍不足覆盖，提升 n
            cover = W + step_use * (n - 1)
            if cover < L_eff:
                n = 1 + int(math.ceil((L_eff - W) / step_use))

            # 若均分步距超过上限，改用上限并重算 n
            if step_use > max_step_mm:
                step_use = max_step_mm
                n = 1 + int(math.ceil((L_eff - W) / step_use))

        z0 = _qfloor(s - guard_start_mm, quant_mm)
        dis_i = int(round(dis_mm))  # 段级距离缺省；若调用处按段覆盖，会被覆盖

        is_last = 1 if i == len(clean) - 1 else 0
        cmds.append((int(z0), int(step_use), int(n), int(dis_i), int(is_last)))

    return cmds
