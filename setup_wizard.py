"""
TrafficFlow Analyzer v1.0.0 — Windows 安装向导

打包为单文件 exe 后，用户双击即可安装。
首次运行：显示安装向导 → 安装完成自动打开应用。
已安装后：直接启动应用。
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
        desktop = Path.home() / "Desktop"
        app = Path(install_dir) / "desktop_app.py"
        lnk = f"{desktop}\\TrafficFlow Analyzer.lnk"
        # 先删除旧快捷方式
        if Path(lnk).exists():
            Path(lnk).unlink()
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
        lnk = f"{sm}\\TrafficFlow Analyzer.lnk"
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

echo.
echo 删除快捷方式...
del /q "%USERPROFILE%\\Desktop\\TrafficFlow Analyzer.lnk" 2>nul
rmdir /s /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\TrafficFlow Analyzer" 2>nul

echo 删除 Conda 环境...
"{install_dir / "miniconda" / "Scripts" / "conda.exe"}" env remove -n {ENV_NAME} -y 2>nul

echo 删除安装目录...
cd /d "%USERPROFILE%"
rmdir /s /q "{install_dir}" 2>nul

echo.
echo 卸载完成! 部分残留文件需手动清理。
pause
""")


def do_install(install_dir, log_func, prog_func):
    d = Path(install_dir)
    d.mkdir(parents=True, exist_ok=True)
    conda = str(d / "miniconda" / "Scripts" / "conda.exe")

    # 1. Miniconda (离线，内嵌在 bundle 中)
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

    # 3. Conda 环境
    log_func(f"[3/6] 创建 Python 3.10 环境 '{ENV_NAME}' ...")
    run(f'"{conda}" create -n {ENV_NAME} python=3.10 -y')
    prog_func(50)

    # 4. PyTorch (在线下载 ~2GB)
    log_func("[4/6] 下载安装 PyTorch + CUDA 12.1 (~2GB) ...")
    result = run(
        f'"{conda}" run -n {ENV_NAME} pip install torch torchvision '
        f'--index-url https://download.pytorch.org/whl/cu121 -q'
    )
    if result.returncode != 0:
        log_func(f"PyTorch 安装失败: {result.stderr}")
        return False
    prog_func(70)

    # 5. AI 库 + GUI
    log_func("[5/6] 安装 ultralytics + OpenCV + PyQt6 ...")
    result = run(
        f'"{conda}" run -n {ENV_NAME} pip install '
        f'ultralytics opencv-python numpy scipy matplotlib pyyaml pyqt6 -q'
    )
    if result.returncode != 0:
        log_func(f"依赖安装失败: {result.stderr}")
        return False
    prog_func(90)

    # 6. 验证 + 快捷方式
    log_func("[6/6] 验证安装 ...")
    result = run(
        f'"{conda}" run -n {ENV_NAME} python -c '
        f'"import torch; print(\'CUDA:\', torch.cuda.is_available()); '
        f'import cv2; from ultralytics import YOLO; print(\'OK\')"'
    )
    log_func(f"  {result.stdout.strip() or 'OK'}")
    make_uninstaller(install_dir)
    prog_func(100)
    log_func("")
    log_func("=" * 50)
    log_func("安装完成!")
    log_func(f"应用程序: {d / 'desktop_app.py'}")
    log_func(f"卸载程序: {d / 'uninstall.bat'}")
    log_func("=" * 50)
    return True


def run_wizard():
    """显示专业安装向导"""
    from PyQt6.QtWidgets import (
        QApplication, QWizard, QWizardPage, QVBoxLayout, QHBoxLayout,
        QLabel, QProgressBar, QTextEdit, QCheckBox, QLineEdit,
        QPushButton, QFileDialog, QMessageBox,
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    wiz = QWizard()
    wiz.setWindowTitle("TrafficFlow Analyzer v1.0.0 安装向导")
    wiz.setWizardStyle(QWizard.WizardStyle.ModernStyle)
    wiz.setMinimumSize(560, 450)
    wiz.setOption(QWizard.WizardOption.NoCancelButtonOnLastPage, True)

    # ═══════════════════════════════════════════
    # Page 0: 欢迎页
    # ═══════════════════════════════════════════
    p0 = QWizardPage()
    p0.setTitle("欢迎使用 TrafficFlow Analyzer v1.0.0")
    p0.setSubTitle("交通路口车辆检测 / 跟踪 / 计数系统")
    l0 = QVBoxLayout(p0)
    info = QLabel(
        "本安装向导将指导您完成以下安装:\n\n"
        "  • Miniconda Python 3.10 环境\n"
        "  • PyTorch + CUDA 12.1 GPU 加速\n"
        "  • YOLO11 目标检测模型 (n/s/m/l/x)\n"
        "  • 车辆多目标跟踪 (ByteTrack)\n"
        "  • 交通流统计分析 & 可视化\n\n"
        "系统要求:\n"
        "  • Windows 10/11 64-bit\n"
        "  • NVIDIA 显卡 (推荐 8GB+ 显存)\n"
        "  • 约 10GB 磁盘空间\n"
        "  • 联网下载 PyTorch (~2GB)\n\n"
        "点击「下一步」继续。"
    )
    info.setWordWrap(True)
    l0.addWidget(info)
    wiz.addPage(p0)

    # ═══════════════════════════════════════════
    # Page 1: 安装路径
    # ═══════════════════════════════════════════
    p1 = QWizardPage()
    p1.setTitle("选择安装位置")
    p1.setSubTitle("选择 TrafficFlow Analyzer 的安装目录。")
    l1 = QVBoxLayout(p1)

    l1.addWidget(QLabel("安装路径:"))
    path_row = QHBoxLayout()
    path_edit = QLineEdit(str(DEFAULT_DIR))
    path_edit.setMinimumHeight(30)
    path_row.addWidget(path_edit)
    browse_btn = QPushButton("浏览...")
    browse_btn.setFixedWidth(80)

    def browse():
        d = QFileDialog.getExistingDirectory(wiz, "选择安装目录", str(DEFAULT_DIR))
        if d:
            path_edit.setText(d)
    browse_btn.clicked.connect(browse)
    path_row.addWidget(browse_btn)
    l1.addLayout(path_row)

    l1.addSpacing(12)

    disk_label = QLabel("")
    l1.addWidget(disk_label)

    def update_disk():
        try:
            import shutil as sh
            p = Path(path_edit.text())
            # 找到对应盘符
            drive = p.drive or "C:\\"
            usage = sh.disk_usage(drive)
            free_gb = usage.free / (1024 ** 3)
            disk_label.setText(f"可用磁盘空间: {free_gb:.1f} GB  (需要约 10 GB)")
            disk_label.setStyleSheet("color:#888;")
            if free_gb < 10:
                disk_label.setStyleSheet("color:#f44336;")
        except Exception:
            disk_label.setText("")

    path_edit.textChanged.connect(update_disk)
    update_disk()

    l1.addSpacing(12)
    desktop_cb = QCheckBox("创建桌面快捷方式")
    desktop_cb.setChecked(True)
    l1.addWidget(desktop_cb)

    startmenu_cb = QCheckBox("创建开始菜单文件夹")
    startmenu_cb.setChecked(True)
    l1.addWidget(startmenu_cb)

    l1.addStretch()
    p1.setLayout(l1)

    # 保存 install_dir 到 wizard 属性
    wiz.setProperty("path_edit", path_edit)
    wiz.setProperty("desktop_cb", desktop_cb)
    wiz.setProperty("startmenu_cb", startmenu_cb)
    wiz.addPage(p1)

    # ═══════════════════════════════════════════
    # Page 2: 安装进度
    # ═══════════════════════════════════════════
    p2 = QWizardPage()
    p2.setTitle("正在安装")
    p2.setSubTitle("请稍候，正在安装 TrafficFlow Analyzer...")
    p2.setCommitPage(True)
    l2 = QVBoxLayout(p2)

    step_label = QLabel("准备中...")
    step_label.setStyleSheet("font-weight:bold; font-size:13px;")
    l2.addWidget(step_label)

    progress = QProgressBar()
    progress.setTextVisible(True)
    l2.addWidget(progress)

    l2.addWidget(QLabel("安装日志:"))
    log_view = QTextEdit()
    log_view.setReadOnly(True)
    log_view.setStyleSheet(
        "QTextEdit{background:#1a1a1a; color:#ddd; "
        "font-family:Consolas; font-size:12px;}"
    )
    l2.addWidget(log_view)

    p2.setLayout(l2)

    wiz.setProperty("step_label", step_label)
    wiz.setProperty("progress", progress)
    wiz.setProperty("log_view", log_view)
    wiz.addPage(p2)

    # ═══════════════════════════════════════════
    # Page 3: 完成
    # ═══════════════════════════════════════════
    p3 = QWizardPage()
    p3.setTitle("安装完成")
    p3.setSubTitle("TrafficFlow Analyzer 已成功安装到您的计算机。")
    l3 = QVBoxLayout(p3)

    complete_label = QLabel(
        "安装已完成!\n\n"
        "您可以通过以下方式启动程序:\n"
        "  • 开始菜单 → TrafficFlow Analyzer\n"
        "  • 桌面快捷方式\n"
        "  • 或直接运行安装目录下的 desktop_app.py\n\n"
        "首次运行时程序会自动下载 YOLO 模型文件。"
    )
    complete_label.setWordWrap(True)
    l3.addWidget(complete_label)

    l3.addSpacing(12)
    launch_cb = QCheckBox("立即启动 TrafficFlow Analyzer")
    launch_cb.setChecked(True)
    l3.addWidget(launch_cb)
    l3.addStretch()
    p3.setLayout(l3)
    wiz.setProperty("launch_cb", launch_cb)
    wiz.addPage(p3)

    # ═══════════════════════════════════════════
    # 安装 Worker (后台线程)
    # ═══════════════════════════════════════════
    class InstallWorker(QThread):
        log_sig = pyqtSignal(str)
        prog_sig = pyqtSignal(int)
        done_sig = pyqtSignal(bool)

        def __init__(self, install_dir, _desktop, _startmenu):
            super().__init__()
            self.install_dir = install_dir
            self.do_desktop = _desktop
            self.do_startmenu = _startmenu

        def run(self):
            try:
                ok = do_install(self.install_dir, self._log, self._prog)
                if ok:
                    self._log("")
                    self._log("创建快捷方式...")
                    if self.do_desktop:
                        make_desktop_shortcut(self.install_dir)
                        self._log("  桌面快捷方式已创建")
                    if self.do_startmenu:
                        make_startmenu_shortcut(self.install_dir)
                        self._log("  开始菜单快捷方式已创建")
                    self._log("")
                self.done_sig.emit(ok)
            except Exception as e:
                import traceback
                self._log(f"错误: {e}\n{traceback.format_exc()}")
                self.done_sig.emit(False)

        def _log(self, msg):
            self.log_sig.emit(msg)

        def _prog(self, val):
            self.prog_sig.emit(val)

    install_done = {"ok": False}

    # ── 页面切换: 进入安装页时启动 Worker ──
    def on_page_change(page_id):
        if page_id == 2:
            # 禁用"上一步"和"取消"按钮（安装中不可中断）
            wiz.button(QWizard.WizardButton.CancelButton).setEnabled(False)
            wiz.button(QWizard.WizardButton.BackButton).setEnabled(False)

            install_dir = path_edit.text().strip()
            worker = InstallWorker(install_dir, desktop_cb.isChecked(), startmenu_cb.isChecked())
            worker.log_sig.connect(log_view.append)
            worker.prog_sig.connect(progress.setValue)
            worker.prog_sig.connect(lambda v: step_label.setText(
                f"正在安装... {v}%" if v < 100 else "安装完成!"
            ))
            worker.done_sig.connect(lambda ok: _install_finished(ok))
            wiz.setProperty("worker", worker)
            worker.start()

        elif page_id == 3:
            # 完成页: 如果勾选了启动，点击 Finish 时启动
            pass

    def _install_finished(ok):
        install_done["ok"] = ok
        if ok:
            step_label.setText("安装完成!")
            wiz.button(QWizard.WizardButton.NextButton).setEnabled(True)
            wiz.next()
        else:
            step_label.setText("安装失败!")
            step_label.setStyleSheet("font-weight:bold; font-size:13px; color:#f44336;")
            wiz.button(QWizard.WizardButton.CancelButton).setEnabled(True)
            wiz.button(QWizard.WizardButton.BackButton).setEnabled(True)

    wiz.currentIdChanged.connect(on_page_change)

    # ── Finish 按钮: 启动应用 ──
    wiz.finished.connect(lambda result: _on_finish())

    def _on_finish():
        if install_done["ok"] and launch_cb.isChecked():
            launch_app(path_edit.text().strip())

    wiz.show()
    app.exec()


def main():
    # 检查默认路径是否已安装 → 直接启动
    if is_installed(str(DEFAULT_DIR)):
        launch_app(str(DEFAULT_DIR))
    else:
        run_wizard()


if __name__ == "__main__":
    main()
