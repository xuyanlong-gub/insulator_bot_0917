# # -*- coding: utf-8 -*-
# """Modbus TCP 最小客户端 + 协议常量与高级 API。注释为中文。"""
# from __future__ import annotations
# import socket, struct, time
# from typing import Iterable, Tuple, List
#
# from core.utils import float_to_regs_be, regs_to_float_be
#
# # ============ 协议常量 ============
# CMD_IDLE      = 0.0
# CMD_TICK      = 1.0
# CMD_STOP_ASC  = 2.0
# CMD_START_SEG = 3.0
# CMD_ABORT     = 4.0
#
# ST_READY   = 1
# ST_BUSY    = 2
# ST_Z_VALID = 4
# ST_AT_MAX  = 8
# ST_ACK     = 16
# ST_SEG_DONE= 32
# ST_ERROR   = 64
#
# # 浮点寄存器偏移（单位：以 float 为步长；实际地址=REG_BASE+off*2）
# OFF_VERSION   = 0
# OFF_CMD       = 1
# OFF_ARG0      = 2
# OFF_ARG1      = 3
# OFF_ARG2      = 4
# OFF_ARG3      = 5
# OFF_ARG4      = 6
# OFF_STATUS    = 7
# OFF_Z         = 8
# OFF_DIS       = 9
# OFF_HEARTBEAT = 10
# TOTAL_FLOATS  = 11
# TOTAL_REGS    = TOTAL_FLOATS * 2
#
# class ModbusClient:
#     """仅支持 FC03（读保持寄存器）与 FC16（写多个保持寄存器）。"""
#     def __init__(self, host: str, port: int = 502, unit_id: int = 1, timeout: float = 2.0):
#         self.host, self.port, self.unit_id, self.timeout = host, port, unit_id, timeout
#         self.txn = 1
#         self.sock: socket.socket | None = None
#         self.connect()
#
#     def connect(self):
#         if self.sock:
#             try:
#                 self.sock.close()
#             except Exception:
#                 pass
#         s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#         s.settimeout(self.timeout)
#         s.connect((self.host, self.port))
#         self.sock = s
#
#     def _send_pdu(self, pdu: bytes) -> bytes:
#         assert self.sock is not None
#         self.txn = (self.txn + 1) & 0xFFFF or 1
#         mbap = struct.pack('>HHHB', self.txn, 0, len(pdu)+1, self.unit_id)
#         self.sock.sendall(mbap + pdu)
#         # 读响应 MBAP
#         hdr = self.sock.recv(7)
#         if not hdr: raise ConnectionError("连接中断")
#         txn, proto, length, uid = struct.unpack('>HHHB', hdr)
#         body = self.sock.recv(length-1)
#         return body
#
#     def read_regs(self, addr: int, count: int) -> List[int]:
#         pdu = struct.pack('>BHH', 3, addr, count)
#         body = self._send_pdu(pdu)
#         if not body or body[0] != 3:
#             raise RuntimeError("FC03 响应异常")
#         bc = body[1]
#         data = body[2:2+bc]
#         regs = list(struct.unpack('>' + 'H'*(bc//2), data))
#         return regs
#
#     def write_regs(self, addr: int, regs: Iterable[int]) -> None:
#         regs = list(regs)
#         count = len(regs)
#         pdu = struct.pack('>BHHB', 16, addr, count, count*2) + struct.pack('>' + 'H'*count, *regs)
#         body = self._send_pdu(pdu)
#         if not body or body[0] != 16:
#             raise RuntimeError("FC16 响应异常")
#
#     # ====== 高级 API：写命令/参数、写测距与心跳、读状态与 Z ======
#     def write_cmd(self, reg_base: int, cmd: float, args: Tuple[float, float, float, float, float] = (0,0,0,0,0)):
#         # CMD 与 ARG0..ARG4 连续写入
#         floats = [cmd, *args]
#         regs: list[int] = []
#         for f in floats:
#             hi, lo = float_to_regs_be(f)
#             regs.extend([hi, lo])
#         self.write_regs(reg_base + OFF_CMD*2, regs)
#
#     def write_distance(self, reg_base: int, dis_mm: float):
#         hi, lo = float_to_regs_be(dis_mm)
#         self.write_regs(reg_base + OFF_DIS*2, [hi, lo])
#
#     def write_heartbeat(self, reg_base: int, hb: float):
#         hi, lo = float_to_regs_be(hb)
#         self.write_regs(reg_base + OFF_HEARTBEAT*2, [hi, lo])
#
#     def read_status_and_z(self, reg_base: int) -> tuple[int, float]:
#         regs = self.read_regs(reg_base + OFF_STATUS*2, 4)  # STATUS(2) + Z(2)
#         st = int(regs_to_float_be(regs[0], regs[1]))
#         z  = float(regs_to_float_be(regs[2], regs[3]))
#         return st, z
#
#     # 等待位：返回 True 表示满足
#     def wait_ack(self, reg_base: int, timeout: float = 3.0, poll_s: float = 0.05) -> bool:
#         t0 = time.time()
#         while time.time() - t0 < timeout:
#             st, _ = self.read_status_and_z(reg_base)
#             if st & ST_ACK: return True
#             time.sleep(poll_s)
#         return False
#
#     def wait_seg_done(self, reg_base: int, timeout: float = 5.0, poll_s: float = 0.05) -> bool:
#         t0 = time.time()
#         while time.time() - t0 < timeout:
#             st, _ = self.read_status_and_z(reg_base)
#             if st & ST_SEG_DONE: return True
#             time.sleep(poll_s)
#         return False


# -*- coding: utf-8 -*-
"""Modbus TCP 最小客户端 + 新协议类型编解码与高级 API。"""
from __future__ import annotations
import socket, struct, time
from typing import Iterable, Tuple, List

from core.utils import float_to_regs_be, regs_to_float_be

# ============ 新协议：命令与状态 ============
# CMD（INT，HOST写）
CMD_BOOT_OK       = 0
CMD_READY_REQ     = 1
CMD_SAMPLE_UP     = 2     # 采样请求（先递增Z_SIGNAL，再写CMD）
CMD_STOP_ASC      = 3
CMD_START_SEG     = 5
CMD_WAIT_SEG_END  = 6     # 由HOST轮询STATUS实现，无需单独写
CMD_FINISH_ALL    = 7

# STATUS（INT，PLC写）
ST_INIT      = 0
ST_READY     = 1
ST_SAMPLING  = 2   # 采样进行中（Z有效）
ST_STOPPED   = 3
ST_AT_TOP    = 4   # 到达最大伸长
ST_WAIT_SEG  = 5   # 等待分段数据
ST_CLEANING  = 6
ST_DONE      = 7

# ============ 寄存器布局（以“寄存器”为步长，非float偏移） ============
# 表顺序：VERSION(1) CMD(1) STATUS(1) Z(2) Z_SIGNAL(2) H0(2) Delta_H(2) N(2) DIS(2) HEART(1)
OFF_VERSION   = 0
OFF_CMD       = 1
OFF_STATUS    = 2
OFF_Z         = 3          # 占2
OFF_ZSIG      = 5          # 占2, DINT
OFF_H0        = 7          # 占2
OFF_DH        = 9          # 占2
OFF_N         = 11         # 占2, DINT
OFF_DIS       = 13         # 占2
OFF_HEART     = 15
TOTAL_REGS    = 16

class ModbusClient:
    """仅支持 FC03（读保持寄存器）与 FC16（写多个保持寄存器）。"""
    def __init__(self, host: str, port: int = 502, unit_id: int = 1, timeout: float = 2.0):
        self.host, self.port, self.unit_id, self.timeout = host, port, unit_id, timeout
        self.txn = 1
        self.sock: socket.socket | None = None
        self.connect()

    def connect(self):
        if self.sock:
            try: self.sock.close()
            except Exception: pass
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect((self.host, self.port))
        self.sock = s

    def _send_pdu(self, pdu: bytes) -> bytes:
        assert self.sock is not None
        self.txn = (self.txn + 1) & 0xFFFF or 1
        mbap = struct.pack('>HHHB', self.txn, 0, len(pdu)+1, self.unit_id)
        self.sock.sendall(mbap + pdu)
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

    # ============ 编解码辅助（大端，word-order高字在前） ============
    @staticmethod
    def _int_to_reg(v: int) -> int:
        return v & 0xFFFF  # 按无符号打包，解包自行解释

    @staticmethod
    def _reg_to_int(r: int) -> int:
        # 以有符号16位解释
        return r-0x10000 if r & 0x8000 else r

    @staticmethod
    def _dint_to_regs(v: int) -> Tuple[int,int]:
        v &= 0xFFFFFFFF
        hi = (v >> 16) & 0xFFFF
        lo = v & 0xFFFF
        return hi, lo

    @staticmethod
    def _regs_to_dint(hi: int, lo: int) -> int:
        v = ((hi & 0xFFFF) << 16) | (lo & 0xFFFF)
        # 以有符号32位解释
        return v-0x100000000 if v & 0x80000000 else v

    # ============ 基本类型读写 ============
    def write_int(self, reg_base: int, off: int, v: int):
        self.write_regs(reg_base + off, [self._int_to_reg(v)])

    def read_int(self, reg_base: int, off: int) -> int:
        r = self.read_regs(reg_base + off, 1)[0]
        return self._reg_to_int(r)

    def write_dint(self, reg_base: int, off: int, v: int):
        hi, lo = self._dint_to_regs(v)
        self.write_regs(reg_base + off, [hi, lo])

    def read_dint(self, reg_base: int, off: int) -> int:
        hi, lo = self.read_regs(reg_base + off, 2)
        return self._regs_to_dint(hi, lo)

    def write_float(self, reg_base: int, off: int, f: float):
        hi, lo = float_to_regs_be(f)
        self.write_regs(reg_base + off, [hi, lo])

    def read_float(self, reg_base: int, off: int) -> float:
        hi, lo = self.read_regs(reg_base + off, 2)
        return float(regs_to_float_be(hi, lo))

    # ============ 高级便捷API ============
    def write_cmd(self, reg_base: int, cmd: int):
        self.write_int(reg_base, OFF_CMD, cmd)

    def write_z_signal_inc_then_sample(self, reg_base: int):
        cur = self.read_dint(reg_base, OFF_ZSIG)
        self.write_dint(reg_base, OFF_ZSIG, cur + 1)
        self.write_cmd(reg_base, CMD_SAMPLE_UP)

    def write_segment_params(self, reg_base: int, h0: float, dh: float, n: int, dis: float):
        self.write_float(reg_base, OFF_H0, h0)
        self.write_float(reg_base, OFF_DH, dh)
        self.write_dint(reg_base, OFF_N, n)
        self.write_float(reg_base, OFF_DIS, dis)

    def read_status_and_z(self, reg_base: int) -> tuple[int, float]:
        st = self.read_int(reg_base, OFF_STATUS)
        z  = self.read_float(reg_base, OFF_Z)
        return st, z

    def write_heartbeat(self, reg_base: int, hb_val: int):
        self.write_int(reg_base, OFF_HEART, hb_val)

    def dump_regs(self, reg_base: int, count: int = TOTAL_REGS):
        regs = self.read_regs(reg_base, count)
        print(f"== DUMP base={reg_base} count={count} ==")
        for i, r in enumerate(regs):
            print(f"{reg_base+i:04d}: {r:5d} 0x{r:04X}")
        return regs