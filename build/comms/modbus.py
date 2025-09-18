# -*- coding: utf-8 -*-
"""Modbus TCP 最小客户端 + 协议常量与高级 API。注释为中文。"""
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
    """仅支持 FC03（读保持寄存器）与 FC16（写多个保持寄存器）。"""
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
