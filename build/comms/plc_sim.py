# -*- coding: utf-8 -*-
"""最小可用的 Modbus TCP 服务器（仅 FC03/FC16）。用于联调。"""
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
