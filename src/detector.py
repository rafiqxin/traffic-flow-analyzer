"""车辆检测模块 — GPU批量推理 + CPU预取流水线"""
import numpy as np
import cv2
import queue
from threading import Thread
from ultralytics import YOLO


class FramePrefetcher:
    """后台线程预读+缩放帧, CPU/GPU并行, 消除GPU空闲等待"""

    def __init__(self, video_path, resize_w, resize_h, sample_interval,
                 batch_size, max_queue=24):
        self.cap = cv2.VideoCapture(video_path)
        self.resize_w = resize_w
        self.resize_h = resize_h
        self.sample_interval = sample_interval
        self.batch_size = batch_size
        self.queue = queue.Queue(maxsize=max_queue)
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self._done = False
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        idx = 0
        try:
            while True:
                ret, frame = self.cap.read()
                if not ret:
                    break
                idx += 1
                if idx % self.sample_interval != 0 and idx > 1:
                    continue
                frame = cv2.resize(frame, (self.resize_w, self.resize_h))
                self.queue.put((frame, idx))
        finally:
            self.queue.put((None, -1))

    def get_batch(self):
        """取一批预处理好帧, 返回([frames], [indices])"""
        if self._done:
            return [], []
        batch, indices = [], []
        for _ in range(self.batch_size):
            frame, idx = self.queue.get()
            if frame is None:
                self._done = True
                break
            batch.append(frame)
            indices.append(idx)
        return batch, indices

    def close(self):
        self.cap.release()


class VehicleDetector:
    """YOLO检测器 — 批量GPU推理, bottom-center锚点"""

    VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

    def __init__(self, model_name="yolo11l.pt", confidence=0.25, iou=0.65,
                 device="cuda:0", batch_size=8):
        self.model = YOLO(model_name)
        self.confidence = confidence
        self.iou = iou
        self.device = device
        self.batch_size = batch_size

    def detect_batch(self, frames):
        """批量GPU推理, 返回检测列表 (含bottom_center)"""
        if not frames:
            return []

        results = self.model(
            frames,
            conf=self.confidence,
            iou=self.iou,
            classes=list(self.VEHICLE_CLASSES.keys()),
            device=self.device,
            stream=False,
            verbose=False,
        )

        all_detections = []
        for result in results:
            dets = []
            if result.boxes is not None:
                boxes = result.boxes
                for i in range(len(boxes)):
                    x1, y1, x2, y2 = boxes.xyxy[i].cpu().numpy()
                    cls = int(boxes.cls[i].cpu().numpy())
                    conf = float(boxes.conf[i].cpu().numpy())
                    # Bottom-center anchor: 轮胎接地点, 透视最稳定
                    bcx = (x1 + x2) / 2
                    bcy = y2
                    dets.append({
                        "bbox": (int(x1), int(y1), int(x2), int(y2)),
                        "bottom_center": (bcx, bcy),
                        "center": ((x1 + x2) / 2, (y1 + y2) / 2),
                        "cls": cls,
                        "cls_name": self.VEHICLE_CLASSES.get(cls, "unknown"),
                        "conf": conf,
                    })
            all_detections.append(dets)

        return all_detections
