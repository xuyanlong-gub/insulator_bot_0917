# -*- coding: utf-8 -*-
from __future__ import annotations
import struct, time

# ================= Modbus float32 大端与寄存器转换 =================
def float_to_regs_be(val: float) -> tuple[int, int]:
    """float32 -> (hi, lo) 16位寄存器（大端，word-order 高字在前）。"""
    b = struct.pack('>f', float(val))
    hi = int.from_bytes(b[0:2], 'big')
    lo = int.from_bytes(b[2:4], 'big')
    return hi, lo

def regs_to_float_be(hi: int, lo: int) -> float:
    """(hi,lo) 16位寄存器 -> float32（大端）。"""
    b = hi.to_bytes(2, 'big') + lo.to_bytes(2, 'big')
    return struct.unpack('>f', b)[0]

# ================== 简易计时器 ==================
class Ticker:
    """按 period_s 周期满足时返回 True，用于采样调度。"""
    def __init__(self, period_s: float):
        self.period = float(period_s)
        self.t_last = time.time()

    def ready(self) -> bool:
        now = time.time()
        if now - self.t_last >= self.period:
            self.t_last = now
            return True
        return False
