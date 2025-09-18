# test_postprocess_sequences.py
# -*- coding: utf-8 -*-
"""
用例A：人工序列
用例B：从 logs/sample.csv 读取 flags、z 并测试
"""

from __future__ import annotations
import os
import csv

# 优先从项目包导入；若无，则请改成你的文件路径
try:
    from postprocess import postprocess_sequences
except Exception:
    import importlib.util
    USER_FILE = r"postprocess.py"  # TODO: 替换为你的 postprocess_sequences 所在文件
    spec = importlib.util.spec_from_file_location("pp", USER_FILE)
    pp = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(pp)
    postprocess_sequences = pp.postprocess_sequences


def run_case_A():
    """
    构造序列：(0×200, 1×400, 0×200, 1×10, 0×30, 1×250)
    Z 设为等间距递增（mm_per_sample 可调）
    预期：open_close_win=15 将去除 1×10 的短段
    """
    mm_per_sample = 2.0  # 每个样本对应的位移（mm），按你真实采样改
    flags = [0]*200 + [1]*400 + [0]*200 + [1]*10 + [0]*30 + [1]*250
    zs = [i * mm_per_sample for i in range(len(flags))]

    params = dict(
        open_close_win=15,
        min_segment_mm=60,
        safety_delta_mm=25,
        brush_offset_mm=0,
        merge_gap_mm=30,
        output_mode="segments",
    )

    segs = postprocess_sequences(flags, zs, **params)

    print("=== 用例A：人工序列 ===")
    print(f"输入长度: {len(flags)} 样本")
    print("输出段(仅展示前10条)：flag, z_start, z_end")
    for row in segs[:10]:
        print(row)
    print(f"总段数: {len(segs)}")
    print()


def run_case_B():
    """
    从 CSV 测试：期望 CSV 至少包含列 'flag','z'
    默认路径 logs/sample.csv；可用环境变量 POST_CSV 覆盖
    """
    csv_path = os.getenv("POST_CSV", r"D:\workspace\绝缘子清洗机器人\项目代码\草稿版本0908-3\insulator_bot\logs\sample.csv")
    if not os.path.exists(csv_path):
        print(f"[跳过用例B] 未找到 {csv_path}")
        return

    flags, zs = [], []
    with open(csv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            flags.append(int(float(row["flag"])))
            zs.append(float(row["z"]))

    params = dict(
        open_close_win=15,
        min_segment_mm=60,
        safety_delta_mm=25,
        brush_offset_mm=0,
        merge_gap_mm=30,
        output_mode="segments",
    )

    segs = postprocess_sequences(flags, zs, **params)

    print("=== 用例B：CSV 序列 ===")
    print(f"读取: {csv_path}，样本数={len(flags)}")
    print("输出段(仅展示前10条)：flag, z_start, z_end")
    for row in segs[:10]:
        print(row)
    print(f"总段数: {len(segs)}")
    print()


if __name__ == "__main__":
    run_case_A()
    # run_case_B()
