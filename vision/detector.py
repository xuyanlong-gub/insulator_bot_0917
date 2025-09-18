"""
检测模块：封装对 YOLOv8 模型的加载与推理。

由于运行环境中可能没有现成的深度学习库，本文件提供两种使用方式：

1. 如果环境中安装了 PyTorch 和 Ultralytics，则可以在 ``Detector`` 中使用
   ``ultralytics.YOLO`` 类加载已训练好的权重进行推理。

2. 如果未安装上述库，但具有 ONNX 权重文件，可以使用 OpenCV 的 ``dnn``
   接口加载 ONNX 模型并进行推理。由于不同模型的输入大小和输出格式各异，
   需要根据实际模型进行相应修改。本示例提供了读取 ONNX 并输出兼容
   ``judge_center_band`` 函数所需的数据结构的框架，具体实现需根据模型结构调整。

3. 如果既无法加载模型，也仅需离线回放功能，可使用 ``DummyDetector``
   返回空列表，该情况下中心带判定将始终输出 ``flag=0``，便于调试后处理逻辑。

输出格式：``detect()`` 方法返回一个列表，每个元素形如
``[x1, y1, x2, y2, class_id, confidence]``，其中坐标为浮点数或整数，
``class_id`` 为整数类别索引，confidence 为置信度分数。

类别定义请参考需求文档：

- 0：顶端
- 1：绝缘子片体
- 2：法兰
- 3：底座
"""

# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from typing import List, Tuple

import numpy as np

try:
    # 如果 ulralytics 和 torch 可用，尝试导入
    from ultralytics import YOLO  # type: ignore
    _ULTRALYTICS_AVAILABLE = True
except Exception:
    _ULTRALYTICS_AVAILABLE = False

import cv2  # OpenCV 用于 ONNX 推理或基础图像处理


class Detector:
    """
    YOLOv8 检测封装类。

    根据所提供的权重文件和环境情况选择使用 Ultralytics、OpenCV dnn 或 Dummy 模式。
    """

    def __init__(self, weight_path: str | None = None, device: str = "cpu"):
        """初始化检测器。

        :param weight_path: 模型权重路径，可为 yolov8.pt 或 onnx 文件。若为 ``None``，则启用 Dummy 模式。
        :param device: 计算设备（如 ``cpu`` 或 ``cuda``）。Ultralytics 模式下有效。
        """
        self.weight_path = weight_path
        self.device = device
        self.model = None
        self.use_ultralytics = False
        self.use_onnx = False
        if weight_path and _ULTRALYTICS_AVAILABLE and weight_path.endswith(('.pt', '.pth')):
            try:
                logging.info("使用 Ultralytics 加载模型：%s", weight_path)
                self.model = YOLO(weight_path)
                self.use_ultralytics = True
            except Exception as e:
                logging.warning("加载 Ultralytics 模型失败：%s", e)
        if weight_path and not self.use_ultralytics and weight_path.endswith('.onnx'):
            # 尝试使用 OpenCV dnn 加载 ONNX
            try:
                logging.info("使用 OpenCV DNN 加载 ONNX：%s", weight_path)
                self.model = cv2.dnn.readNetFromONNX(weight_path)
                self.use_onnx = True
            except Exception as e:
                logging.warning("加载 ONNX 模型失败：%s", e)
        if self.model is None:
            logging.warning("未提供有效权重或无法加载模型，启用 Dummy 检测器。")

    def detect(self, frame: np.ndarray) -> List[List[float]]:
        """对单帧图像进行目标检测。

        :param frame: BGR 格式图像数组。
        :return: 检测结果列表，每个元素为 [x1, y1, x2, y2, class_id, confidence]。
        """
        if self.use_ultralytics and self.model:
            # 使用 Ultralytics 推理，自动完成预处理
            # results = self.model(frame)[0]
            # 优先使用 predict 并显式关闭 verbose
            results = self.model.predict(frame, verbose=False, device=self.device)[0]
            # 如果你更喜欢 __call__ 语法，也必须传 verbose=False：
            # results = self.model(frame, verbose=False)[0]

            boxes = []
            for cls_id, conf, xyxy in zip(results.boxes.cls.tolist(),
                                          results.boxes.conf.tolist(),
                                          results.boxes.xyxy.tolist()):
                x1, y1, x2, y2 = xyxy
                boxes.append([x1, y1, x2, y2, int(cls_id), float(conf)])
            return boxes
        elif self.use_onnx and self.model:
            # 使用 ONNX 模型推理
            # 注：需根据实际模型的输入尺寸和输出格式调整以下代码
            blob = cv2.dnn.blobFromImage(frame, 1/255.0, (640, 480), swapRB=True, crop=False)
            self.model.setInput(blob)
            try:
                outputs = self.model.forward()  # 假设模型只有一个输出
            except Exception as e:
                logging.error("ONNX 推理失败：%s", e)
                return []
            # 解析输出，需要根据模型修改
            detections: List[List[float]] = []
            # 示意性地假定输出形状为 (N, 85): [cx, cy, w, h, conf, class_scores...]
            if len(outputs.shape) == 3:
                outputs = outputs[0]
            for det in outputs:
                if len(det) < 6:
                    continue
                cx, cy, w, h, obj_conf, *class_confs = det
                confs = np.array(class_confs) * obj_conf
                class_id = int(np.argmax(confs))
                confidence = float(confs[class_id])
                # 筛除置信度极低的目标
                if confidence < 0.01:
                    continue
                x1 = float((cx - w / 2) * frame.shape[1] / 640)
                y1 = float((cy - h / 2) * frame.shape[0] / 480)
                x2 = float((cx + w / 2) * frame.shape[1] / 640)
                y2 = float((cy + h / 2) * frame.shape[0] / 480)
                detections.append([x1, y1, x2, y2, class_id, confidence])
            return detections
        else:
            # Dummy 模式：返回空列表
            return []


class DummyDetector(Detector):
    """
    一个始终返回空检测结果的示例检测器，用于离线回放或开发阶段。
    """
    def __init__(self):
        super().__init__(weight_path=None)

    def detect(self, frame: np.ndarray) -> List[List[float]]:  # type: ignore[override]
        return []


__all__ = ["Detector", "DummyDetector"]