# -*- coding: utf-8 -*-
import threading, time, queue, logging
from typing import Optional, Tuple
import cv2
import numpy as np

class Latest:
    """线程安全的“最新值容器”"""
    def __init__(self): self._v=None; self._seq=0; self._lock=threading.Lock()
    def set(self, v):
        with self._lock: self._v=v; self._seq+=1
    def get(self, last_seq:int=-1) -> Tuple[int, Optional[object]]:
        with self._lock:
            return self._seq, self._v if self._seq!=last_seq else None

def frame_grabber(stop_evt, src, frame_q:queue.Queue, size=(640,480), fps_cap:float=0):
    cap = cv2.VideoCapture(src);
    if not cap.isOpened():
        logging.error("无法打开视频源: %s", src); return
    tick = 1.0/fps_cap if fps_cap>0 else 0
    try:
        while not stop_evt.is_set():
            ret, frame = cap.read()
            if not ret: break
            if size: frame = cv2.resize(frame, size)
            # 丢旧保新：队列满则尝试丢弃一个旧帧
            try: frame_q.put(frame, timeout=0.01)
            except queue.Full:
                try: frame_q.get_nowait()
                except queue.Empty: pass
                frame_q.put(frame)
            if tick: time.sleep(tick)
    finally:
        cap.release()

def yolo_worker(stop_evt, frame_q:queue.Queue, det_latest:Latest, detector, conf_thr, center_band_px):
    from vision.detector import Detector
    from vision.center_band1 import judge_center_band
    while not stop_evt.is_set():
        try: frame = frame_q.get(timeout=0.1)
        except queue.Empty: continue
        dets = Detector.detect(detector, frame)
        flag_frame, cls_ins = judge_center_band(dets, conf_thr, frame.shape[0], center_band_px)
        det_latest.set((flag_frame, cls_ins))  # 仅存“最新”的结果

def distance_worker(stop_evt, provider, dis_latest:Latest, period_s:float=0.02):
    # 真实双目线程：阻塞或轮询均可；拿到“新距离”就 set
    while not stop_evt.is_set():
        v = provider.read_once_blocking_or_poll()  # 你在 DistanceProvider 中实现
        if v is not None: dis_latest.set(float(v))
        time.sleep(period_s)

def modbus_heartbeat_worker(stop_evt, mod, reg_base:int, period_s:float=0.7):
    hb=0
    while not stop_evt.is_set():
        hb=(hb+1)&0xFFFF
        try: mod.write_heartbeat(reg_base, hb)
        except Exception as e: logging.warning("heartbeat error: %s", e)
        stop_evt.wait(period_s)

def csv_writer_worker(stop_evt, row_q:queue.Queue, csv_path:str):
    import csv, os
    f = open(csv_path, "a", newline="", encoding="utf-8")
    w = csv.writer(f)
    try:
        while not stop_evt.is_set():
            try: row = row_q.get(timeout=0.1)
            except queue.Empty: continue
            w.writerow(row); f.flush()
    finally:
        f.close()
