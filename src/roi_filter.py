"""
车辆计数过滤器 — 硬ROI掩膜 + 有向绊线(Tripwire)

核心逻辑:
  1. 硬ROI掩膜: 检测阶段直接丢弃车道外车辆 (bottom_center必须在lane_mask内)
  2. 绊线计数: 接地点向量穿越绊线 → 计数+1
  3. 不依赖长历史: 只需绊线前后的短帧, 抗ID切换

绊线方向约定:
  所有摄像头: 远处→近处 (y增大), 穿越方向向下
"""

import numpy as np
import cv2


class ROIFilter:
    def __init__(self, approach_lane_norm, direction_range,
                 ignore_region_norm=None, img_width=1920, img_height=1080,
                 wrong_way_tolerance=50):
        self.img_w = img_width
        self.img_h = img_height

        # 车道掩膜 (硬ROI, 检测的bottom_center必须在此多边形内)
        self.lane_mask = self._to_pixel(approach_lane_norm)

        # 兼容旧配置
        self.dir_min, self.dir_max = direction_range
        if self.dir_max <= self.dir_min:
            self.dir_max += 360

        self.ignore_region = None
        if ignore_region_norm:
            self.ignore_region = self._to_pixel(ignore_region_norm)

        # 绊线: (p1, p2, direction) — direction=True表示上→下穿越有效
        self.tripwire_a = None  # 进入线
        self.tripwire_b = None  # 计数线
        self.tripwire_direction = "down"  # "down" = y增大方向穿越

        # 排除区
        self.exclusion_zones = []

        # 统计
        self.passed_vehicles = {}
        self.total_count = 0
        self._track_prev_pos = {}     # {tid: (x, y)} 上一帧位置
        self._track_crossed_a = {}    # {tid: bool} 已穿过A线
        self._recent_positions = []
        self._frame_idx = 0

    def _to_pixel(self, norm_data):
        coords = []
        for i in range(0, len(norm_data), 2):
            coords.append((int(norm_data[i] * self.img_w),
                           int(norm_data[i + 1] * self.img_h)))
        return np.array(coords, np.int32)

    def _in_poly(self, point, polygon):
        return cv2.pointPolygonTest(polygon, point, False) >= 0

    # === 配置方法 ===
    def _build_wire_segments(self, norm_points):
        """将归一化折线点列表转为像素坐标的线段列表 [(p0,p1),(p1,p2),...]"""
        pts = []
        for i in range(0, len(norm_points), 2):
            pts.append((norm_points[i] * self.img_w,
                       norm_points[i + 1] * self.img_h))
        if len(pts) < 2:
            return None
        segments = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        return segments

    def set_tripwire_a(self, *norm_points):
        """进入检测线: 支持多段折线 polyline, 参数为平铺归一化坐标 [x1,y1,x2,y2,...]"""
        self.tripwire_a = self._build_wire_segments(norm_points)

    def set_tripwire_b(self, *norm_points):
        """计数线: 支持多段折线 polyline"""
        self.tripwire_b = self._build_wire_segments(norm_points)

    def add_exclusion_zone(self, poly_norm, name=""):
        self.exclusion_zones.append((self._to_pixel(poly_norm), name))

    def cleanup_stale(self, active_tids):
        """清理已死亡track的记录, 防止内存泄漏"""
        stale = [tid for tid in self._track_prev_pos if tid not in active_tids]
        for tid in stale:
            self._track_prev_pos.pop(tid, None)
            self._track_crossed_a.pop(tid, None)
        # 也清理过期去重记录
        if len(self._recent_positions) > 500:
            self._recent_positions = self._recent_positions[-200:]

    def set_lane_mask(self, poly_norm):
        self.lane_mask = self._to_pixel(poly_norm)

    # === 向量叉乘相交检测 ===
    def _segments_intersect(self, p1, p2, p3, p4):
        """判断线段p1-p2与p3-p4是否相交 (包含端点)"""
        def ccw(a, b, c):
            return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])
        return (ccw(p1, p3, p4) != ccw(p2, p3, p4) and
                ccw(p1, p2, p3) != ccw(p1, p2, p4))

    def _cross_direction_ok(self, p_prev, p_curr, line_p1, line_p2):
        """
        检查穿越方向是否正确 (向下穿越)
        line从左到右, 计算车辆轨迹在法向量方向的分量
        """
        # 绊线法向量 (指向下方, 即y增大方向)
        line_dx = line_p2[0] - line_p1[0]
        line_dy = line_p2[1] - line_p1[1]
        # 法向量 (右手法则 → 指向y正方向即下方)
        nx = -line_dy
        ny = line_dx
        # 车辆位移
        dx = p_curr[0] - p_prev[0]
        dy = p_curr[1] - p_prev[1]
        # 点积: 车辆位移在法向量上的投影
        dot = dx * nx + dy * ny
        return dot > 0  # 正=向下穿越

    # === 硬ROI掩膜 ===
    def is_inside_lane(self, bottom_center):
        """检测的bottom_center是否在车道掩膜内"""
        return self._in_poly(bottom_center, self.lane_mask)

    def is_in_exclusion(self, bottom_center):
        """是否在排除区内"""
        for zone, _ in self.exclusion_zones:
            if self._in_poly(bottom_center, zone):
                return True
        return False

    def _is_dup(self, bottom_center, cls_name, frame_idx):
        """空间-时间去重"""
        bx, by = bottom_center
        cutoff = frame_idx - 25 * 10
        self._recent_positions = [p for p in self._recent_positions if p[3] > cutoff]
        for px, py, cls, fnum in self._recent_positions:
            if ((bx - px) ** 2 + (by - py) ** 2) < 6400 \
               and cls == cls_name and abs(frame_idx - fnum) < 30:
                return True
        return False

    # ================================================================
    #  主逻辑: 硬ROI + 双绊线
    # ================================================================
    def filter_detections(self, detections):
        """第一步: 硬ROI掩膜过滤检测"""
        filtered = []
        for det in detections:
            bc = det["bottom_center"]
            if self.is_inside_lane(bc) and not self.is_in_exclusion(bc):
                filtered.append(det)
        return filtered

    def update(self, tracks, frame_shape=None):
        """第二步: 绊线穿越检测"""
        if frame_shape:
            self.img_h, self.img_w = frame_shape[:2]

        newly_passed = []
        frame_idx = self._frame_idx

        for track in tracks:
            tid = track["track_id"]
            # 使用bottom_center (接地点) 进行绊线检测
            bc = track.get("bottom_center", track.get("center"))
            bx, by = bc

            if tid in self.passed_vehicles:
                continue

            # 获取前一帧位置
            prev_pos = self._track_prev_pos.get(tid)
            self._track_prev_pos[tid] = bc

            if prev_pos is None:
                continue

            # 去重检查
            if self._is_dup(bc, track["cls_name"], frame_idx):
                continue

            crossed = False

            # 双绊线模式: A→B (折线多段检测)
            if self.tripwire_a and self.tripwire_b:
                # 检查是否穿过A线 (遍历所有折线段)
                if not self._track_crossed_a.get(tid, False):
                    for pa1, pa2 in self.tripwire_a:
                        if self._segments_intersect(prev_pos, bc, pa1, pa2):
                            if self._cross_direction_ok(prev_pos, bc, pa1, pa2):
                                self._track_crossed_a[tid] = True
                                break
                            else:
                                self._track_crossed_a[tid] = False

                # 已穿过A线后, 检查是否穿过B线 (遍历所有折线段)
                if self._track_crossed_a.get(tid, False):
                    for pb1, pb2 in self.tripwire_b:
                        if self._segments_intersect(prev_pos, bc, pb1, pb2):
                            if self._cross_direction_ok(prev_pos, bc, pb1, pb2):
                                crossed = True
                                break

            # 单绊线模式 (折线多段)
            elif self.tripwire_b:
                for pb1, pb2 in self.tripwire_b:
                    if self._segments_intersect(prev_pos, bc, pb1, pb2):
                        if self._cross_direction_ok(prev_pos, bc, pb1, pb2):
                            crossed = True
                            break

            if crossed:
                # 计算轨迹整体方向
                history = track.get("history", [])
                pts = list(history) if history else [bc]
                angle = 90  # 默认向下
                if len(pts) >= 2:
                    dx = pts[-1][0] - pts[0][0]
                    dy = pts[-1][1] - pts[0][1]
                    if abs(dx) + abs(dy) > 1:
                        angle = round(np.degrees(np.arctan2(dy, dx)), 1)

                passed = {
                    "track_id": tid,
                    "cls_name": track["cls_name"],
                    "cls": track["cls"],
                    "angle": angle,
                    "is_turning": False,
                    "pass_point": bc,
                    "pass_frame": frame_idx,
                }
                self.passed_vehicles[tid] = passed
                newly_passed.append(passed)
                self.total_count += 1
                self._recent_positions.append((bx, by, track["cls_name"], frame_idx))

        return newly_passed, {
            "total_passed": self.total_count,
            "newly_passed": len(newly_passed),
        }

    def draw_roi(self, frame, color=(0, 255, 0), thickness=2):
        """可视化: 车道掩膜 + 绊线"""
        display = frame.copy()

        # 车道掩膜
        if self.lane_mask is not None:
            cv2.polylines(display, [self.lane_mask], True, (0, 255, 0), 2)

        # 绊线A (进入线, 黄色多段折线)
        if self.tripwire_a:
            for pa1, pa2 in self.tripwire_a:
                cv2.line(display, (int(pa1[0]), int(pa1[1])),
                         (int(pa2[0]), int(pa2[1])), (0, 255, 255), 2)
                cv2.circle(display, (int(pa1[0]), int(pa1[1])), 4, (0, 200, 200), -1)
            # 末端点
            last = self.tripwire_a[-1][1]
            cv2.circle(display, (int(last[0]), int(last[1])), 4, (0, 200, 200), -1)
            first = self.tripwire_a[0][0]
            cv2.putText(display, "ENTRY A", (int(first[0]), int(first[1]) - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        # 绊线B (计数线, 红色多段折线)
        if self.tripwire_b:
            for pb1, pb2 in self.tripwire_b:
                cv2.line(display, (int(pb1[0]), int(pb1[1])),
                         (int(pb2[0]), int(pb2[1])), (0, 0, 255), 2)
                cv2.circle(display, (int(pb1[0]), int(pb1[1])), 4, (0, 0, 200), -1)
            last = self.tripwire_b[-1][1]
            cv2.circle(display, (int(last[0]), int(last[1])), 4, (0, 0, 200), -1)
            first = self.tripwire_b[0][0]
            cv2.putText(display, "COUNT B", (int(first[0]), int(first[1]) - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        # 排除区
        for zone, name in self.exclusion_zones:
            cv2.polylines(display, [zone], True, (0, 0, 255), 1)

        return display

    def reset(self):
        self.passed_vehicles = {}
        self.total_count = 0
        self._track_prev_pos.clear()
        self._track_crossed_a.clear()
        self._recent_positions.clear()
