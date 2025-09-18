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

from typing import List, Tuple

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













if __name__ == "__main__":
    # —— 参数设置（可按需修改）——
    open_close_win = 3        # 形态学开闭窗口
    min_segment_mm = 60.0     # 最小可清段长度
    safety_delta_mm = 25.0    # 边界缩退
    brush_offset_mm = 10.0    # 刷头整体偏置
    merge_gap_mm = 30.0       # 合并间隙阈值
    output_mode = "segments"  # "segments" 或 "points"

    # —— 构造较长的 flags 序列（0/1）——
    # 模式：大量 0 与多个 1 段交替，包含若干很短的 1 段用于测试滤除与合并
    pattern = [
        (0, 20),  # 0*20
        (1, 2),   # 短1段，预期被滤除
        (0, 8),
        (1, 15),  # 长1段
        (0, 1),
        (1, 1),   # 中等1段
        (0, 40),
        (1, 3),   # 短1段，预期被滤除
        (0, 6),
        (1, 20),  # 长1段
        (0, 10),
        (1, 18),  # 长1段
        (0, 5),
        (1, 4),   # 临界1段（长度≈步长*4）
        (0, 25),
    ]
    flags: List[int] = []
    for val, cnt in pattern:
        flags.extend([val] * cnt)

    # —— 构造对应的 Z 序列（单调递增，采样步长 15 mm）——
    step_mm = 15.0
    zs: List[float] = [i * step_mm for i in range(len(flags))]

    # —— 各阶段处理并打印中间结果 ——
    print("总采样点数:", len(flags))
    print("flags ", flags)
    print("zs    前10:", zs[:10], "...", zs[-10:])

    # 1) 开闭运算去噪
    flags_clean = morph_open_close(flags, open_close_win)
    print("\n[1] 开闭运算后 flags 前60:", flags_clean[:60])

    # 2) 转段
    seg0 = convert_flags_to_segments(flags_clean, zs)
    print("\n[2] 原始段数:", len(seg0))
    print("    前5段:", seg0[:5])

    # 3) 最小段长过滤
    seg1 = filter_min_length(seg0, min_segment_mm)
    print("\n[3] 过滤短段后段数:", len(seg1))
    print("    前5段:", seg1[:5])

    # 4) 边界缩退
    seg2 = shrink_boundaries(seg1, safety_delta_mm)
    print("\n[4] 边界缩退后段数:", len(seg2))
    print("    前5段:", seg2[:5])

    # 5) 刷头偏置
    seg3 = apply_brush_offset(seg2, brush_offset_mm)
    print("\n[5] 偏置后段数:", len(seg3))
    print("    前5段:", seg3[:5])

    # 6) 合并
    seg4 = merge_segments(seg3, merge_gap_mm)
    print("\n[6] 合并后段数:", len(seg4))
    print("    全量段（前10）:", seg4[:10])

    # 7) 主接口输出
    result = postprocess_sequences(
        flags, zs,
        open_close_win=open_close_win,
        min_segment_mm=min_segment_mm,
        safety_delta_mm=safety_delta_mm,
        brush_offset_mm=brush_offset_mm,
        merge_gap_mm=merge_gap_mm,
        output_mode=output_mode,
    )
    if output_mode.lower() == "segments":
        print("\n[最终输出/段表] 共", len(result), "段")
        for i, seg in enumerate(result[:10]):
            print(f"  seg[{i}]: flag={int(seg[0])}, z_start={seg[1]:.1f}, z_end={seg[2]:.1f}")
        if len(result) > 10:
            print("  ... 共计", len(result), "段")
    else:
        print("\n[最终输出/点表] 前20点:")
        for i, pt in enumerate(result[:20]):
            print(f"  pt[{i}]: flag={int(pt[0])}, z={pt[1]:.1f}")
        print("  ... 共计", len(result), "点")
