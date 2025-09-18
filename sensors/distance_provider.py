# -*- coding: utf-8 -*-
from __future__ import annotations
import random
from typing import Optional, Any, Dict

class DistanceProvider:
    """
    统一的测距接口：
    - try_get_distance_mm(frame=None) -> Optional[float]：无新数据返回 None。
    - 缺省为“模拟器”，按设定的“每 N 次采样来一次距离”生成带噪声的距离。
    - 将来接入真实双目：在 _real_try_get_distance_mm 中写实际读取逻辑并返回 float 或 None。
    """
    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        cfg = cfg or {}
        # 模拟器参数
        self.latency_n = int(cfg.get("latency_n", 5))          # 平均每 N 个采样来一次距离
        self.mock_base_mm = float(cfg.get("mock_base_mm", 800.0))
        self.mock_noise_mm = float(cfg.get("mock_noise_mm", 5.0))
        self.mock_drift_per_sample_mm = float(cfg.get("mock_drift_per_sample_mm", 0.0))

        # 质量控制
        self.max_jump_mm = float(cfg.get("max_jump_mm", 150.0))

        # 内部状态
        self._tick = 0
        self._last_val: Optional[float] = None

    # ============= 对外主入口 =============
    def try_get_distance_mm(self, frame=None) -> Optional[float]:
        # 若后续接入真实双目，在此优先读取真实数据
        val = self._real_try_get_distance_mm(frame)
        if val is not None:
            return self._limit_jump(val)

        # 否则走模拟器
        self._tick += 1
        if self._tick % max(1, self.latency_n) != 0:
            return None
        base = self._last_val if self._last_val is not None else self.mock_base_mm
        val = base + self.mock_drift_per_sample_mm + random.uniform(-self.mock_noise_mm, self.mock_noise_mm)
        self._last_val = val
        return float(val)

    # ============= 真实设备读取：占位实现 =============
    def _real_try_get_distance_mm(self, frame=None) -> Optional[float]:
        """
        TODO：替换为真实双目测距模块的读取逻辑。
        返回 float 毫米；无新数据或未就绪返回 None。
        """
        return None

    # ============= 跳变限幅 =============
    def _limit_jump(self, new_val: float) -> float:
        if self._last_val is None:
            self._last_val = new_val
            return new_val
        diff = new_val - self._last_val
        if abs(diff) > self.max_jump_mm:
            new_val = self._last_val + (self.max_jump_mm if diff > 0 else -self.max_jump_mm)
        self._last_val = new_val
        return new_val
