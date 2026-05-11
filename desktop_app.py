"""
交通流检测 — 桌面版 (PyQt6)
"""
import sys, os, tempfile
from pathlib import Path
import cv2, numpy as np

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QComboBox, QSlider, QSpinBox,
    QGroupBox, QProgressBar, QTableWidget, QTableWidgetItem,
    QSplitter, QMessageBox, QRadioButton, QHeaderView,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import PipelineRunner

MODELS = ["yolo11n.pt", "yolo11s.pt", "yolo11m.pt", "yolo11l.pt", "yolo11x.pt"]


class CalibCanvas(QLabel):
    mode_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(500, 300)
        self.setStyleSheet("background:#1a1a1a; border:1px solid #333;")
        self.setText("1. 选择视频 → 2. 提取标定帧")
        self._frame = None
        self.lane_pts = []
        self.wire_a_pts = []
        self.wire_b_pts = []
        self.lane_closed = False
        self.mode = "A"

    def set_frame(self, img):
        self._frame = img.copy()
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
        pw, ph = self.pixmap().width(), self.pixmap().height()
        cw, ch = self.width(), self.height()
        ox, oy = (cw - pw) // 2, (ch - ph) // 2
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
        x, y = pt
        if ev.button() == Qt.MouseButton.LeftButton:
            if self.mode == "A":
                self.wire_a_pts.append((x, y))
                self.mode_changed.emit(f"A线 {len(self.wire_a_pts)} 点")
            elif self.mode == "B":
                self.wire_b_pts.append((x, y))
                self.mode_changed.emit(f"B线 {len(self.wire_b_pts)} 点")
            elif self.mode == "L" and not self.lane_closed:
                self.lane_pts.append((x, y))
                self.mode_changed.emit(f"车道 {len(self.lane_pts)} 点")
        elif ev.button() == Qt.MouseButton.RightButton:
            if self.mode == "A" and len(self.wire_a_pts) >= 2:
                self.mode_changed.emit(f"A线完成 ✓ ({len(self.wire_a_pts)}段)")
            elif self.mode == "B" and len(self.wire_b_pts) >= 2:
                self.mode_changed.emit(f"B线完成 ✓ ({len(self.wire_b_pts)}段)")
            elif self.mode == "L" and len(self.lane_pts) >= 3:
                self.lane_closed = True
                self.mode_changed.emit(f"车道闭合 ✓ ({len(self.lane_pts)}点)")
        self._redraw()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._frame is not None:
            self._redraw()


class PipelineWorker(QThread):
    progress = pyqtSignal(int)
    done = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.cfg = config

    def run(self):
        try:
            twa, twb, lane = [], [], []
            h, w = self.cfg["orig_h"], self.cfg["orig_w"]
            for x, y in self.cfg.get("wire_a_pts", []):
                twa += [round(x / w, 4), round(y / h, 4)]
            for x, y in self.cfg.get("wire_b_pts", []):
                twb += [round(x / w, 4), round(y / h, 4)]
            for x, y in self.cfg.get("lane_pts", []):
                lane += [round(x / w, 4), round(y / h, 4)]

            def cb(pct):
                self.progress.emit(pct)

            pipeline = PipelineRunner(
                model_name=self.cfg["model"],
                confidence=self.cfg["confidence"],
                iou=self.cfg["iou"],
                device="cuda:0",
                batch_size=self.cfg["batch"],
                resize_width=2560,
                sample_interval=3,
                output_fps=20,
                progress_callback=cb,
            )
            result = pipeline.run(
                video_path=self.cfg["video"],
                tripwire_a=twa,
                tripwire_b=twb,
                lane_mask=lane,
                output_dir=self.cfg["output_dir"],
                output_video=True,
            )
            self.done.emit(result)
        except Exception as e:
            import traceback
            self.error.emit(f"{e}\n{traceback.format_exc()}")


class DesktopApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TrafficFlow Analyzer v1.0.0")
        self.setMinimumSize(1200, 750)
        self._video_path = None
        self._orig_size = (3840, 2160)
        self._output_dir = None

        cw = QWidget()
        self.setCentralWidget(cw)
        ml = QHBoxLayout(cw)
        ml.setContentsMargins(6, 6, 6, 6)

        # ═══ LEFT PANEL ═══
        left = QWidget()
        left.setFixedWidth(280)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)

        # 1. Video
        g1 = QGroupBox("1. 视频")
        g1l = QVBoxLayout(g1)
        self._vid_btn = QPushButton("选择视频文件")
        self._vid_btn.clicked.connect(self._select_video)
        self._vid_label = QLabel("未选择")
        self._vid_label.setWordWrap(True)
        g1l.addWidget(self._vid_btn)
        g1l.addWidget(self._vid_label)

        self._extract_btn = QPushButton("提取标定帧")
        self._extract_btn.setEnabled(False)
        self._extract_btn.clicked.connect(self._extract_frame)
        g1l.addWidget(self._extract_btn)

        self._out_btn = QPushButton("选择输出目录")
        self._out_btn.clicked.connect(self._select_output)
        self._out_label = QLabel("输出: 临时目录")
        self._out_label.setWordWrap(True)
        g1l.addWidget(self._out_btn)
        g1l.addWidget(self._out_label)
        ll.addWidget(g1)

        # 2. Model
        g2 = QGroupBox("2. 模型与参数")
        g2l = QVBoxLayout(g2)
        self._model_cb = QComboBox()
        self._model_cb.addItems(MODELS)
        self._model_cb.setCurrentText("yolo11x.pt")
        g2l.addWidget(QLabel("模型:"))
        g2l.addWidget(self._model_cb)

        g2l.addWidget(QLabel("置信度:"))
        r1 = QHBoxLayout()
        self._conf_sl = QSlider(Qt.Orientation.Horizontal)
        self._conf_sl.setRange(5, 50); self._conf_sl.setValue(10)
        self._conf_lb = QLabel("0.10")
        self._conf_sl.valueChanged.connect(lambda v: self._conf_lb.setText(f"{v/100:.2f}"))
        r1.addWidget(self._conf_sl); r1.addWidget(self._conf_lb)
        g2l.addLayout(r1)

        g2l.addWidget(QLabel("IoU:"))
        r2 = QHBoxLayout()
        self._iou_sl = QSlider(Qt.Orientation.Horizontal)
        self._iou_sl.setRange(30, 90); self._iou_sl.setValue(65)
        self._iou_lb = QLabel("0.65")
        self._iou_sl.valueChanged.connect(lambda v: self._iou_lb.setText(f"{v/100:.2f}"))
        r2.addWidget(self._iou_sl); r2.addWidget(self._iou_lb)
        g2l.addLayout(r2)

        g2l.addWidget(QLabel("Batch:"))
        self._batch_sb = QSpinBox()
        self._batch_sb.setRange(2, 16); self._batch_sb.setValue(8)
        g2l.addWidget(self._batch_sb)
        ll.addWidget(g2)

        # 3. Calib mode
        g3 = QGroupBox("3. 标定 (左键加点 右键完成)")
        g3l = QVBoxLayout(g3)
        self._mode_a = QRadioButton("A线 进入确认 (黄)")
        self._mode_b = QRadioButton("B线 计数触发 (红)")
        self._mode_l = QRadioButton("车道掩膜 (绿)")
        self._mode_a.setChecked(True)
        self._mode_a.toggled.connect(lambda: self._set_mode("A"))
        self._mode_b.toggled.connect(lambda: self._set_mode("B"))
        self._mode_l.toggled.connect(lambda: self._set_mode("L"))
        g3l.addWidget(self._mode_a)
        g3l.addWidget(self._mode_b)
        g3l.addWidget(self._mode_l)
        self._mode_status = QLabel("A线: 左键加点 | 右键完成")
        g3l.addWidget(self._mode_status)
        br = QHBoxLayout()
        self._undo_btn = QPushButton("撤销"); self._undo_btn.clicked.connect(self._undo)
        self._clear_btn = QPushButton("清除"); self._clear_btn.clicked.connect(self._clear_mode)
        br.addWidget(self._undo_btn); br.addWidget(self._clear_btn)
        g3l.addLayout(br)
        ll.addWidget(g3)

        # 4. Run
        g4 = QGroupBox("4. 运行")
        g4l = QVBoxLayout(g4)
        self._run_btn = QPushButton("开始检测")
        self._run_btn.setEnabled(False)
        self._run_btn.setStyleSheet(
            "QPushButton{background:#2196F3;color:white;padding:10px;font-weight:bold}"
            "QPushButton:disabled{background:#555}")
        self._run_btn.clicked.connect(self._run)
        g4l.addWidget(self._run_btn)
        self._prog = QProgressBar(); self._prog.setVisible(False)
        g4l.addWidget(self._prog)
        ll.addWidget(g4)
        ll.addStretch()

        # ═══ RIGHT PANEL ═══
        right = QSplitter(Qt.Orientation.Vertical)

        # Top: calibration canvas
        self._canvas = CalibCanvas()
        self._canvas.mode_changed.connect(lambda s: self._mode_status.setText(s))
        right.addWidget(self._canvas)

        # Bottom: results
        result_widget = QWidget()
        rl = QVBoxLayout(result_widget)
        rl.setContentsMargins(0, 4, 0, 0)

        self._result_title = QLabel("")
        self._result_title.setStyleSheet("font-weight:bold; font-size:13px;")
        rl.addWidget(self._result_title)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["车型", "数量", "占比", "高峰分钟流量"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setMaximumHeight(140)
        rl.addWidget(self._table)

        bottom_row = QHBoxLayout()
        self._status_label = QLabel("等待操作...")
        self._status_label.setWordWrap(True)
        bottom_row.addWidget(self._status_label, 1)
        self._csv_label = QLabel("")
        self._csv_label.setStyleSheet("color:#4CAF50;")
        self._csv_label.setOpenExternalLinks(True)
        bottom_row.addWidget(self._csv_label)
        rl.addLayout(bottom_row)

        right.addWidget(result_widget)
        right.setSizes([450, 280])
        ml.addWidget(left)
        ml.addWidget(right, 1)

    # ── slots ──
    def _select_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择视频", "",
                                               "Video (*.mp4 *.avi *.mov *.mkv);;All (*)")
        if path:
            self._video_path = path
            self._vid_label.setText(os.path.basename(path))
            self._extract_btn.setEnabled(True)

    def _select_output(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self._output_dir = d
            self._out_label.setText(d)

    def _extract_frame(self):
        cap = cv2.VideoCapture(self._video_path)
        if not cap.isOpened():
            QMessageBox.warning(self, "错误", "无法打开视频"); return
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._orig_size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                           int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            QMessageBox.warning(self, "错误", "读取帧失败"); return
        self._canvas.set_frame(frame)
        self._run_btn.setEnabled(True)
        self._status_label.setText(f"标定帧 {self._orig_size[0]}x{self._orig_size[1]} | 左键加点 右键完成")

    def _set_mode(self, m):
        self._canvas.mode = m
        names = {"A": "A线(黄) 左键加点 右键完成", "B": "B线(红) 左键加点 右键完成",
                 "L": "车道(绿) 左键加点 右键闭合"}
        self._mode_status.setText(names[m])

    def _undo(self):
        m = self._canvas.mode
        if m == "A" and self._canvas.wire_a_pts: self._canvas.wire_a_pts.pop()
        elif m == "B" and self._canvas.wire_b_pts: self._canvas.wire_b_pts.pop()
        elif m == "L" and self._canvas.lane_pts:
            self._canvas.lane_pts.pop(); self._canvas.lane_closed = False
        self._canvas._redraw()

    def _clear_mode(self):
        m = self._canvas.mode
        if m == "A": self._canvas.wire_a_pts.clear()
        elif m == "B": self._canvas.wire_b_pts.clear()
        elif m == "L": self._canvas.lane_pts.clear(); self._canvas.lane_closed = False
        self._canvas._redraw()
        self._mode_status.setText("已清除")

    def _run(self):
        if len(self._canvas.wire_a_pts) < 2:
            QMessageBox.warning(self, "未完成", "A线至少需要2个点 (右键完成)"); return
        if len(self._canvas.wire_b_pts) < 2:
            QMessageBox.warning(self, "未完成", "B线至少需要2个点 (右键完成)"); return

        self._run_btn.setEnabled(False)
        self._run_btn.setText("检测中...")
        self._prog.setVisible(True)
        self._prog.setValue(0)
        self._result_title.setText("")
        self._table.setRowCount(0)
        self._csv_label.setText("")

        out_dir = self._output_dir or tempfile.mkdtemp(prefix="traffic_")

        self._worker = PipelineWorker({
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
            "output_dir": out_dir,
        })
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, pct):
        self._prog.setValue(pct)

    def _on_error(self, msg):
        self._run_btn.setEnabled(True)
        self._run_btn.setText("开始检测")
        self._prog.setVisible(False)
        self._status_label.setText(f"错误: {msg}")
        QMessageBox.critical(self, "检测失败", msg)

    def _on_done(self, result):
        self._run_btn.setEnabled(True)
        self._run_btn.setText("开始检测")
        self._prog.setVisible(False)

        stats = result.get("stats")
        if not stats:
            self._status_label.setText("无统计数据")
            return

        total = stats.total_vehicles
        types = dict(stats.vehicles_by_type)
        peak_flow = stats.peak_flow
        peak_min = stats.peak_minute

        # Title
        elapsed = result.get("elapsed", 0)
        fps = result.get("fps", 0)
        self._result_title.setText(
            f"检测完成 — 总计 {total} 辆 | 耗时 {elapsed:.0f}s @ {fps:.1f}fps"
        )

        # Table
        type_order = ["car", "bus", "truck", "motorcycle"]
        type_names = {"car": "汽车", "bus": "公交", "truck": "卡车", "motorcycle": "摩托车"}
        self._table.setRowCount(0)
        for key in type_order:
            v = types.get(key, 0)
            if v > 0:
                r = self._table.rowCount()
                self._table.insertRow(r)
                self._table.setItem(r, 0, QTableWidgetItem(type_names.get(key, key)))
                self._table.setItem(r, 1, QTableWidgetItem(str(v)))
                self._table.setItem(r, 2, QTableWidgetItem(f"{v/total*100:.1f}%" if total else "0%"))
                self._table.setItem(r, 3, QTableWidgetItem(
                    f"第{peak_min}分钟 {peak_flow}辆" if peak_flow else "-"))
        # Total row
        r = self._table.rowCount()
        self._table.insertRow(r)
        self._table.setItem(r, 0, QTableWidgetItem("合计"))
        self._table.setItem(r, 1, QTableWidgetItem(str(total)))

        # Status & CSV
        self._status_label.setText(
            f"car:{types.get('car',0)} bus:{types.get('bus',0)} "
            f"truck:{types.get('truck',0)} moto:{types.get('motorcycle',0)}"
        )
        csv_path = result.get("csv")
        vpath = result.get("output_video")
        if csv_path and os.path.exists(csv_path):
            self._csv_label.setText(f"CSV: {csv_path}\n视频: {vpath or '无'}")

        # 打开输出目录
        out_dir = os.path.dirname(csv_path) if csv_path else None
        if out_dir:
            os.startfile(out_dir)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = DesktopApp()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
