"""可视化模块 — 检测效果渲染、统计图表"""
import cv2
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import os

# 车辆类型颜色映射
VEHICLE_COLORS = {
    "car": (0, 255, 0),        # 绿色
    "motorcycle": (255, 255, 0),  # 青色
    "bus": (255, 0, 0),        # 蓝色
    "truck": (0, 165, 255),    # 橙色
}


class Visualizer:
    """检测效果可视化"""

    def __init__(self, show_direction=True, show_roi=True, show_stats=True,
                 output_dir="output"):
        self.show_direction = show_direction
        self.show_roi = show_roi
        self.show_stats = show_stats
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def draw_detections(self, frame, tracks, roi_filter=None, fps=0):
        """
        在画面上绘制检测框、ID、轨迹、ROI和统计信息
        """
        display = frame.copy()

        # 绘制ROI
        if self.show_roi and roi_filter:
            display = roi_filter.draw_roi(display)

        # 绘制检测框和轨迹
        for track in tracks:
            tid = track["track_id"]
            x1, y1, x2, y2 = track["bbox"]
            cls_name = track["cls_name"]
            color = VEHICLE_COLORS.get(cls_name, (255, 255, 255))

            # 检测框
            cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)

            # 标签
            label = f"#{tid} {cls_name}"
            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)[0]
            cv2.rectangle(display, (x1, y1 - label_size[1] - 8),
                          (x1 + label_size[0] + 4, y1), color, -1)
            cv2.putText(display, label, (x1 + 2, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

            # 轨迹线 (bottom_center历史)
            if self.show_direction:
                history = track.get("history", [])
                if len(history) >= 2:
                    pts = np.array(history, np.int32).reshape((-1, 1, 2))
                    cv2.polylines(display, [pts], False, color, 1)

            # 接地点标记 (bottom_center)
            bc = track.get("bottom_center")
            if bc is not None:
                cv2.circle(display, (int(bc[0]), int(bc[1])), 3, (0, 255, 255), -1)

        # 统计信息叠加
        if self.show_stats and roi_filter:
            self._draw_stats_overlay(display, roi_filter, fps)

        return display

    def _draw_stats_overlay(self, frame, roi_filter, fps):
        """在画面左上角绘制统计信息"""
        h, w = frame.shape[:2]
        overlay = frame.copy()
        cv2.rectangle(overlay, (8, 8), (260, 100), (0, 0, 0), -1)
        frame[:] = cv2.addWeighted(frame, 0.6, overlay, 0.4, 0)

        y = 30
        track_dict = getattr(roi_filter, '_track_crossed_a', {})
        crossed_a = sum(1 for v in track_dict.values() if v)
        texts = [
            f"FPS: {fps:.1f}",
            f"Counted: {roi_filter.total_count}",
            f"In lane: {crossed_a}",
        ]
        for text in texts:
            cv2.putText(frame, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, (255, 255, 255), 1)
            y += 24

    def generate_charts(self, stats_dict, data_processor):
        """生成统计图表"""
        charts = {}

        # 1. 流量时序图
        fig, ax = plt.subplots(figsize=(12, 4))
        for cam_name, stats in stats_dict.items():
            if stats.flow_per_minute:
                minutes = list(range(len(stats.flow_per_minute)))
                ax.plot(minutes, stats.flow_per_minute, label=cam_name, linewidth=1.5)
        ax.set_xlabel("Time (min)")
        ax.set_ylabel("Vehicles")
        ax.set_title("Traffic Flow Over Time")
        ax.legend()
        ax.grid(True, alpha=0.3)
        path = os.path.join(self.output_dir, "flow_timeline.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        charts["flow_timeline"] = path

        # 2. 车型分布饼图
        n = len(stats_dict)
        fig, axes = plt.subplots(1, n, figsize=(5 * n, 5))
        if n == 1:
            axes = [axes]
        else:
            axes = axes.flatten()
        for idx, (cam_name, stats) in enumerate(stats_dict.items()):
            ax = axes[idx]
            types = stats.vehicles_by_type
            if types:
                labels = list(types.keys())
                sizes = list(types.values())
                colors = ['#4CAF50', '#FFC107', '#2196F3', '#FF9800']
                ax.pie(sizes, labels=labels, colors=colors[:len(labels)],
                       autopct='%1.1f%%', startangle=90)
            ax.set_title(f"{cam_name} - Vehicle Types")
        fig.suptitle("Vehicle Type Distribution", fontsize=14)
        fig.tight_layout()
        path = os.path.join(self.output_dir, "vehicle_types.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        charts["vehicle_types"] = path

        # 3. 汇总柱状图
        fig, ax = plt.subplots(figsize=(10, 5))
        cameras = list(stats_dict.keys())
        totals = [s.total_vehicles for s in stats_dict.values()]
        bars = ax.bar(cameras, totals, color=['#4CAF50', '#2196F3', '#FF9800'])
        ax.set_ylabel("Total Vehicles")
        ax.set_title("Total Count by Approach")
        for bar, val in zip(bars, totals):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                    str(val), ha='center', va='bottom', fontweight='bold')
        path = os.path.join(self.output_dir, "total_count.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        charts["total_count"] = path

        return charts

    def create_comparison_video(self, original_frame, processed_frame):
        """并排拼接原画面和处理后画面"""
        return np.hstack([original_frame, processed_frame])
