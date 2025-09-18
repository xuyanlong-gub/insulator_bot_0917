"""
后处理模块：对采样得到的可清/不可清序列进行形态学去噪、边界缩退、刷头偏置和合并操作，
生成最终用于执行的点表或段表。

核心流程参考需求文档第 4 节：

1. 去抖开闭运算（开关窗口 ``open_close_win``）。
2. 最小段长 ``min_segment_mm``：过短的可清段并入邻段或直接禁止清洗。
3. 边界缩退 ``safety_delta_mm``：交界处向禁清方向各缩退该距离。
4. 刷头偏置 ``brush_offset_mm``：清洗段整体偏移该距离。
5. 合并相邻同类型且间隔小于 ``merge_gap_mm`` 的段。
6. 根据 ``output_mode`` 输出点表或段表。
"""

from __future__ import annotations

import csv
from typing import List, Tuple

import pandas as pd

from vision.kf_vote import remove_small_segments


def morph_open_close(flags: List[int], open_close_win: int) -> List[int]:
    """对二值序列执行形态学开闭运算，去除孤立噪声。"""
    # 开运算：先腐蚀小的 1 段，再膨胀恢复
    eroded = remove_small_segments(flags, open_close_win, fill_with=0)
    # 闭运算：先填充小的 0 段，再恢复
    # 先对反转序列开运算，相当于闭运算
    inverted = [1 - f for f in eroded]
    closed_inverted = remove_small_segments(inverted, open_close_win, fill_with=0)
    closed = [1 - f for f in closed_inverted]
    return closed


def merge_segments(segments: List[Tuple[int, float, float]], merge_gap_mm: float) -> List[Tuple[int, float, float]]:
    """合并相邻同 flag 且间距小于 ``merge_gap_mm`` 的段。"""
    if not segments:
        return []
    merged: List[Tuple[int, float, float]] = []
    curr_flag, curr_start, curr_end = segments[0]
    for flag, start, end in segments[1:]:
        if flag == curr_flag and start - curr_end < merge_gap_mm:
            # 合并
            curr_end = end
        else:
            merged.append((curr_flag, curr_start, curr_end))
            curr_flag, curr_start, curr_end = flag, start, end
    merged.append((curr_flag, curr_start, curr_end))
    return merged


def shrink_boundaries(segments: List[Tuple[int, float, float]], delta: float) -> List[Tuple[int, float, float]]:
    """
    对 0↔1 的交界处进行边界缩退操作。

    对于相邻的 ``(flag0, s0, e0)`` 和 ``(flag1, s1, e1)``：如果标记不同，则
    - 如果 ``flag0`` 为 1（可清），那么 ``e0`` 减去 ``delta``，同时 ``s1`` 加上 ``delta``。
    - 如果 ``flag1`` 为 1，则反向操作。
    缩退后若出现逆序（即 ``e <= s``），则舍弃该段。
    """
    if not segments:
        return []
    adjusted: List[Tuple[int, float, float]] = []
    for i, (flag, s, e) in enumerate(segments):
        new_s, new_e = s, e
        # 前后标志不同则分别处理边界
        # 与前一个比较
        if i > 0:
            prev_flag, prev_s, prev_e = segments[i - 1]
            if prev_flag != flag:
                # 前一段和当前段不同
                if flag == 1:
                    # 当前段为可清，缩小起点
                    new_s = max(new_s, s + delta)
                elif flag == 0:
                    # 当前段为不可清，扩大起点（禁清方向即向前）
                    new_s = max(new_s, s)
        # 与下一段比较
        if i < len(segments) - 1:
            next_flag, next_s, next_e = segments[i + 1]
            if next_flag != flag:
                if flag == 1:
                    # 当前段为可清，缩小终点
                    new_e = min(new_e, e - delta)
                elif flag == 0:
                    # 当前段为不可清，扩大终点
                    new_e = min(new_e, e)
        # 过滤掉反向或空段
        if new_e > new_s:
            adjusted.append((flag, new_s, new_e))
    return adjusted


def apply_brush_offset(segments: List[Tuple[int, float, float]], offset: float) -> List[Tuple[int, float, float]]:
    """将刷头偏置应用到可清段。"""
    return [
        (flag, s + offset, e + offset) if flag == 1 else (flag, s, e)
        for flag, s, e in segments
    ]


def filter_min_length(segments: List[Tuple[int, float, float]], min_length: float) -> List[Tuple[int, float, float]]:
    """移除长度小于 ``min_length`` 的可清段。"""
    filtered: List[Tuple[int, float, float]] = []
    for flag, s, e in segments:
        length = e - s
        if flag == 1 and length < min_length:
            # 放弃短可清段
            continue
        filtered.append((flag, s, e))
    return filtered


def convert_flags_to_segments(flags: List[int], zs: List[float]) -> List[Tuple[int, float, float]]:
    """
    根据 flag 和对应的 Z 序列生成段列表。

    :param flags: 标记列表，0/1 长度与 ``zs`` 相同。
    :param zs: 按照采样时间升序排列的 Z 值列表。
    :return: 段列表，每个元素为 (flag, Z_start, Z_end)。
    """
    assert len(flags) == len(zs), "flags 与 zs 长度不一致"
    if not flags:
        return []
    segments: List[Tuple[int, float, float]] = []
    curr_flag = flags[0]
    start_z = zs[0]
    prev_z = zs[0]
    for flag, z in zip(flags[1:], zs[1:]):
        # 遇到标志变化或非连续 Z（大幅跳变）
        if flag != curr_flag:
            segments.append((curr_flag, start_z, prev_z))
            curr_flag = flag
            start_z = z
        prev_z = z
    # 最后一段
    segments.append((curr_flag, start_z, prev_z))
    return segments


def postprocess_sequences(flags: List[int], zs: List[float],
                          open_close_win: int,
                          min_segment_mm: float,
                          safety_delta_mm: float,
                          brush_offset_mm: float,
                          merge_gap_mm: float,

                          output_mode: str = "segments") -> List[List[float]]:
    """
    采样序列后处理主函数。

    :param flags: 采样的 0/1 序列。
    :param zs: 对应的 Z 值（单位 mm）序列。
    :param open_close_win: 形态学开闭运算窗口长度。
    :param min_segment_mm: 最小可清洗段长度，短于该值将被过滤掉。
    :param safety_delta_mm: 边界缩退距离。
    :param brush_offset_mm: 刷头偏置，正值表示需要向上移动。
    :param merge_gap_mm: 合并间隙阈值，两个同类型段距离小于该值则合并。
    :param output_mode: ``"points"`` 输出点表；``"segments"`` 输出段表。
    :return: 根据输出模式，返回点表或段表。
    """
    # 1. 开闭运算去噪
    flags_clean = morph_open_close(flags, open_close_win)
    # 2. 转换为段表
    segments = convert_flags_to_segments(flags_clean, zs)
    # 3. 最小段长过滤
    segments = filter_min_length(segments, min_segment_mm)
    # 4. 边界缩退
    segments = shrink_boundaries(segments, safety_delta_mm)
    # 5. 刷头偏置
    segments = apply_brush_offset(segments, brush_offset_mm)
    # 6. 合并相邻同 flag 段
    segments = merge_segments(segments, merge_gap_mm)
    # 输出
    if output_mode.lower() == "points":
        # 点表：保持 flags 和 zs
        return [[float(f), float(z)] for f, z in zip(flags_clean, zs)]
    else:
        # 段表：只输出可清段
        result: List[List[float]] = []
        for flag, s, e in segments:
            # 只输出 flag 和 Z 起止值
            result.append([float(flag), float(s), float(e)])
        return result


__all__ = [
    "morph_open_close", "merge_segments", "shrink_boundaries",
    "apply_brush_offset", "filter_min_length",
    "convert_flags_to_segments", "postprocess_sequences"
]
# ——在原文件顶部 import 附近追加——
from bisect import bisect_left, bisect_right
from typing import Optional

# ——在原文件中新增：dis 序列回填工具——
def backfill_then_ffill_dis(ds: List[Optional[float]],
                            ffill_tail: bool = True,
                            max_interp_gap: int = 0) -> List[float]:
    """
    先向后填充（bfill）：用右侧最近的非 None 回填左边的 None；
    再可选向前填充（ffill）尾段；可选在短缺口做线性插值。
    """
    n = len(ds)
    out = ds[:]
    # bfill
    next_v: Optional[float] = None
    for i in range(n-1, -1, -1):
        if out[i] is not None:
            next_v = out[i]
        elif next_v is not None:
            out[i] = next_v
    # 简易插值（可选）
    if max_interp_gap and max_interp_gap > 1:
        i = 0
        while i < n:
            if out[i] is None:
                j = i
                while j < n and out[j] is None:
                    j += 1
                gap = j - i
                if j < n and i-1 >= 0 and gap <= max_interp_gap and out[i-1] is not None and out[j] is not None:
                    v0, v1 = float(out[i-1]), float(out[j])
                    for k in range(gap):
                        out[i+k] = v0 + (v1 - v0) * (k+1)/(gap+1)
                i = j
            else:
                i += 1
    # 尾部 ffill 或裁剪
    if ffill_tail:
        last_v: Optional[float] = None
        for i in range(n):
            if out[i] is not None:
                last_v = out[i]
            elif last_v is not None:
                out[i] = last_v
    else:
        while out and out[-1] is None:
            out.pop()
    return [float(x) if x is not None else float('nan') for x in out]

# ——新增：flag 连续段（按索引）——
def convert_flags_to_runs(flags: List[int]) -> List[Tuple[int, int, int]]:
    """
    将 flags 转为索引段：[(flag, i_start, i_end)]，闭区间。
    """
    if not flags:
        return []
    runs: List[Tuple[int, int, int]] = []
    curr_flag = flags[0]
    i_start = 0
    for i in range(1, len(flags)):
        if flags[i] != curr_flag:
            runs.append((curr_flag, i_start, i-1))
            curr_flag = flags[i]
            i_start = i
    runs.append((curr_flag, i_start, len(flags)-1))
    return runs

# ——新增：用 z 边界反查索引段（单调递增假设）——
def z_range_to_index(zs: List[float], z_start: float, z_end: float) -> Tuple[int, int]:
    i0 = bisect_left(zs, z_start)
    i1 = max(i0, bisect_right(zs, z_end) - 1)
    i0 = min(max(0, i0), len(zs)-1)
    i1 = min(max(0, i1), len(zs)-1)
    return i0, i1

# ——新增：段内距离统计——
def dis_stat_for_range(ds: List[float], i0: int, i1: int, method: str = "median", trim_ratio: float = 0.1) -> float:
    window = ds[i0:i1+1]
    if not window:
        return float("nan")
    if method == "median":
        window_sorted = sorted(window)
        m = len(window_sorted)//2
        return float(window_sorted[m] if len(window_sorted)%2==1 else 0.5*(window_sorted[m-1]+window_sorted[m]))
    # trimmed mean
    k = max(1, int(len(window) * trim_ratio))
    wsorted = sorted(window)
    wsorted = wsorted[k: len(wsorted)-k] if len(wsorted) >= 2*k+1 else wsorted
    return float(sum(wsorted)/len(wsorted))

# ——保留原 postprocess_sequences 不变——

# ——新增：带距离的后处理主函数——
def postprocess_sequences_ex(flags: List[int], zs: List[float], ds: List[Optional[float]],
                             open_close_win: int,
                             min_segment_mm: float,
                             safety_delta_mm: float,
                             brush_offset_mm: float,
                             merge_gap_mm: float,
                             output_mode: str = "segments",
                             dis_method: str = "median",
                             dis_trim_ratio: float = 0.1,
                             interp_gap_max: int = 0,
                             ffill_tail: bool = True
                             ) -> List[List[float]]:
    """
    扩展版后处理：在原有段表基础上追加段代表距离 dis。
    - points 模式输出 [flag, z, dis]
    - segments 模式输出 [flag, z_start, z_end, dis]
    """
    assert len(flags) == len(zs) == len(ds), "flags/zs/ds 长度不一致"
    # 1) dis 回填与清洗
    ds_filled = backfill_then_ffill_dis(ds, ffill_tail=ffill_tail, max_interp_gap=interp_gap_max)
    # 2) 形态学去噪
    flags_clean = morph_open_close(flags, open_close_win)
    # 3) 段表（z）
    segments = convert_flags_to_segments(flags_clean, zs)
    segments = filter_min_length(segments, min_segment_mm)
    segments = shrink_boundaries(segments, safety_delta_mm)
    segments = apply_brush_offset(segments, brush_offset_mm)
    segments = merge_segments(segments, merge_gap_mm)

    if output_mode.lower() == "points":
        return [[float(f), float(z), float(d)] for f, z, d in zip(flags_clean, zs, ds_filled)]
    else:
        out: List[List[float]] = []
        for flag, s, e in segments:
            i0, i1 = z_range_to_index(zs, s, e)
            dis_val = dis_stat_for_range(ds_filled, i0, i1, method=dis_method, trim_ratio=dis_trim_ratio)
            out.append([float(flag), float(s), float(e), float(dis_val)])
        return out

# ——更新导出符号——
__all__ += [
    "backfill_then_ffill_dis",
    "convert_flags_to_runs",
    "z_range_to_index",
    "dis_stat_for_range",
    "postprocess_sequences_ex",
]


if __name__ == "__main__":
    df = pd.read_csv(r'D:\workspace\绝缘子清洗机器人\项目代码\草稿版本0908-3\insulator_bot\logs\sample.csv')
    flags = list(df['flag'])
    win = 15
    eroded = remove_small_segments(flags, win, fill_with=0)
    closed = [1 - x for x in remove_small_segments([1 - x for x in eroded], win, fill_with=0)]
    # 期望：closed == [0]*200 + [1]*400 + [0]*240 + [1]*250
    print(closed)