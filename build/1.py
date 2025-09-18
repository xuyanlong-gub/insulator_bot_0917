# Create project structure and files according to the MD guide.
import os, textwrap, json, sys, shutil, zipfile, pathlib, random, math, time

base = r"D:\workspace\绝缘子清洗机器人\项目代码\草稿版本0908-3\insulator_bot\build"
os.makedirs(base, exist_ok=True)

def write(path, content):
    path = os.path.join(base, path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

# --------------------------
# requirements.txt
# --------------------------
write("requirements.txt", textwrap.dedent("""\
    opencv-python
    numpy
    pyyaml
    # 可选：若需要直接加载 YOLOv8 权重
    ultralytics
    torch
"""))

# --------------------------
# README.md
# --------------------------
write("README.md", textwrap.dedent("""\
    # 绝缘子清洗机器人（三阶段协议重构版）

    本项目根据《GPT5 Agent 重构指南》重构，包含：视觉检测、中心带判定、采样后处理、三阶段 Modbus 通讯状态机、模拟 PLC、可视化与配置。

    ## 一、环境
    ```bash
    pip install -r requirements.txt
    ```

    ## 二、启动模拟 PLC（建议先在本机联调）
    ```bash
    python -m insulator_bot.comms.plc_sim  # 监听 0.0.0.0:15020
    ```

    ## 三、运行主流程（视频源或相机）
    ```bash
    # 使用默认配置与示例参数（请先修改 config.yaml 中模型路径）
    python -m insulator_bot.main --config config.yaml --video path/to/demo.mp4
    ```

    ## 四、仅离线后处理与可视化
    ```bash
    python -m insulator_bot.viz.visualize --csv logs/sample.csv --video path/to/demo.mp4
    ```

    ## 五、目录
    ```text
    insulator_bot/
    ├─ core/                 # 配置、日志、工具
    ├─ vision/               # 检测、中心带判定、投票
    ├─ pipeline/             # 采样、后处理、段映射、状态机
    ├─ comms/                # Modbus 客户端与模拟 PLC
    ├─ viz/                  # 可视化
    ├─ main.py               # 程序入口
    ├─ config.yaml           # 配置
    └─ requirements.txt
    ```

    ## 六、三阶段交互协议要点
    - 浮点寄存器（float32，大端，1 float=2 regs）；固定偏移：VERSION、CMD、ARG0..ARG4、STATUS、Z、DIS、HEARTBEAT；
    - CMD：0 idle，1 tick，2 stop_ascend，3 start_seg，4 abort；
    - STATUS 位：1 READY，2 BUSY，4 Z_VALID，8 AT_MAX，16 ACK，32 SEG_DONE，64 ERROR；
    - 上升：周期写 TICK→读 STATUS|Z 并记录 [flag,Z]；
    - 终止：写 STOP_ASC（ARG0=1 顶端/2 顶部位）→等待 ACK；
    - 下降：逐段写 START_SEG（ARG0=Z_start, ARG1=offset_step, ARG2=n_steps, ARG3=dis, ARG4=is_last）→等待 ACK→等待 SEG_DONE。

    ## 七、连接真实 PLC 的注意事项
    - Windows 防火墙放行 TCP/502 或实际端口；
    - 确认上位机与 PLC 在同一网段，禁用虚拟网卡对优先级的影响；
    - 读写保持寄存器时注意字节序：本项目使用 float32 大端，字序高字在前；
    - 超时与重试策略：ACK/SEG_DONE 等待超时自动重发，掉线可重连；
    - 对端需按本文协议置位/清位 STATUS 位，保证幂等。

    ## 八、验证路线
    1. 启动 `plc_sim`，观察控制台打印；
    2. 运行 `python -m insulator_bot.main --config config.yaml --video path/to/demo.mp4`；
    3. 结束后检查 `logs/sample.csv` 与日志，确认段下发；
    4. 可在 `postproc` 中调整形态学窗口、最小段、边界缩退与合并参数。

    ## 九、License
    本仓库仅用于内部联调与演示。
"""))

# --------------------------
# __init__.py
# --------------------------
write("__init__.py", "")

# --------------------------
# core/config.py
# --------------------------
write("core/config.py", textwrap.dedent("""\
    # -*- coding: utf-8 -*-
    from __future__ import annotations
    import yaml
    from dataclasses import dataclass, field
    from typing import Any, Dict

    @dataclass
    class Config:
        data: Dict[str, Any] = field(default_factory=dict)

        @classmethod
        def load(cls, path: str) -> "Config":
            with open(path, "r", encoding="utf-8") as f:
                d = yaml.safe_load(f) or {}
            return cls(d)

        def get(self, key: str, default=None):
            return self.data.get(key, default)

        def section(self, name: str) -> Dict[str, Any]:
            return dict(self.data.get(name, {}))
"""))

# --------------------------
# core/logger.py
# --------------------------
write("core/logger.py", textwrap.dedent("""\
    # -*- coding: utf-8 -*-
    import logging, os

    def setup_logger(level: str = "INFO", logfile: str | None = None):
        lvl = getattr(logging, level.upper(), logging.INFO)
        fmt = '[%(asctime)s] %(levelname)s: %(message)s'
        logging.basicConfig(level=lvl, format=fmt)
        if logfile:
            os.makedirs(os.path.dirname(logfile), exist_ok=True)
            fh = logging.FileHandler(logfile, encoding='utf-8')
            fh.setLevel(lvl); fh.setFormatter(logging.Formatter(fmt))
            logging.getLogger().addHandler(fh)
"""))

# --------------------------
# core/utils.py
# --------------------------
write("core/utils.py", textwrap.dedent("""\
    # -*- coding: utf-8 -*-
    from __future__ import annotations
    import struct, time

    # ================= Modbus float32 大端与寄存器转换 =================
    def float_to_regs_be(val: float) -> tuple[int, int]:
        \"\"\"float32 -> (hi, lo) 16位寄存器（大端，word-order 高字在前）。\"\"\"
        b = struct.pack('>f', float(val))
        hi = int.from_bytes(b[0:2], 'big')
        lo = int.from_bytes(b[2:4], 'big')
        return hi, lo

    def regs_to_float_be(hi: int, lo: int) -> float:
        \"\"\"(hi,lo) 16位寄存器 -> float32（大端）。\"\"\"
        b = hi.to_bytes(2, 'big') + lo.to_bytes(2, 'big')
        return struct.unpack('>f', b)[0]

    # ================== 简易计时器 ==================
    class Ticker:
        \"\"\"按 period_s 周期满足时返回 True，用于采样调度。\"\"\"
        def __init__(self, period_s: float):
            self.period = float(period_s)
            self.t_last = time.time()

        def ready(self) -> bool:
            now = time.time()
            if now - self.t_last >= self.period:
                self.t_last = now
                return True
            return False
"""))

# --------------------------
# comms/modbus.py  客户端与协议常量
# --------------------------
write("comms/modbus.py", textwrap.dedent("""\
    # -*- coding: utf-8 -*-
    \"\"\"Modbus TCP 最小客户端 + 协议常量与高级 API。注释为中文。\"\"\"
    from __future__ import annotations
    import socket, struct, time
    from typing import Iterable, Tuple, List

    from ..core.utils import float_to_regs_be, regs_to_float_be

    # ============ 协议常量 ============
    CMD_IDLE      = 0.0
    CMD_TICK      = 1.0
    CMD_STOP_ASC  = 2.0
    CMD_START_SEG = 3.0
    CMD_ABORT     = 4.0

    ST_READY   = 1
    ST_BUSY    = 2
    ST_Z_VALID = 4
    ST_AT_MAX  = 8
    ST_ACK     = 16
    ST_SEG_DONE= 32
    ST_ERROR   = 64

    # 浮点寄存器偏移（单位：以 float 为步长；实际地址=REG_BASE+off*2）
    OFF_VERSION   = 0
    OFF_CMD       = 1
    OFF_ARG0      = 2
    OFF_ARG1      = 3
    OFF_ARG2      = 4
    OFF_ARG3      = 5
    OFF_ARG4      = 6
    OFF_STATUS    = 7
    OFF_Z         = 8
    OFF_DIS       = 9
    OFF_HEARTBEAT = 10
    TOTAL_FLOATS  = 11
    TOTAL_REGS    = TOTAL_FLOATS * 2

    class ModbusClient:
        \"\"\"仅支持 FC03（读保持寄存器）与 FC16（写多个保持寄存器）。\"\"\"
        def __init__(self, host: str, port: int = 502, unit_id: int = 1, timeout: float = 2.0):
            self.host, self.port, self.unit_id, self.timeout = host, port, unit_id, timeout
            self.txn = 1
            self.sock: socket.socket | None = None
            self.connect()

        def connect(self):
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))
            self.sock = s

        def _send_pdu(self, pdu: bytes) -> bytes:
            assert self.sock is not None
            self.txn = (self.txn + 1) & 0xFFFF or 1
            mbap = struct.pack('>HHHB', self.txn, 0, len(pdu)+1, self.unit_id)
            self.sock.sendall(mbap + pdu)
            # 读响应 MBAP
            hdr = self.sock.recv(7)
            if not hdr: raise ConnectionError("连接中断")
            txn, proto, length, uid = struct.unpack('>HHHB', hdr)
            body = self.sock.recv(length-1)
            return body

        def read_regs(self, addr: int, count: int) -> List[int]:
            pdu = struct.pack('>BHH', 3, addr, count)
            body = self._send_pdu(pdu)
            if not body or body[0] != 3:
                raise RuntimeError("FC03 响应异常")
            bc = body[1]
            data = body[2:2+bc]
            regs = list(struct.unpack('>' + 'H'*(bc//2), data))
            return regs

        def write_regs(self, addr: int, regs: Iterable[int]) -> None:
            regs = list(regs)
            count = len(regs)
            pdu = struct.pack('>BHHB', 16, addr, count, count*2) + struct.pack('>' + 'H'*count, *regs)
            body = self._send_pdu(pdu)
            if not body or body[0] != 16:
                raise RuntimeError("FC16 响应异常")

        # ====== 高级 API：写命令/参数、写测距与心跳、读状态与 Z ======
        def write_cmd(self, reg_base: int, cmd: float, args: Tuple[float, float, float, float, float] = (0,0,0,0,0)):
            # CMD 与 ARG0..ARG4 连续写入
            floats = [cmd, *args]
            regs: list[int] = []
            for f in floats:
                hi, lo = float_to_regs_be(f)
                regs.extend([hi, lo])
            self.write_regs(reg_base + OFF_CMD*2, regs)

        def write_distance(self, reg_base: int, dis_mm: float):
            hi, lo = float_to_regs_be(dis_mm)
            self.write_regs(reg_base + OFF_DIS*2, [hi, lo])

        def write_heartbeat(self, reg_base: int, hb: float):
            hi, lo = float_to_regs_be(hb)
            self.write_regs(reg_base + OFF_HEARTBEAT*2, [hi, lo])

        def read_status_and_z(self, reg_base: int) -> tuple[int, float]:
            regs = self.read_regs(reg_base + OFF_STATUS*2, 4)  # STATUS(2) + Z(2)
            st = int(regs_to_float_be(regs[0], regs[1]))
            z  = float(regs_to_float_be(regs[2], regs[3]))
            return st, z

        # 等待位：返回 True 表示满足
        def wait_ack(self, reg_base: int, timeout: float = 3.0, poll_s: float = 0.05) -> bool:
            t0 = time.time()
            while time.time() - t0 < timeout:
                st, _ = self.read_status_and_z(reg_base)
                if st & ST_ACK: return True
                time.sleep(poll_s)
            return False

        def wait_seg_done(self, reg_base: int, timeout: float = 5.0, poll_s: float = 0.05) -> bool:
            t0 = time.time()
            while time.time() - t0 < timeout:
                st, _ = self.read_status_and_z(reg_base)
                if st & ST_SEG_DONE: return True
                time.sleep(poll_s)
            return False
"""))

# --------------------------
# comms/plc_sim.py  基于用户版本，改为导入本项目常量
# --------------------------
write("comms/plc_sim.py", textwrap.dedent("""\
    # -*- coding: utf-8 -*-
    \"\"\"最小可用的 Modbus TCP 服务器（仅 FC03/FC16）。用于联调。\"\"\"
    from __future__ import annotations
    import socket, struct, threading, time

    from ..core.utils import float_to_regs_be, regs_to_float_be
    from .modbus import (
        CMD_IDLE, CMD_TICK, CMD_STOP_ASC, CMD_START_SEG, CMD_ABORT,
        ST_READY, ST_BUSY, ST_Z_VALID, ST_AT_MAX, ST_ACK, ST_SEG_DONE, ST_ERROR,
        OFF_VERSION, OFF_CMD, OFF_ARG0, OFF_ARG1, OFF_ARG2, OFF_ARG3, OFF_ARG4,
        OFF_STATUS, OFF_Z, OFF_DIS, OFF_HEARTBEAT, TOTAL_REGS
    )

    HOST, PORT, UNIT_ID = '0.0.0.0', 15020, 1
    REG_BASE = 0
    Z_MAX_MM = 2500.0
    ASCEND_V_MM_S = 80.0
    EXEC_SEG_TIME_S = 0.6

    REGS = [0] * (REG_BASE + TOTAL_REGS)

    def write_float(off_regs: int, val: float):
        hi, lo = float_to_regs_be(val)
        REGS[REG_BASE + off_regs + 0] = hi
        REGS[REG_BASE + off_regs + 1] = lo

    def read_float(off_regs: int) -> float:
        hi = REGS[REG_BASE + off_regs + 0]
        lo = REGS[REG_BASE + off_regs + 1]
        return regs_to_float_be(hi, lo)

    def set_status(mask: int, enable: bool=True):
        s = int(read_float(OFF_STATUS))
        s = (s | mask) if enable else (s & ~mask)
        write_float(OFF_STATUS, float(s))

    def init_regs():
        write_float(OFF_VERSION, 100.2)
        write_float(OFF_CMD, CMD_IDLE)
        for off in (OFF_ARG0,OFF_ARG1,OFF_ARG2,OFF_ARG3,OFF_ARG4,OFF_DIS,OFF_HEARTBEAT):
            write_float(off, 0.0)
        write_float(OFF_Z, 0.0)
        write_float(OFF_STATUS, float(ST_READY))

    def logic_tick(dt: float):
        z = read_float(OFF_Z)
        z = min(z + ASCEND_V_MM_S * dt, Z_MAX_MM)
        write_float(OFF_Z, z)
        if z >= Z_MAX_MM: set_status(ST_AT_MAX, True)

    def handle_command():
        cmd = read_float(OFF_CMD)
        if cmd == CMD_TICK:
            set_status(ST_Z_VALID, True)
            set_status(ST_ACK, False)
            set_status(ST_SEG_DONE, False)
        elif cmd == CMD_STOP_ASC:
            set_status(ST_ACK, True)
            write_float(OFF_CMD, CMD_IDLE)
        elif cmd == CMD_START_SEG:
            z_start = read_float(OFF_ARG0)
            step    = read_float(OFF_ARG1)
            nsteps  = int(read_float(OFF_ARG2))
            dis     = read_float(OFF_ARG3)
            is_last = int(read_float(OFF_ARG4))
            set_status(ST_ACK, True)
            set_status(ST_BUSY, True)
            def do_seg():
                time.sleep(EXEC_SEG_TIME_S)
                set_status(ST_SEG_DONE, True)
                set_status(ST_BUSY, False)
                set_status(ST_ACK, False)
                if is_last: write_float(OFF_CMD, CMD_IDLE)
            threading.Thread(target=do_seg, daemon=True).start()
        elif cmd == CMD_ABORT:
            set_status(ST_ERROR, True)

    def serve():
        init_regs()
        def client_thread(conn):
            try:
                while True:
                    mbap = conn.recv(7)
                    if not mbap: break
                    txn, proto, length, uid = struct.unpack('>HHHB', mbap)
                    pdu  = conn.recv(length-1)
                    fcode = pdu[0]
                    if fcode == 3:
                        addr, count = struct.unpack('>HH', pdu[1:5])
                        data = REGS[addr:addr+count]
                        resp = struct.pack('>BB', 3, count*2) + struct.pack('>'+'H'*count, *data)
                    elif fcode == 16:
                        addr, count, bc = struct.unpack('>HHB', pdu[1:6])
                        vals = list(struct.unpack('>'+'H'*count, pdu[6:6+bc]))
                        REGS[addr:addr+count] = vals
                        resp = struct.pack('>BHH', 16, addr, count)
                        handle_command()
                    else:
                        resp = struct.pack('>B', fcode | 0x80) + b'\\x01'
                    mbap2 = struct.pack('>HHHB', txn, 0, len(resp)+1, uid)
                    conn.sendall(mbap2 + resp)
            finally:
                conn.close()

        def physics_loop():
            t0 = time.time()
            while True:
                t1 = time.time()
                logic_tick(t1 - t0)
                t0 = t1
                time.sleep(0.05)

        threading.Thread(target=physics_loop, daemon=True).start()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((HOST, PORT))
            s.listen(5)
            print(f"[PLC_SIM] listening on {HOST}:{PORT}, unit={UNIT_ID}")
            while True:
                c, _ = s.accept()
                threading.Thread(target=client_thread, args=(c,), daemon=True).start()

    if __name__ == '__main__':
        serve()
"""))

# --------------------------
# vision/detector.py  迁移用户检测器
# --------------------------
detector_py = open("/mnt/data/9e175f54-b5d1-4d21-82a4-cfcab1bf361f.py","r",encoding="utf-8").read()
write("vision/detector.py", detector_py.replace("from __future__ import annotations", "# -*- coding: utf-8 -*-\nfrom __future__ import annotations"))

# --------------------------
# vision/center_band.py  从 main.py 提取中心带判定
# --------------------------
write("vision/center_band.py", textwrap.dedent("""\
    # -*- coding: utf-8 -*-
    from __future__ import annotations
    from typing import List

    def judge_center_band(detections: List[List[float]], conf_thr: dict[str, float],
                          img_height: int, band_width: int) -> int:
        \"\"\"中心带可清判定。禁清类优先，其次片体。完全覆盖优先于部分覆盖。\"\"\"
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
"""))

# --------------------------
# vision/kf_vote.py  投票器（来自 utils）+ 可选卡尔曼占位
# --------------------------
utils_src = open("/mnt/data/db33d931-8ced-4774-b103-33ea71f9ba32.py","r",encoding="utf-8").read()
write("vision/kf_vote.py", textwrap.dedent("""\
    # -*- coding: utf-8 -*-
""") + utils_src + textwrap.dedent("""\

    # 这里保留 VotingBuffer，用于稳定帧级判定；如需概率卡尔曼，可在此扩展。
"""))

# --------------------------
# pipeline/postprocess.py  迁移用户后处理
# --------------------------
post_src = open("/mnt/data/8226d448-4a69-4a4b-bd2e-408cdfd36dac.py","r",encoding="utf-8").read()
# 修正 import 路径：utils -> vision.kf_vote 中提供 remove_small_segments
post_src = post_src.replace("from utils import remove_small_segments", "from ..vision.kf_vote import remove_small_segments")
write("pipeline/postprocess.py", post_src)

# --------------------------
# pipeline/segments.py  段到下发参数映射
# --------------------------
write("pipeline/segments.py", textwrap.dedent("""\
    # -*- coding: utf-8 -*-
    \"\"\"将段表转换为下发参数 (Z_start, step, n_steps, dis, is_last)。\"\"\"
    from __future__ import annotations
    from typing import List, Tuple

    def segments_to_commands(segments: List[Tuple[int, float, float]], dis_mm: float,
                             step_mm: float = 5.0) -> List[tuple[float,float,int,float,int]]:
        \"\"\"仅对 flag==1 的段生成参数。\"\"\"
        cmds: list[tuple[float,float,int,float,int]] = []
        clean = [(s,e) for f,s,e in segments if f==1]
        for i,(s,e) in enumerate(clean):
            length = max(0.0, e - s)
            n = max(1, int(round(length/step_mm)))
            is_last = 1 if i == len(clean)-1 else 0
            cmds.append((s, step_mm, n, dis_mm, is_last))
        return cmds
"""))

# --------------------------
# pipeline/sampler.py  上升阶段采样
# --------------------------
write("pipeline/sampler.py", textwrap.dedent("""\
    # -*- coding: utf-8 -*-
    from __future__ import annotations
    import time, logging, cv2, numpy as np
    from typing import List, Tuple

    from ..vision.detector import Detector
    from ..vision.center_band import judge_center_band
    from ..vision.kf_vote import VotingBuffer
    from ..core.utils import Ticker
    from ..comms.modbus import ModbusClient, CMD_TICK, OFF_ARG0

    def run_sampling(mod: ModbusClient, reg_base: int, detector: Detector, video: str | None,
                     period_s: float, conf_thr: dict, center_band_px: int,
                     vote_k: int, vote_t: int) -> tuple[list[int], list[float]]:
        \"\"\"执行上升阶段：周期写 TICK 并记录 [flag,z]。\"\"\"
        voter = VotingBuffer(window_size=vote_k, vote_threshold=vote_t)
        flags: list[int] = []; zs: list[float] = []
        cap = None
        if video:
            cap = cv2.VideoCapture(video)
            if not cap.isOpened():
                logging.error("无法打开视频：%s", video)
                cap = None
        ticker = Ticker(period_s)
        logging.info("开始采样...")
        t0_ms = int(time.time()*1000)
        while True:
            # 读取帧或黑图
            if cap:
                ret, frame = cap.read()
                if not ret:
                    logging.info("视频结束，停止采样")
                    break
                frame = cv2.resize(frame, (640, 480))
            else:
                frame = np.zeros((480, 640, 3), dtype=np.uint8)

            dets = Detector.detect(detector, frame)
            flag_frame = judge_center_band(dets, conf_thr, frame.shape[0], center_band_px)
            flag = voter.update(flag_frame)

            if ticker.ready():
                # CMD=1 + ARG0=timestamp_ms，仅示意
                arg0 = float(int(time.time()*1000) - t0_ms)
                # 写 CMD 与 ARG0..ARG4（其余 0）
                mod.write_cmd(reg_base, CMD_TICK, (arg0,0,0,0,0))
                st, z = mod.read_status_and_z(reg_base)
                flags.append(int(flag)); zs.append(float(z))
                logging.info("采样 flag=%d, z=%.2f, STATUS=0x%02X", flag, z, st)

                # 到顶或 AT_MAX 退出（由状态位给出）
                if st & 8:  # ST_AT_MAX
                    logging.info("检测到 AT_MAX，结束采样")
                    break
        if cap: cap.release()
        return flags, zs
"""))

# --------------------------
# pipeline/state_machine.py  三阶段状态机
# --------------------------
write("pipeline/state_machine.py", textwrap.dedent("""\
    # -*- coding: utf-8 -*-
    from __future__ import annotations
    import logging, time
    from typing import List

    from ..comms.modbus import ModbusClient, CMD_STOP_ASC, CMD_START_SEG
    from ..pipeline.segments import segments_to_commands

    def negotiate_stop(mod: ModbusClient, reg_base: int, reason: float = 2.0, timeout: float = 3.0) -> bool:
        \"\"\"终止上升：CMD_STOP_ASC(ARG0=reason)，等待 ACK。\"\"\"
        mod.write_cmd(reg_base, CMD_STOP_ASC, (reason,0,0,0,0))
        ok = mod.wait_ack(reg_base, timeout=timeout)
        logging.info("终止协商 ACK=%s", ok)
        return ok

    def descend_execute(mod: ModbusClient, reg_base: int, segments: List[List[float]], dis_mm: float) -> None:
        \"\"\"按段下发 CMD_START_SEG，等待 ACK 与 SEG_DONE。\"\"\"
        cmds = segments_to_commands([(int(f), s, e) for f,s,e in segments], dis_mm=dis_mm)
        logging.info("下发段数：%d", len(cmds))
        for (z_start, step, n, dis, is_last) in cmds:
            logging.info("START_SEG z=%.1f step=%.1f n=%d dis=%.1f last=%d", z_start, step, n, dis, is_last)
            mod.write_cmd(reg_base, CMD_START_SEG, (z_start, step, float(n), dis, float(is_last)))
            if not mod.wait_ack(reg_base, timeout=3.0):
                logging.warning("ACK 超时，重试一次")
                mod.write_cmd(reg_base, CMD_START_SEG, (z_start, step, float(n), dis, float(is_last)))
                mod.wait_ack(reg_base, timeout=3.0)
            ok = mod.wait_seg_done(reg_base, timeout=max(3.0, 0.1*n))
            logging.info("SEG_DONE=%s", ok)
"""))

# --------------------------
# viz/visualize.py  简易可视化（叠加中心带与采样点）
# --------------------------
write("viz/visualize.py", textwrap.dedent("""\
    # -*- coding: utf-8 -*-
    from __future__ import annotations
    import csv, cv2, numpy as np, argparse

    def draw_center_band(img: np.ndarray, band_px: int = 20):
        h, w = img.shape[:2]
        cy = h//2; b=band_px//2
        cv2.rectangle(img, (0, cy-b), (w-1, cy+b), (0,255,0), 1)

    def main(csv_path: str, video_path: str):
        caps = cv2.VideoCapture(video_path)
        flags = []
        with open(csv_path, newline='', encoding='utf-8') as f:
            r = csv.DictReader(f)
            for row in r:
                flags.append(int(float(row['flag'])))
        i=0
        while True:
            ok, frame = caps.read()
            if not ok: break
            frame = cv2.resize(frame, (640,480))
            draw_center_band(frame, 20)
            if i < len(flags):
                cv2.putText(frame, f"flag={flags[i]}", (10,30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
            cv2.imshow("viz", frame); i+=1
            if cv2.waitKey(1) == 27: break
        caps.release(); cv2.destroyAllWindows()

    if __name__ == "__main__":
        ap = argparse.ArgumentParser()
        ap.add_argument("--csv", required=True)
        ap.add_argument("--video", required=True)
        a = ap.parse_args()
        main(a.csv, a.video)
"""))

# --------------------------
# main.py  项目入口：读取配置→状态机
# --------------------------
config_yaml = open("/mnt/data/62d535db-53f3-4837-8092-c83c99813180.yaml","r",encoding="utf-8").read()
write("config.yaml", config_yaml)
write("main.py", textwrap.dedent("""\
    # -*- coding: utf-8 -*-
    \"\"\"入口：三阶段流程。\"\"\"
    from __future__ import annotations
    import argparse, logging, os, csv

    from .core.config import Config
    from .core.logger import setup_logger
    from .vision.detector import Detector
    from .pipeline.postprocess import postprocess_sequences
    from .pipeline.sampler import run_sampling
    from .pipeline.state_machine import negotiate_stop, descend_execute
    from .comms.modbus import ModbusClient

    def save_csv(path: str, flags, zs):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline='', encoding='utf-8') as f:
            w = csv.writer(f); w.writerow(["flag","z"]); w.writerows([[f,z] for f,z in zip(flags,zs)])

    def main(cfg_path: str, video_path: str | None):
        cfg = Config.load(cfg_path)
        log_cfg = cfg.section("logging")
        setup_logger(level=log_cfg.get("level","INFO"), logfile=log_cfg.get("file", None))

        # 视觉配置
        vcfg = cfg.section("vision")
        weight = vcfg.get("weight_path")
        conf_thr = vcfg.get("conf_thr", {})
        center_band_px = int(vcfg.get("center_band_px", 20))
        vote_k = int(vcfg.get("vote_k", 5)); vote_t = int(vcfg.get("vote_t", 3))

        # 采样配置
        scfg = cfg.section("sampling")
        period_s = float(scfg.get("period_s", 1.0))

        # 后处理配置
        pcfg = cfg.section("postproc")
        open_close_win = int(pcfg.get("open_close_win", 3))
        min_segment_mm = float(pcfg.get("min_segment_mm", 60))
        safety_delta_mm = float(pcfg.get("safety_delta_mm", 25))
        brush_offset_mm = float(pcfg.get("brush_offset_mm", 0))
        merge_gap_mm = float(pcfg.get("merge_gap_mm", 30))
        output_mode = pcfg.get("output_mode", "segments")

        # Modbus
        mcfg = cfg.section("modbus")
        host = mcfg.get("host", "127.0.0.1")
        port = int(mcfg.get("port", 15020))
        unit_id = int(mcfg.get("unit_id", 1))
        reg_base = int(mcfg.get("reg_base", 0))

        # 初始化
        det = Detector(weight)
        mod = ModbusClient(host, port, unit_id, timeout=2.0)

        # Phase-1 上升采样
        flags, zs = run_sampling(mod, reg_base, det, video_path, period_s, conf_thr, center_band_px, vote_k, vote_t)

        # 保存原始采样
        csv_path = log_cfg.get("csv_path", "logs/sample.csv")
        save_csv(csv_path, flags, zs)

        # Phase-2 终止协商
        negotiate_stop(mod, reg_base, reason=2.0, timeout=3.0)

        # Phase-1.5 后处理
        processed = postprocess_sequences(flags, zs, open_close_win, min_segment_mm, safety_delta_mm, brush_offset_mm, merge_gap_mm, output_mode="segments")

        # Phase-3 逐段执行
        descend_execute(mod, reg_base, processed, dis_mm=-1.0)

        logging.info("流程结束。")

    if __name__ == "__main__":
        ap = argparse.ArgumentParser()
        ap.add_argument("--config", required=True)
        ap.add_argument("--video", default=None)
        a = ap.parse_args()
        main(a.config, a.video)
"""))

# --------------------------
# __init__ for subpackages
# --------------------------
for pkg in ["core","vision","pipeline","comms","viz"]:
    write(f"{pkg}/__init__.py", "")

# --------------------------
# # 打包 ZIP
# # --------------------------
# zip_path = "/mnt/data/insulator_bot_project.zip"
# with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
#     for root, dirs, files in os.walk(base):
#         for f in files:
#             p = os.path.join(root, f)
#             z.write(p, os.path.relpath(p, "/mnt/data"))

