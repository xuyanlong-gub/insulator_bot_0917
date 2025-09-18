# -*- coding: utf-8 -*-
"""
工具模块：包含卡尔曼滤波器、滑动投票器以及通用辅助函数。

本模块实现了一个简单的一维卡尔曼滤波器 ``KalmanFilter1D``，
可用于对二值测量的存在概率进行平滑估计。同时提供 ``VotingBuffer``，
用于实现滑窗计数投票功能。
"""

from __future__ import annotations

import collections
from typing import Deque, Iterable, Optional



class VotingBuffer:
    """
    滑动投票缓冲区。

    维护最近 ``window_size`` 个二值结果，并根据阈值 ``vote_threshold`` 输出稳定值。
    当窗口内的 1 数量大于等于阈值时，输出 1；否则输出 0。
    """

    def __init__(self, window_size: int = 5, vote_threshold: Optional[int] = None) -> None:
        self.window_size = window_size
        self.vote_threshold = vote_threshold or ((window_size + 1) // 2)
        self.buffer: Deque[int] = collections.deque(maxlen=window_size)

    def update(self, value: int) -> int:
        """向缓冲区添加新值并返回当前稳定输出。"""
        if value not in (0, 1):
            raise ValueError("VotingBuffer 只能处理 0/1 值")
        self.buffer.append(value)
        count_ones = sum(self.buffer)
        # 如果缓冲区未满，直接输出 0（保守策略）
        if len(self.buffer) < self.window_size:
            return 0
        return 1 if count_ones >= self.vote_threshold else 0

    def reset(self) -> None:
        """清空缓冲区。"""
        self.buffer.clear()


def remove_small_segments(flags: Iterable[int], min_length: int, fill_with: int) -> list[int]:
    """
    移除二值序列中长度小于 ``min_length`` 的连续片段。

    :param flags: 输入的 0/1 序列。
    :param min_length: 最小保留长度，小于该长度的片段将被替换为 ``fill_with``。
    :param fill_with: 用于填充被移除片段的值（0 或 1）。
    :return: 处理后的序列列表。
    """
    flags = list(flags)
    n = len(flags)
    if n == 0:
        return flags
    result = flags.copy()
    i = 0
    while i < n:
        j = i
        # 找出连续片段 [i, j)
        while j < n and flags[j] == flags[i]:
            j += 1
        segment_len = j - i
        if segment_len < min_length:
            for k in range(i, j):
                result[k] = fill_with
        i = j
    return result


__all__ = [ "VotingBuffer", "remove_small_segments"]
# 这里保留 VotingBuffer，用于稳定帧级判定；如需概率卡尔曼，可在此扩展。
