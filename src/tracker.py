"""ByteTrack跟踪器 — 二次匹配 + Kalman预测, 抗遮挡"""
import numpy as np
from collections import deque
from scipy.optimize import linear_sum_assignment


class KalmanBox:
    """Kalman滤波器: 状态[x,y,w,h,dx,dy] 预测+平滑"""

    def __init__(self, bbox):
        x1, y1, x2, y2 = bbox
        w, h = x2 - x1, y2 - y1
        self.state = np.array([x1, y1, w, h, 0.0, 0.0], dtype=np.float32)
        self.P = np.eye(6) * 100.0
        self.Q = np.diag([1.0, 1.0, 1.0, 1.0, 10.0, 10.0])
        self.R = np.diag([10.0, 10.0, 5.0, 5.0])
        self.H = np.zeros((4, 6))
        self.H[0, 0] = self.H[1, 1] = self.H[2, 2] = self.H[3, 3] = 1.0
        self.initialized = False

    def predict(self):
        """状态预测: 用于匹配时估计当前帧位置"""
        dt = 1.0
        F = np.eye(6)
        F[0, 4] = dt
        F[1, 5] = dt
        self.state = F @ self.state
        self.P = F @ self.P @ F.T + self.Q
        x, y, w, h = self.state[:4]
        return (int(x), int(y), int(x + w), int(y + h))

    def update(self, bbox):
        """Kalman更新: 观测融合"""
        z = np.array([bbox[0], bbox[1],
                      bbox[2] - bbox[0], bbox[3] - bbox[1]], dtype=np.float32)

        if not self.initialized:
            self.state[:4] = z
            self.initialized = True
            return bbox

        self.predict()
        y = z - self.H @ self.state
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.state = self.state + K @ y
        self.P = (np.eye(6) - K @ self.H) @ self.P

        x, y_p, w, h = self.state[:4]
        return (int(x), int(y_p), int(x + w), int(y_p + h))


class Tracklet:
    """车辆追踪片断"""
    __slots__ = ('id', 'cls', 'cls_name', 'conf', 'bbox', 'center',
                 'bottom_center', 'history', 'hits', 'age', 'lost', 'kalman',
                 'predicted_bbox')
    _next_id = 1

    def __init__(self, bbox, cls_id, cls_name, conf, bottom_center=None):
        self.id = Tracklet._next_id
        Tracklet._next_id += 1
        self.cls = cls_id
        self.cls_name = cls_name
        self.conf = conf
        self.kalman = KalmanBox(bbox)
        self.bbox = bbox
        x1, y1, x2, y2 = bbox
        self.center = ((x1 + x2) / 2, (y1 + y2) / 2)
        self.bottom_center = bottom_center or ((x1 + x2) / 2, y2)
        self.predicted_bbox = bbox
        self.history = deque(maxlen=60)
        self.history.append(self.bottom_center)
        self.hits = 1
        self.age = 0
        self.lost = 0


class ByteTracker:
    """
    ByteTrack: 二次匹配策略
    核心: 低置信度检测框(0.1~0.3)用于拯救被遮挡轨迹

    匹配流程:
      Stage1: 高置信度(>=high_thresh)检测 → 所有轨迹 (匈牙利全局最优)
      Stage2: 低置信度(<high_thresh)检测  → Stage1未匹配的轨迹 (严格IoU)
      低置信匹配: 更新位置但不重置lost计数
    """

    def __init__(self, track_lost_buffer=70, high_thresh=0.35,
                 match_thresh=0.25, low_match_thresh=0.45, min_hits=2):
        self.track_lost_buffer = track_lost_buffer
        self.high_thresh = high_thresh
        self.match_thresh = match_thresh      # Stage1 IoU阈值
        self.low_match_thresh = low_match_thresh  # Stage2 IoU阈值(更严格)
        self.min_hits = min_hits
        self.active_tracks = {}
        self.frame_count = 0

    def update(self, detections):
        self.frame_count += 1

        # 老化所有轨迹, 预测当前位置
        for t in self.active_tracks.values():
            t.age += 1
            t.lost += 1

        for track in self.active_tracks.values():
            track.predicted_bbox = track.kalman.predict()

        if len(detections) == 0:
            # 无检测: 只清理过期轨迹
            return self._purge_and_collect()

        # 分离高/低置信度检测
        dets_high = []   # (idx, det)
        dets_low = []    # (idx, det)
        for i, det in enumerate(detections):
            if det["conf"] >= self.high_thresh:
                dets_high.append((i, det))
            else:
                dets_low.append((i, det))

        # ── Stage 1: 高置信检测 vs 所有轨迹 (匈牙利) ──
        matched_tids = set()
        matched_dets = set()

        if dets_high and self.active_tracks:
            tid_list = list(self.active_tracks.keys())
            cost = np.zeros((len(tid_list), len(dets_high)))
            for ti, tid in enumerate(tid_list):
                track = self.active_tracks[tid]
                for di, (_, det) in enumerate(dets_high):
                    iou = self._iou(track.predicted_bbox, det["bbox"])
                    cost[ti, di] = 1.0 - iou if iou > 0 else 1.0

            row_ind, col_ind = linear_sum_assignment(cost)

            for ti, di in zip(row_ind, col_ind):
                iou = 1.0 - cost[ti, di]
                if iou >= self.match_thresh:
                    tid = tid_list[ti]
                    _, det = dets_high[di]
                    self._apply_detection(tid, det, is_high_conf=True)
                    matched_tids.add(tid)
                    matched_dets.add(di)

        # ── Stage 2: 低置信检测 vs 剩余未匹配轨迹 ──
        if dets_low and self.active_tracks:
            remaining_tids = [tid for tid in self.active_tracks
                              if tid not in matched_tids]
            if remaining_tids:
                cost2 = np.zeros((len(remaining_tids), len(dets_low)))
                for ti, tid in enumerate(remaining_tids):
                    track = self.active_tracks[tid]
                    for di, (_, det) in enumerate(dets_low):
                        iou = self._iou(track.predicted_bbox, det["bbox"])
                        cost2[ti, di] = 1.0 - iou if iou > 0 else 1.0

                row_ind2, col_ind2 = linear_sum_assignment(cost2)

                for ti, di in zip(row_ind2, col_ind2):
                    iou = 1.0 - cost2[ti, di]
                    if iou >= self.low_match_thresh:
                        tid = remaining_tids[ti]
                        _, det = dets_low[di]
                        # 低置信匹配: 更新位置但不重置lost
                        self._apply_detection(tid, det, is_high_conf=False)
                        matched_tids.add(tid)
                        matched_dets.add(di)  # 标记已用(虽不用建新track)

        # ── 未匹配的高置信检测 → 新建轨迹 ──
        for di, (_, det) in enumerate(dets_high):
            if di not in matched_dets:
                new_t = Tracklet(det["bbox"], det["cls"],
                                 det["cls_name"], det["conf"],
                                 det.get("bottom_center"))
                self.active_tracks[new_t.id] = new_t

        return self._purge_and_collect()

    def _apply_detection(self, tid, det, is_high_conf):
        """将检测应用到轨迹"""
        track = self.active_tracks[tid]
        smooth_bbox = track.kalman.update(det["bbox"])
        track.bbox = smooth_bbox
        x1, y1, x2, y2 = smooth_bbox
        track.center = ((x1 + x2) / 2, (y1 + y2) / 2)
        bc = det.get("bottom_center")
        if bc is None:
            bc = ((x1 + x2) / 2, y2)
        track.bottom_center = bc
        track.history.append(track.bottom_center)
        track.conf = det["conf"]
        track.hits += 1
        if is_high_conf:
            track.lost = 0  # 高置信重置丢失计数

    def _purge_and_collect(self):
        """清理死轨迹, 收集活跃轨迹输出"""
        dead = []
        for tid, track in self.active_tracks.items():
            if track.lost > self.track_lost_buffer:
                dead.append(tid)

        for tid in dead:
            del self.active_tracks[tid]

        results = []
        for track in self.active_tracks.values():
            if track.hits >= self.min_hits and track.lost == 0:
                results.append({
                    "track_id": track.id,
                    "bbox": track.bbox,
                    "cls": track.cls,
                    "cls_name": track.cls_name,
                    "conf": track.conf,
                    "center": track.center,
                    "bottom_center": track.bottom_center,
                    "history": list(track.history),
                })

        return results

    def _iou(self, box1, box2):
        x1, y1 = max(box1[0], box2[0]), max(box1[1], box2[1])
        x2, y2 = min(box1[2], box2[2]), min(box1[3], box2[3])
        iw, ih = x2 - x1, y2 - y1
        if iw <= 0 or ih <= 0:
            return 0.0
        inter = iw * ih
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        return inter / (area1 + area2 - inter)
