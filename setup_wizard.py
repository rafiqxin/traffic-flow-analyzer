"""
TrafficFlow Analyzer v1.0.0 — Windows 安装向导

双击运行 → 4 步安装 → 自动打开应用 UI。
"""
import sys, os, subprocess, shutil
from pathlib import Path

# ── bundle 路径 ──
if getattr(sys, 'frozen', False):
    BUNDLE = Path(sys._MEIPASS) / "bundle"
else:
    BUNDLE = Path(__file__).parent.parent / "bundle"

ENV_NAME = "yolovenv"
MINICONDA_EXE = "miniconda_installer.exe"
SRC_FILES = [
    "calibrate_roi.py", "desktop_app.py", "main.py", "pipeline.py",
    "pyproject.toml", "requirements.txt",
]
SRC_DIRS = ["config", "src"]
DEFAULT_DIR = Path.home() / "TrafficFlowAnalyzer"


def run(cmd, **kw):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)


def is_installed(install_dir):
    python = Path(install_dir) / "miniconda" / "envs" / ENV_NAME / "python.exe"
    app = Path(install_dir) / "desktop_app.py"
    return python.exists() and app.exists()


def launch_app(install_dir):
    python = Path(install_dir) / "miniconda" / "envs" / ENV_NAME / "python.exe"
    app = Path(install_dir) / "desktop_app.py"
    subprocess.Popen(
        [str(python), str(app)],
        cwd=str(install_dir),
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def make_desktop_shortcut(install_dir):
    try:
        conda = Path(install_dir) / "miniconda" / "Scripts" / "conda.exe"
        lnk = Path.home() / "Desktop" / "TrafficFlow Analyzer.lnk"
        if lnk.exists():
            lnk.unlink()
        app = Path(install_dir) / "desktop_app.py"
        ps = (
            f"$WS = New-Object -ComObject WScript.Shell; "
            f"$SC = $WS.CreateShortcut('{lnk}'); "
            f"$SC.TargetPath = '{conda}'; "
            f"$SC.Arguments = 'run -n {ENV_NAME} python \"{app}\"'; "
            f"$SC.WorkingDirectory = '{install_dir}'; "
            f"$SC.IconLocation = 'shell32.dll,15'; $SC.Save()"
        )
        subprocess.run(["powershell", "-Command", ps], capture_output=True)
    except Exception:
        pass


def make_startmenu_shortcut(install_dir):
    try:
        conda = Path(install_dir) / "miniconda" / "Scripts" / "conda.exe"
        sm = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "TrafficFlow Analyzer"
        sm.mkdir(parents=True, exist_ok=True)
        app = Path(install_dir) / "desktop_app.py"
        lnk = sm / "TrafficFlow Analyzer.lnk"
        ps = (
            f"$WS = New-Object -ComObject WScript.Shell; "
            f"$SC = $WS.CreateShortcut('{lnk}'); "
            f"$SC.TargetPath = '{conda}'; "
            f"$SC.Arguments = 'run -n {ENV_NAME} python \"{app}\"'; "
            f"$SC.WorkingDirectory = '{install_dir}'; "
            f"$SC.IconLocation = 'shell32.dll,15'; $SC.Save()"
        )
        subprocess.run(["powershell", "-Command", ps], capture_output=True)
    except Exception:
        pass


def make_uninstaller(install_dir):
    install_dir = Path(install_dir)
    batch = install_dir / "uninstall.bat"
    with open(batch, "w", encoding="utf-8") as f:
        f.write(f"""@echo off
chcp 65001 >nul
echo ============================================
echo   TrafficFlow Analyzer 卸载程序
echo ============================================
echo.
echo 即将删除以下内容:
echo   - 应用程序: {install_dir}
echo   - Conda 环境: {ENV_NAME}
echo   - 桌面快捷方式
echo   - 开始菜单快捷方式
echo.
set /p CONFIRM="确认卸载? (输入 Y 继续): "
if /i not "%CONFIRM%"=="Y" (echo 已取消 & pause & exit /b)
echo 删除快捷方式...
del /q "%USERPROFILE%\\Desktop\\TrafficFlow Analyzer.lnk" 2>nul
rmdir /s /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\TrafficFlow Analyzer" 2>nul
echo 删除 Conda 环境...
"{install_dir / "miniconda" / "Scripts" / "conda.exe"}" env remove -n {ENV_NAME} -y 2>nul
echo 删除安装目录...
cd /d "%USERPROFILE%"
rmdir /s /q "{install_dir}" 2>nul
echo 卸载完成! 部分残留文件需手动清理。
pause
""")


def do_install(install_dir, log_func, prog_func):
    d = Path(install_dir)
    d.mkdir(parents=True, exist_ok=True)
    conda = str(d / "miniconda" / "Scripts" / "conda.exe")

    # 1. Miniconda
    log_func("[1/6] 安装 Miniconda ...")
    mci = BUNDLE / MINICONDA_EXE
    if not mci.exists():
        log_func("错误: 未找到 Miniconda 安装包")
        return False
    run(f'"{mci}" /InstallationType=JustMe /RegisterPython=0 /S /D={d / "miniconda"}')
    prog_func(20)

    # 2. 复制源码
    log_func(f"[2/6] 安装应用程序到 {d} ...")
    for f in SRC_FILES:
        src = BUNDLE / f
        if src.exists():
            shutil.copy2(src, d / f)
    for sd in SRC_DIRS:
        src_dir = BUNDLE / sd
        if src_dir.exists():
            dst = d / sd
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src_dir, dst)
    prog_func(35)

    # 3. 创建 conda 环境
    log_func(f"[3/6] 创建 Python 3.10 环境 '{ENV_NAME}' ...")
    run(f'"{conda}" create -n {ENV_NAME} python=3.10 -y')
    prog_func(50)

    # 4. PyTorch (~2GB 在线下载)
    log_func("[4/6] 下载安装 PyTorch + CUDA 12.1 (~2GB) ...")
    result = run(
        f'"{conda}" run -n {ENV_NAME} pip install torch torchvision '
        f'--index-url https://download.pytorch.org/whl/cu121 -q'
    )
    if result.returncode != 0:
        log_func(f"PyTorch 安装失败: {result.stderr}")
        return False
    prog_func(70)

    # 5. AI + GUI 依赖
    log_func("[5/6] 安装 ultralytics + OpenCV + PyQt6 ...")
    result = run(
        f'"{conda}" run -n {ENV_NAME} pip install '
        f'ultralytics opencv-python numpy scipy matplotlib pyyaml pyqt6 -q'
    )
    if result.returncode != 0:
        log_func(f"依赖安装失败: {result.stderr}")
        return False
    prog_func(90)

    # 6. 验证
    log_func("[6/6] 验证安装 ...")
    result = run(
        f'"{conda}" run -n {ENV_NAME} python -c '
        f'"import torch; print(\'CUDA:\', torch.cuda.is_available()); '
        f'import cv2; from ultralytics import YOLO; print(\'OK\')"'
    )
    log_func(f"  {result.stdout.strip() or 'OK'}")
    prog_func(100)
    log_func("")
    log_func("=" * 50)
    log_func("安装完成!")
    log_func("=" * 50)
    return True


# ─────────────────────────────────────────────
# 安装向导 UI (QStackedWidget)
# ─────────────────────────────────────────────
def run_wizard():
    from PyQt6.QtWidgets import (
        QApplication, QDialog, QStackedWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QProgressBar, QTextEdit, QCheckBox, QLineEdit,
        QPushButton, QFileDialog, QWidget, QSpacerItem, QSizePolicy,
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    dlg = QDialog()
    dlg.setWindowTitle("TrafficFlow Analyzer v1.0.0 安装向导")
    dlg.setMinimumSize(560, 460)
    dlg.setMaximumSize(560, 460)

    root = QVBoxLayout(dlg)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    # ── 顶部标题栏 ──
    header = QWidget()
    header.setStyleSheet("background:#1a1a2e;")
    header.setFixedHeight(72)
    hl = QVBoxLayout(header)
    hl.setContentsMargins(24, 12, 24, 8)
    wizard_title = QLabel("TrafficFlow Analyzer 安装向导")
    wizard_title.setStyleSheet("color:white; font-size:16px; font-weight:bold;")
    hl.addWidget(wizard_title)
    wizard_subtitle = QLabel("")
    wizard_subtitle.setStyleSheet("color:#aaa; font-size:12px;")
    hl.addWidget(wizard_subtitle)
    root.addWidget(header)

    # ── 页面堆栈 ──
    stack = QStackedWidget()
    root.addWidget(stack, 1)

    # ── 底部按钮栏 ──
    footer = QWidget()
    footer.setStyleSheet("background:#f5f5f5; border-top:1px solid #ddd;")
    footer.setFixedHeight(52)
    fl = QHBoxLayout(footer)
    fl.setContentsMargins(16, 8, 16, 8)
    fl.addStretch()

    back_btn = QPushButton("上一步")
    back_btn.setFixedWidth(90)
    fl.addWidget(back_btn)

    next_btn = QPushButton("下一步")
    next_btn.setFixedWidth(90)
    next_btn.setStyleSheet(
        "QPushButton{background:#2196F3; color:white; padding:6px; border-radius:4px; font-weight:bold;}"
        "QPushButton:disabled{background:#ccc;}"
    )
    fl.addWidget(next_btn)

    cancel_btn = QPushButton("取消")
    cancel_btn.setFixedWidth(70)
    cancel_btn.setStyleSheet("QPushButton{padding:6px;}")
    fl.addWidget(cancel_btn)

    root.addWidget(footer)

    # ═══════════════════════════════════════
    # PAGE 0 — 欢迎
    # ═══════════════════════════════════════
    p0 = QWidget()
    l0 = QVBoxLayout(p0)
    l0.setContentsMargins(32, 24, 32, 16)
    l0.addWidget(QLabel("欢迎使用 TrafficFlow Analyzer v1.0.0"))
    l0.addWidget(QLabel("交通路口车辆检测 / 跟踪 / 计数系统"))
    l0.addSpacing(16)
    info0 = QLabel(
        "本安装向导将指导您完成以下安装:\n\n"
        "  - Miniconda Python 3.10 环境\n"
        "  - PyTorch + CUDA 12.1 GPU 加速\n"
        "  - YOLO11 目标检测模型 (n/s/m/l/x)\n"
        "  - 车辆多目标跟踪 (ByteTrack)\n"
        "  - 交通流统计分析 & 可视化\n\n"
        "系统要求:\n"
        "  - Windows 10/11 64-bit\n"
        "  - NVIDIA 显卡 (推荐 8GB+ 显存)\n"
        "  - 约 10GB 磁盘空间\n"
        "  - 联网下载 PyTorch (~2GB)"
    )
    info0.setWordWrap(True)
    l0.addWidget(info0)
    l0.addStretch()
    stack.addWidget(p0)

    # ═══════════════════════════════════════
    # PAGE 1 — 安装路径
    # ═══════════════════════════════════════
    p1 = QWidget()
    l1 = QVBoxLayout(p1)
    l1.setContentsMargins(32, 24, 32, 16)

    l1.addWidget(QLabel("选择安装位置"))
    l1.addWidget(QLabel("选择 TrafficFlow Analyzer 的安装目录。"))
    l1.addSpacing(12)
    l1.addWidget(QLabel("安装路径:"))

    path_row = QHBoxLayout()
    path_edit = QLineEdit(str(DEFAULT_DIR))
    path_edit.setMinimumHeight(30)
    path_row.addWidget(path_edit)
    browse_btn = QPushButton("浏览...")
    browse_btn.setFixedWidth(80)

    def browse():
        d = QFileDialog.getExistingDirectory(dlg, "选择安装目录", str(DEFAULT_DIR))
        if d:
            path_edit.setText(d)
    browse_btn.clicked.connect(browse)
    path_row.addWidget(browse_btn)
    l1.addLayout(path_row)
    l1.addSpacing(8)

    disk_label = QLabel("")
    l1.addWidget(disk_label)

    def update_disk():
        try:
            p = Path(path_edit.text())
            drive = p.drive or "C:\\"
            usage = shutil.disk_usage(drive)
            free_gb = usage.free / (1024 ** 3)
            disk_label.setText(f"可用磁盘空间: {free_gb:.1f} GB (需要约 10 GB)")
            disk_label.setStyleSheet("color:green;" if free_gb >= 10 else "color:red;")
        except Exception:
            disk_label.setText("")
    path_edit.textChanged.connect(update_disk)
    update_disk()
    l1.addSpacing(16)

    desktop_cb = QCheckBox("创建桌面快捷方式")
    desktop_cb.setChecked(True)
    l1.addWidget(desktop_cb)

    startmenu_cb = QCheckBox("创建开始菜单文件夹")
    startmenu_cb.setChecked(True)
    l1.addWidget(startmenu_cb)
    l1.addStretch()
    stack.addWidget(p1)

    # ═══════════════════════════════════════
    # PAGE 2 — 安装进度
    # ═══════════════════════════════════════
    p2 = QWidget()
    l2 = QVBoxLayout(p2)
    l2.setContentsMargins(32, 24, 32, 16)

    step_label = QLabel("准备安装...")
    step_label.setStyleSheet("font-weight:bold; font-size:13px;")
    l2.addWidget(step_label)

    progress = QProgressBar()
    progress.setTextVisible(True)
    l2.addWidget(progress)

    l2.addWidget(QLabel("安装日志:"))
    log_view = QTextEdit()
    log_view.setReadOnly(True)
    log_view.setStyleSheet(
        "QTextEdit{background:#1a1a1a; color:#ddd;"
        "font-family:Consolas; font-size:12px;}"
    )
    l2.addWidget(log_view)
    stack.addWidget(p2)

    # ═══════════════════════════════════════
    # PAGE 3 — 完成
    # ═══════════════════════════════════════
    p3 = QWidget()
    l3 = QVBoxLayout(p3)
    l3.setContentsMargins(32, 24, 32, 16)

    complete_label = QLabel("安装已完成!")
    l3.addWidget(complete_label)

    l3.addWidget(QLabel(
        "您可以通过以下方式启动程序:\n"
        "  - 开始菜单 → TrafficFlow Analyzer\n"
        "  - 桌面快捷方式\n"
        "  - 直接运行安装目录下的 desktop_app.py\n\n"
        "首次运行时程序会自动下载 YOLO 模型文件。"
    ))
    l3.addSpacing(12)

    launch_cb = QCheckBox("立即启动 TrafficFlow Analyzer")
    launch_cb.setChecked(True)
    l3.addWidget(launch_cb)
    l3.addStretch()
    stack.addWidget(p3)

    # ═══════════════════════════════════════
    # 后台安装线程
    # ═══════════════════════════════════════
    class InstallWorker(QThread):
        log_sig = pyqtSignal(str)
        prog_sig = pyqtSignal(int)
        done_sig = pyqtSignal(bool)

        def __init__(self, install_dir, do_desktop, do_startmenu):
            super().__init__()
            self.install_dir = install_dir
            self.do_desktop = do_desktop
            self.do_startmenu = do_startmenu

        def run(self):
            try:
                ok = do_install(self.install_dir, self._log, self._prog)
                if ok:
                    self._log("")
                    self._log("创建快捷方式...")
                    make_uninstaller(self.install_dir)
                    self._log(f"  卸载程序: {Path(self.install_dir) / 'uninstall.bat'}")
                    if self.do_desktop:
                        make_desktop_shortcut(self.install_dir)
                        self._log("  桌面快捷方式已创建")
                    if self.do_startmenu:
                        make_startmenu_shortcut(self.install_dir)
                        self._log("  开始菜单快捷方式已创建")
                    self._log("")
                self.done_sig.emit(ok)
            except Exception:
                import traceback
                self._log(f"错误:\n{traceback.format_exc()}")
                self.done_sig.emit(False)

        def _log(self, msg):
            self.log_sig.emit(msg)

        def _prog(self, val):
            self.prog_sig.emit(val)

    worker_ref = []
    current_page = [0]
    install_ok = [False]

    # ═══════════════════════════════════════
    # 页面导航
    # ═══════════════════════════════════════
    def show_page(idx):
        current_page[0] = idx
        stack.setCurrentIndex(idx)

        if idx == 0:
            wizard_subtitle.setText("欢迎")
            back_btn.setVisible(False)
            next_btn.setText("下一步")
            next_btn.setEnabled(True)
            cancel_btn.setVisible(True)

        elif idx == 1:
            wizard_subtitle.setText("选择安装位置")
            back_btn.setVisible(True)
            next_btn.setText("安装")
            next_btn.setStyleSheet(
                "QPushButton{background:#4CAF50; color:white; padding:6px; "
                "border-radius:4px; font-weight:bold;}"
                "QPushButton:disabled{background:#ccc;}"
            )
            next_btn.setEnabled(True)
            cancel_btn.setVisible(True)

        elif idx == 2:
            wizard_subtitle.setText("正在安装，请勿关闭窗口")
            back_btn.setVisible(False)
            next_btn.setVisible(False)
            cancel_btn.setVisible(False)
            # 启动安装
            install_dir = path_edit.text().strip()
            worker = InstallWorker(
                install_dir, desktop_cb.isChecked(), startmenu_cb.isChecked()
            )
            worker.log_sig.connect(log_view.append)
            worker.prog_sig.connect(progress.setValue)
            worker.prog_sig.connect(
                lambda v: step_label.setText(
                    f"正在安装... {v}%" if v < 100 else "安装完成!"
                )
            )
            worker.done_sig.connect(_on_install_done)
            worker_ref.append(worker)
            worker.start()
            step_label.setText("正在安装...")

        elif idx == 3:
            wizard_subtitle.setText("安装完成")
            back_btn.setVisible(False)
            next_btn.setText("完成")
            next_btn.setStyleSheet(
                "QPushButton{background:#4CAF50; color:white; padding:6px; "
                "border-radius:4px; font-weight:bold;}"
            )
            next_btn.setVisible(True)
            next_btn.setEnabled(True)
            cancel_btn.setVisible(False)

    def _on_install_done(ok):
        install_ok[0] = ok
        if ok:
            step_label.setText("安装完成!")
            # 自动跳转到完成页
            show_page(3)
        else:
            step_label.setText("安装失败!")
            step_label.setStyleSheet(
                "font-weight:bold; font-size:13px; color:#f44336;"
            )
            back_btn.setVisible(True)
            back_btn.setEnabled(True)
            next_btn.setText("重试")
            next_btn.setVisible(True)
            next_btn.setEnabled(True)
            cancel_btn.setVisible(True)
            cancel_btn.setEnabled(True)

    def on_next():
        idx = current_page[0]
        if idx == 0:
            show_page(1)
        elif idx == 1:
            # 检查路径
            p = path_edit.text().strip()
            if not p:
                return
            show_page(2)
        elif idx == 2:
            # 重试
            log_view.clear()
            progress.setValue(0)
            worker = InstallWorker(
                path_edit.text().strip(), desktop_cb.isChecked(), startmenu_cb.isChecked()
            )
            worker.log_sig.connect(log_view.append)
            worker.prog_sig.connect(progress.setValue)
            worker.prog_sig.connect(
                lambda v: step_label.setText(
                    f"正在安装... {v}%" if v < 100 else "安装完成!"
                )
            )
            worker.done_sig.connect(_on_install_done)
            worker_ref.append(worker)
            worker.start()
            step_label.setText("正在安装...")
            step_label.setStyleSheet("font-weight:bold; font-size:13px;")
            back_btn.setVisible(False)
            next_btn.setVisible(False)
            cancel_btn.setVisible(False)
        elif idx == 3:
            # 完成 → 启动应用并关闭窗口
            if install_ok[0] and launch_cb.isChecked():
                launch_app(path_edit.text().strip())
            dlg.close()

    def on_back():
        idx = current_page[0]
        if idx == 1:
            show_page(0)

    def on_cancel():
        dlg.close()

    next_btn.clicked.connect(on_next)
    back_btn.clicked.connect(on_back)
    cancel_btn.clicked.connect(on_cancel)

    # 初始显示欢迎页
    show_page(0)

    dlg.show()
    app.exec()


def main():
    if is_installed(str(DEFAULT_DIR)):
        launch_app(str(DEFAULT_DIR))
    else:
        run_wizard()


if __name__ == "__main__":
    main()
