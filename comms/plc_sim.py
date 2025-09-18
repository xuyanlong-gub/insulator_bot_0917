# # -*- coding: utf-8 -*-
# """最小可用的 Modbus TCP 服务器（仅 FC03/FC16）。用于联调。"""
# from __future__ import annotations
# import socket, struct, threading, time
#
# from core.utils import float_to_regs_be, regs_to_float_be
# from modbus import (
#     CMD_IDLE, CMD_TICK, CMD_STOP_ASC, CMD_START_SEG, CMD_ABORT,
#     ST_READY, ST_BUSY, ST_Z_VALID, ST_AT_MAX, ST_ACK, ST_SEG_DONE, ST_ERROR,
#     OFF_VERSION, OFF_CMD, OFF_ARG0, OFF_ARG1, OFF_ARG2, OFF_ARG3, OFF_ARG4,
#     OFF_STATUS, OFF_Z, OFF_DIS, OFF_HEARTBEAT, TOTAL_REGS
# )
#
# HOST, PORT, UNIT_ID = '127.0.0.1', 15020, 1
# REG_BASE = 0
# Z_MAX_MM = 2500.0
# ASCEND_V_MM_S = 80.0
# EXEC_SEG_TIME_S = 0.6
#
# REGS = [0] * (REG_BASE + TOTAL_REGS)
#
# def write_float(off_regs: int, val: float):
#     hi, lo = float_to_regs_be(val)
#     REGS[REG_BASE + off_regs + 0] = hi
#     REGS[REG_BASE + off_regs + 1] = lo
#
# def read_float(off_regs: int) -> float:
#     hi = REGS[REG_BASE + off_regs + 0]
#     lo = REGS[REG_BASE + off_regs + 1]
#     return regs_to_float_be(hi, lo)
#
# def set_status(mask: int, enable: bool=True):
#     s = int(read_float(OFF_STATUS))
#     s = (s | mask) if enable else (s & ~mask)
#     write_float(OFF_STATUS, float(s))
#
# def init_regs():
#     write_float(OFF_VERSION, 100.2)
#     write_float(OFF_CMD, CMD_IDLE)
#     for off in (OFF_ARG0,OFF_ARG1,OFF_ARG2,OFF_ARG3,OFF_ARG4,OFF_DIS,OFF_HEARTBEAT):
#         write_float(off, 0.0)
#     write_float(OFF_Z, 0.0)
#     write_float(OFF_STATUS, float(ST_READY))
#
# def logic_tick(dt: float):
#     z = read_float(OFF_Z)
#     z = min(z + ASCEND_V_MM_S * dt, Z_MAX_MM)
#     write_float(OFF_Z, z)
#     if z >= Z_MAX_MM: set_status(ST_AT_MAX, True)
#
# def handle_command():
#     cmd = read_float(OFF_CMD)
#     if cmd == CMD_TICK:
#         set_status(ST_Z_VALID, True)
#         set_status(ST_ACK, False)
#         set_status(ST_SEG_DONE, False)
#     elif cmd == CMD_STOP_ASC:
#         set_status(ST_ACK, True)
#         write_float(OFF_CMD, CMD_IDLE)
#     elif cmd == CMD_START_SEG:
#         z_start = read_float(OFF_ARG0)
#         step    = read_float(OFF_ARG1)
#         nsteps  = int(read_float(OFF_ARG2))
#         dis     = read_float(OFF_ARG3)
#         is_last = int(read_float(OFF_ARG4))
#         set_status(ST_ACK, True)
#         set_status(ST_BUSY, True)
#         def do_seg():
#             time.sleep(EXEC_SEG_TIME_S)
#             set_status(ST_SEG_DONE, True)
#             set_status(ST_BUSY, False)
#             set_status(ST_ACK, False)
#             if is_last: write_float(OFF_CMD, CMD_IDLE)
#         threading.Thread(target=do_seg, daemon=True).start()
#     elif cmd == CMD_ABORT:
#         set_status(ST_ERROR, True)
#
# def serve():
#     init_regs()
#     def client_thread(conn):
#         try:
#             while True:
#                 mbap = conn.recv(7)
#                 if not mbap: break
#                 txn, proto, length, uid = struct.unpack('>HHHB', mbap)
#                 pdu  = conn.recv(length-1)
#                 fcode = pdu[0]
#                 if fcode == 3:
#                     addr, count = struct.unpack('>HH', pdu[1:5])
#                     data = REGS[addr:addr+count]
#                     resp = struct.pack('>BB', 3, count*2) + struct.pack('>'+'H'*count, *data)
#                 elif fcode == 16:
#                     addr, count, bc = struct.unpack('>HHB', pdu[1:6])
#                     vals = list(struct.unpack('>'+'H'*count, pdu[6:6+bc]))
#                     REGS[addr:addr+count] = vals
#                     resp = struct.pack('>BHH', 16, addr, count)
#                     handle_command()
#                 else:
#                     resp = struct.pack('>B', fcode | 0x80) + b'\x01'
#                 mbap2 = struct.pack('>HHHB', txn, 0, len(resp)+1, uid)
#                 conn.sendall(mbap2 + resp)
#         finally:
#             conn.close()
#
#     def physics_loop():
#         t0 = time.time()
#         while True:
#             t1 = time.time()
#             logic_tick(t1 - t0)
#             t0 = t1
#             time.sleep(0.05)
#
#     threading.Thread(target=physics_loop, daemon=True).start()
#     with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
#         s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
#         s.bind((HOST, PORT))
#         s.listen(5)
#         print(f"[PLC_SIM] listening on {HOST}:{PORT}, unit={UNIT_ID}")
#         while True:
#             c, _ = s.accept()
#             threading.Thread(target=client_thread, args=(c,), daemon=True).start()
#
# if __name__ == '__main__':
#     serve()

# -*- coding: utf-8 -*-
"""最小可用的 Modbus TCP 服务器（仅 FC03/FC16），匹配新协议语义。"""
from __future__ import annotations
import socket, struct, threading, time

from core.utils import float_to_regs_be, regs_to_float_be
from comms.modbus import (
    # 常量与偏移
    CMD_BOOT_OK, CMD_READY_REQ, CMD_SAMPLE_UP, CMD_STOP_ASC, CMD_START_SEG, CMD_FINISH_ALL,
    ST_INIT, ST_READY, ST_SAMPLING, ST_STOPPED, ST_AT_TOP, ST_WAIT_SEG, ST_CLEANING, ST_DONE,
    OFF_VERSION, OFF_CMD, OFF_STATUS, OFF_Z, OFF_ZSIG, OFF_H0, OFF_DH, OFF_N, OFF_DIS, OFF_HEART, TOTAL_REGS
)

HOST, PORT, UNIT_ID = '127.0.0.1', 15020, 1
REG_BASE = 0
Z_MAX_MM = 2500.0
ASCEND_V_MM_S = 80.0
EXEC_SEG_TIME_S = 0.6

REGS = [0] * (REG_BASE + TOTAL_REGS)

def write_int(off: int, val: int):
    REGS[REG_BASE + off] = val & 0xFFFF

def read_int(off: int) -> int:
    r = REGS[REG_BASE + off] & 0xFFFF
    return r-0x10000 if r & 0x8000 else r

def write_dint(off: int, v: int):
    v &= 0xFFFFFFFF
    hi = (v >> 16) & 0xFFFF
    lo = v & 0xFFFF
    REGS[REG_BASE + off + 0] = hi
    REGS[REG_BASE + off + 1] = lo

def read_dint(off: int) -> int:
    hi = REGS[REG_BASE + off + 0]
    lo = REGS[REG_BASE + off + 1]
    v = ((hi & 0xFFFF) << 16) | (lo & 0xFFFF)
    return v-0x100000000 if v & 0x80000000 else v

def write_float(off: int, val: float):
    hi, lo = float_to_regs_be(val)
    REGS[REG_BASE + off + 0] = hi
    REGS[REG_BASE + off + 1] = lo

def read_float(off: int) -> float:
    hi = REGS[REG_BASE + off + 0]
    lo = REGS[REG_BASE + off + 1]
    return regs_to_float_be(hi, lo)

def init_regs():
    write_float(OFF_VERSION, 100.2)
    write_int(OFF_CMD, 0)
    write_int(OFF_STATUS, ST_READY)
    write_float(OFF_Z, 0.0)
    write_dint(OFF_ZSIG, 0)
    for off in (OFF_H0, OFF_DH, OFF_N, OFF_DIS):
        # H0/DH/DIS写float，N写dint，初始化清零
        pass

def logic_tick(dt: float):
    z = read_float(OFF_Z)
    st = read_int(OFF_STATUS)
    if st in (ST_SAMPLING, ST_WAIT_SEG):
        z = min(z + ASCEND_V_MM_S * dt, Z_MAX_MM)
        write_float(OFF_Z, z)
        if z >= Z_MAX_MM:
            write_int(OFF_STATUS, ST_AT_TOP)

def handle_command():
    cmd = read_int(OFF_CMD)
    if cmd == CMD_SAMPLE_UP:
        # 主机已递增Z_SIGNAL；进入采样中
        write_int(OFF_STATUS, ST_SAMPLING)
        write_int(OFF_CMD, 0)
    elif cmd == CMD_STOP_ASC:
        write_int(OFF_STATUS, ST_STOPPED)
        write_int(OFF_CMD, 0)
    elif cmd == CMD_START_SEG:
        # 参数读取
        h0  = read_float(OFF_H0)
        dh  = read_float(OFF_DH)
        n   = read_dint(OFF_N)
        dis = read_float(OFF_DIS)
        # 进入清洗，短暂后回到等待分段
        write_int(OFF_STATUS, ST_CLEANING)
        def do_seg():
            time.sleep(EXEC_SEG_TIME_S)
            write_int(OFF_STATUS, ST_WAIT_SEG)
        threading.Thread(target=do_seg, daemon=True).start()
        write_int(OFF_CMD, 0)
    elif cmd == CMD_FINISH_ALL:
        write_int(OFF_STATUS, ST_DONE)
        write_int(OFF_CMD, 0)

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
                    resp = struct.pack('>B', fcode | 0x80) + b'\x01'
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
