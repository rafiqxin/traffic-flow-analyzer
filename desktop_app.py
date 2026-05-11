"""
交通流检测 — 桌面版 (PyQt6)
用法: python desktop_app.py
"""
import sys
import os
import threading
import queue
import tempfile
from pathlib import Path

import cv2
import numpy as np

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QComboBox, QSlider, QSpinBox,
    QGroupBox, QProgressBar, QTabWidget, QTableWidget, QTableWidgetItem,
    QSplitter, QMessageBox, QRadioButton, QHeaderView,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QFont, QAction

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import PipelineRunner

MODELS = ["yolo11n.pt", "yolo11s.pt", "yolo11m.pt", "yolo11l.pt", "yolo11x.pt"]


class CalibCanvas(QLabel):
    mode_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(640, 360)
        self.setStyleSheet("background:#1a1a1a; border:1px solid #333;")
        self.setText("请先提取标定帧")
        self._frame = None
        self._display = None
        self.lane_pts = []
        self.wire_a_pts = []
        self.wire_b_pts = []
        self.lane_closed = False
        self.mode = "A"
        self.setMouseTracking(True)

    def set_frame(self, img_bgr):
        self._frame = img_bgr.copy()
        self._display = img_bgr.copy()
        self.lane_pts.clear()
        self.wire_a_pts.clear()
        self.wire_b_pts.clear()
        self.lane_closed = False
        self._redraw()

    def _redraw(self):
        if self._frame is None:
            return
        img = self._frame.copy()
        for i, p in enumerate(self.lane_pts):
            cv2.circle(img, p, 5, (0, 255, 0), -1)
            if i > 0:
                cv2.line(img, self.lane_pts[i - 1], p, (0, 255, 255), 2)
        if self.lane_closed and len(self.lane_pts) >= 3:
            pts = np.array(self.lane_pts, np.int32).reshape((-1, 1, 2))
            overlay = img.copy()
            cv2.fillPoly(overlay, [pts], (0, 255, 0))
            img = cv2.addWeighted(img, 0.7, overlay, 0.3, 0)
            cv2.polylines(img, [pts], True, (0, 255, 0), 2)
        for i, p in enumerate(self.wire_a_pts):
            cv2.circle(img, p, 6, (0, 255, 255), -1)
            if i > 0:
                cv2.line(img, self.wire_a_pts[i - 1], p, (0, 255, 255), 2)
        for i, p in enumerate(self.wire_b_pts):
            cv2.circle(img, p, 6, (0, 0, 255), -1)
            if i > 0:
                cv2.line(img, self.wire_b_pts[i - 1], p, (0, 0, 255), 2)

        self._display = img
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg)
        scaled = pix.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(scaled)

    def _img_coords(self, ev):
        if self._frame is None or self.pixmap() is None:
            return None
        pw = self.pixmap().width()
        ph = self.pixmap().height()
        cw = self.width()
        ch = self.height()
        ox = (cw - pw) // 2
        oy = (ch - ph) // 2
        pos = ev.position()
        mx, my = pos.x() - ox, pos.y() - oy
        if mx < 0 or my < 0 or mx >= pw or my >= ph:
            return None
        fh, fw = self._frame.shape[:2]
        return (int(mx * fw / pw), int(my * fh / ph))

    def mousePressEvent(self, ev):
        pt = self._img_coords(ev)
        if pt is None:
            return
        ix, iy = pt

        if ev.button() == Qt.MouseButton.LeftButton:
            if self.mode == "A":
                self.wire_a_pts.append((ix, iy))
                self.mode_changed.emit(f"A线 +{len(self.wire_a_pts)}点")
            elif self.mode == "B":
                self.wire_b_pts.append((ix, iy))
                self.mode_changed.emit(f"B线 +{len(self.wire_b_pts)}点")
            elif self.mode == "L" and not self.lane_closed:
                self.lane_pts.append((ix, iy))
                self.mode_changed.emit(f"车道 +{len(self.lane_pts)}点")
        elif ev.button() == Qt.MouseButton.RightButton:
            if self.mode == "A" and len(self.wire_a_pts) >= 2:
                self.mode_changed.emit(f"A线完成 ({len(self.wire_a_pts)}点)")
            elif self.mode == "B" and len(self.wire_b_pts) >= 2:
                self.mode_changed.emit(f"B线完成 ({len(self.wire_b_pts)}点)")
            elif self.mode == "L" and len(self.lane_pts) >= 3:
                self.lane_closed = True
                self.mode_changed.emit(f"车道闭合 ({len(self.lane_pts)}点)")
        self._redraw()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._display is not None:
            self._redraw()


class PipelineWorker(QThread):
    progress_signal = pyqtSignal(int)
    status_signal = pyqtSignal(str)
    done_signal = pyqtSignal(object)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        try:
            twa = self._flat_norm(self.config["wire_a_pts"])
            twb = self._flat_norm(self.config["wire_b_pts"])
            lane = self._flat_norm(self.config["lane_pts"])

            def cb(pct):
                self.progress_signal.emit(pct)

            pipeline = PipelineRunner(
                model_name=self.config["model"],
                confidence=self.config["confidence"],
                iou=self.config["iou"],
                device="cuda:0",
                batch_size=self.config["batch"],
                resize_width=2560,
                sample_interval=3,
                output_fps=20,
                progress_callback=cb,
            )

            out_dir = tempfile.mkdtemp(prefix="traffic_")
            result = pipeline.run(
                video_path=self.config["video"],
                tripwire_a=twa,
                tripwire_b=twb,
                lane_mask=lane,
                output_dir=out_dir,
                output_video=True,
            )
            self.done_signal.emit(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.status_signal.emit(f"错误: {e}")

    def _flat_norm(self, pts):
        if not pts:
            return []
        h = self.config.get("orig_h", 2160)
        w = self.config.get("orig_w", 3840)
        flat = []
        for x, y in pts:
            flat.append(round(x / w, 4))
            flat.append(round(y / h, 4))
        return flat


class DesktopApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("交通流检测系统 TrafficFlow Analyzer")
        self.setMinimumSize(1280, 780)
        self._video_path = None
        self._orig_size = (3840, 2160)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # ── LEFT PANEL ──
        left = QWidget()
        left.setFixedWidth(300)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)

        # 1. Video
        g1 = QGroupBox("1. 视频上传")
        g1l = QVBoxLayout(g1)
        self._video_btn = QPushButton("选择视频文件")
        self._video_btn.clicked.connect(self._select_video)
        self._video_label = QLabel("未选择")
        self._video_label.setWordWrap(True)
        g1l.addWidget(self._video_btn)
        g1l.addWidget(self._video_label)
        self._extract_btn = QPushButton("提取标定帧")
        self._extract_btn.setEnabled(False)
        self._extract_btn.clicked.connect(self._extract_frame)
        g1l.addWidget(self._extract_btn)
        ll.addWidget(g1)

        # 2. Model
        g2 = QGroupBox("2. 模型与参数")
        g2l = QVBoxLayout(g2)
        g2l.addWidget(QLabel("YOLO 模型:"))
        self._model_cb = QComboBox()
        self._model_cb.addItems(MODELS)
        self._model_cb.setCurrentText("yolo11x.pt")
        g2l.addWidget(self._model_cb)

        g2l.addWidget(QLabel("置信度阈值:"))
        row1 = QHBoxLayout()
        self._conf_sl = QSlider(Qt.Orientation.Horizontal)
        self._conf_sl.setRange(5, 50)
        self._conf_sl.setValue(10)
        self._conf_label = QLabel("0.10")
        self._conf_sl.valueChanged.connect(lambda v: self._conf_label.setText(f"{v/100:.2f}"))
        row1.addWidget(self._conf_sl)
        row1.addWidget(self._conf_label)
        g2l.addLayout(row1)

        g2l.addWidget(QLabel("IoU 阈值:"))
        row2 = QHBoxLayout()
        self._iou_sl = QSlider(Qt.Orientation.Horizontal)
        self._iou_sl.setRange(30, 90)
        self._iou_sl.setValue(65)
        self._iou_label = QLabel("0.65")
        self._iou_sl.valueChanged.connect(lambda v: self._iou_label.setText(f"{v/100:.2f}"))
        row2.addWidget(self._iou_sl)
        row2.addWidget(self._iou_label)
        g2l.addLayout(row2)

        g2l.addWidget(QLabel("Batch Size:"))
        self._batch_sb = QSpinBox()
        self._batch_sb.setRange(2, 16)
        self._batch_sb.setValue(8)
        g2l.addWidget(self._batch_sb)
        ll.addWidget(g2)

        # 3. Calibration
        g3 = QGroupBox("3. 标定模式")
        g3l = QVBoxLayout(g3)
        self._mode_a = QRadioButton("A线 — 进入确认 (黄)")
        self._mode_b = QRadioButton("B线 — 计数触发 (红)")
        self._mode_l = QRadioButton("车道掩膜 (绿)")
        self._mode_a.setChecked(True)
        self._mode_a.toggled.connect(lambda: self._set_mode("A"))
        self._mode_b.toggled.connect(lambda: self._set_mode("B"))
        self._mode_l.toggled.connect(lambda: self._set_mode("L"))
        g3l.addWidget(self._mode_a)
        g3l.addWidget(self._mode_b)
        g3l.addWidget(self._mode_l)
        self._mode_status = QLabel("左键加点 | 右键完成")
        g3l.addWidget(self._mode_status)
        row_btns = QHBoxLayout()
        undo_btn = QPushButton("撤销")
        undo_btn.clicked.connect(self._undo)
        clear_btn = QPushButton("清除")
        clear_btn.clicked.connect(self._clear_mode)
        row_btns.addWidget(undo_btn)
        row_btns.addWidget(clear_btn)
        g3l.addLayout(row_btns)
        ll.addWidget(g3)

        # 4. Run
        g4 = QGroupBox("4. 运行")
        g4l = QVBoxLayout(g4)
        self._run_btn = QPushButton("开始检测")
        self._run_btn.setEnabled(False)
        self._run_btn.setStyleSheet(
            "QPushButton { background:#2196F3; color:white; padding:8px; font-weight:bold; }"
            "QPushButton:disabled { background:#666; }"
        )
        self._run_btn.clicked.connect(self._run_pipeline)
        g4l.addWidget(self._run_btn)
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        g4l.addWidget(self._progress)
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        g4l.addWidget(self._status_label)
        ll.addWidget(g4)
        ll.addStretch()

        # ── RIGHT PANEL ──
        right = QSplitter(Qt.Orientation.Vertical)
        right.setStyleSheet("QSplitter::handle { background:#333; }")

        self._canvas = CalibCanvas()
        self._canvas.mode_changed.connect(lambda s: self._mode_status.setText(s))
        right.addWidget(self._canvas)

        self._result_tabs = QTabWidget()
        self._result_tabs.setVisible(False)

        self._video_result_label = QLabel("输出视频将在此显示")
        self._video_result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_tabs.addTab(self._video_result_label, "输出视频")

        self._chart_container = QWidget()
        cl = QVBoxLayout(self._chart_container)
        self._fig = Figure(figsize=(10, 5), dpi=100)
        self._canvas_chart = FigureCanvasQTAgg(self._fig)
        cl.addWidget(self._canvas_chart)
        self._result_tabs.addTab(self._chart_container, "统计图表")

        self._table = QTableWidget()
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(["车型", "数量"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._result_tabs.addTab(self._table, "数据汇总")

        right.addWidget(self._result_tabs)
        right.setSizes([450, 300])
        main_layout.addWidget(left)
        main_layout.addWidget(right, 1)

    def _select_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频", "",
            "Video Files (*.mp4 *.avi *.mov *.mkv);;All Files (*)")
        if path:
            self._video_path = path
            self._video_label.setText(os.path.basename(path))
            self._extract_btn.setEnabled(True)

    def _extract_frame(self):
        cap = cv2.VideoCapture(self._video_path)
        if not cap.isOpened():
            QMessageBox.warning(self, "错误", "无法打开视频")
            return
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._orig_size = (
            int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
        mid = total // 2
        cap.set(cv2.CAP_PROP_POS_FRAMES, mid)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            QMessageBox.warning(self, "错误", "读取帧失败")
            return
        self._canvas.set_frame(frame)
        self._run_btn.setEnabled(True)
        self._status_label.setText(
            f"标定帧 ({self._orig_size[0]}x{self._orig_size[1]}) | 在画面上点击标定A/B线"
        )

    def _set_mode(self, mode):
        self._canvas.mode = mode
        names = {"A": "A线(黄) 左键加点 右键完成", "B": "B线(红) 左键加点 右键完成",
                 "L": "车道(绿) 左键加点 右键闭合"}
        self._mode_status.setText(names[mode])

    def _undo(self):
        m = self._canvas.mode
        if m == "A" and self._canvas.wire_a_pts:
            self._canvas.wire_a_pts.pop()
        elif m == "B" and self._canvas.wire_b_pts:
            self._canvas.wire_b_pts.pop()
        elif m == "L" and self._canvas.lane_pts:
            self._canvas.lane_pts.pop()
            self._canvas.lane_closed = False
        self._canvas._redraw()

    def _clear_mode(self):
        m = self._canvas.mode
        if m == "A":
            self._canvas.wire_a_pts.clear()
        elif m == "B":
            self._canvas.wire_b_pts.clear()
        elif m == "L":
            self._canvas.lane_pts.clear()
            self._canvas.lane_closed = False
        self._canvas._redraw()
        self._mode_status.setText("已清除")

    def _run_pipeline(self):
        if len(self._canvas.wire_a_pts) < 2:
            QMessageBox.warning(self, "标定未完成", "请先完成A线标定 (至少2个点, 右键完成)")
            return
        if len(self._canvas.wire_b_pts) < 2:
            QMessageBox.warning(self, "标定未完成", "请先完成B线标定 (至少2个点, 右键完成)")
            return

        self._run_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._result_tabs.setVisible(False)

        config = {
            "video": self._video_path,
            "model": self._model_cb.currentText(),
            "confidence": self._conf_sl.value() / 100,
            "iou": self._iou_sl.value() / 100,
            "batch": self._batch_sb.value(),
            "wire_a_pts": list(self._canvas.wire_a_pts),
            "wire_b_pts": list(self._canvas.wire_b_pts),
            "lane_pts": list(self._canvas.lane_pts),
            "orig_w": self._orig_size[0],
            "orig_h": self._orig_size[1],
        }

        self._worker = PipelineWorker(config)
        self._worker.progress_signal.connect(self._on_progress)
        self._worker.status_signal.connect(self._on_status)
        self._worker.done_signal.connect(self._on_done)
        self._worker.start()

    def _on_progress(self, pct):
        self._progress.setValue(pct)
        self._status_label.setText(f"检测中... {pct}%")

    def _on_status(self, msg):
        self._status_label.setText(msg)

    def _on_done(self, result):
        self._run_btn.setEnabled(True)
        self._progress.setVisible(False)

        if result is None:
            self._status_label.setText("错误: 未返回结果")
            return

        stats = result.get("stats")
        if stats:
            self._status_label.setText(
                f"完成! 总计: {stats.total_vehicles} | "
                f"car:{stats.vehicles_by_type.get('car',0)} "
                f"bus:{stats.vehicles_by_type.get('bus',0)} "
                f"truck:{stats.vehicles_by_type.get('truck',0)} "
                f"moto:{stats.vehicles_by_type.get('motorcycle',0)} | "
                f"耗时:{result.get('elapsed',0):.0f}s @ {result.get('fps',0):.1f}fps"
            )

            # Table
            self._table.setRowCount(0)
            for k, v in stats.vehicles_by_type.items():
                r = self._table.rowCount()
                self._table.insertRow(r)
                self._table.setItem(r, 0, QTableWidgetItem(k))
                self._table.setItem(r, 1, QTableWidgetItem(str(v)))
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setItem(r, 0, QTableWidgetItem("总计"))
            self._table.setItem(r, 1, QTableWidgetItem(str(stats.total_vehicles)))
        else:
            self._status_label.setText(f"完成! 耗时:{result.get('elapsed',0):.0f}s (无统计数据)")

        # Video link
        vpath = result.get("output_video")
        if vpath and os.path.exists(vpath):
            self._video_result_label.setText(f"输出视频已生成:\n{vpath}")
            self._video_result_label.setStyleSheet("color:#4CAF50; padding:20px;")
        else:
            self._video_result_label.setText("(视频未生成)")

        # Charts
        self._fig.clear()
        flow_path = result.get("charts", {}).get("flow_timeline")
        if flow_path and os.path.exists(flow_path):
            flow_img = cv2.imread(flow_path)
            flow_img = cv2.cvtColor(flow_img, cv2.COLOR_BGR2RGB)
            ax = self._fig.add_subplot(211)
            ax.imshow(flow_img)
            ax.axis("off")
            ax.set_title("Traffic Flow Timeline")
        type_path = result.get("charts", {}).get("vehicle_types")
        if type_path and os.path.exists(type_path):
            type_img = cv2.imread(type_path)
            type_img = cv2.cvtColor(type_img, cv2.COLOR_BGR2RGB)
            ax2 = self._fig.add_subplot(212)
            ax2.imshow(type_img)
            ax2.axis("off")
            ax2.set_title("Vehicle Types")
        self._fig.tight_layout()
        self._canvas_chart.draw()
        self._result_tabs.setVisible(True)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = DesktopApp()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
