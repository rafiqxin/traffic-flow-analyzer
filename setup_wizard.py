"""
TrafficFlow Analyzer — Windows 安装向导
打包为单文件 exe 后，用户双击即可安装
"""
import sys, os, subprocess, shutil, tempfile
from pathlib import Path

# 打包时 bundle/ 会被内嵌到 exe, 运行时 PyInstaller 解压到 sys._MEIPASS
if getattr(sys, 'frozen', False):
    BUNDLE = Path(sys._MEIPASS) / "bundle"
else:
    BUNDLE = Path(__file__).parent.parent / "bundle"

MINICONDA_EXE = "miniconda_installer.exe"
SRC_FILES = [
    "calibrate_roi.py", "desktop_app.py", "main.py", "pipeline.py",
    "pyproject.toml", "requirements.txt", ".gitignore",
]
SRC_DIRS = ["config", "src"]

ENV_NAME = "yolovenv"


def run(cmd, **kw):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)


class SetupWizard:
    def __init__(self):
        try:
            from PyQt6.QtWidgets import (
                QApplication, QWizard, QWizardPage, QVBoxLayout, QLabel,
                QProgressBar, QTextEdit, QCheckBox, QLineEdit,
            )
            from PyQt6.QtCore import Qt, QThread, pyqtSignal
        except ImportError:
            print("Installing PyQt6...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyqt6", "-q"])
            from PyQt6.QtWidgets import (
                QApplication, QWizard, QWizardPage, QVBoxLayout, QLabel,
                QProgressBar, QTextEdit, QCheckBox, QLineEdit,
            )
            from PyQt6.QtCore import Qt, QThread, pyqtSignal

        self.QApp = QApplication
        self.QWizard = QWizard
        self.QWizardPage = QWizardPage
        self.QVBoxLayout = QVBoxLayout
        self.QLabel = QLabel
        self.QProgressBar = QProgressBar
        self.QTextEdit = QTextEdit
        self.QCheckBox = QCheckBox
        self.QLineEdit = QLineEdit
        self.Qt = Qt
        self.QThread = QThread
        self.pyqtSignal = pyqtSignal

    def run_wizard(self):
        app = self.QApp(sys.argv)
        app.setStyle("Fusion")
        wizard = self._build_wizard()
        wizard.show()
        sys.exit(app.exec())

    def _build_wizard(self):
        Qt = self.Qt
        wiz = self.QWizard()
        wiz.setWindowTitle("TrafficFlow Analyzer v1.0.0 安装向导")
        wiz.setWizardStyle(self.QWizard.WizardStyle.ModernStyle)
        wiz.setMinimumSize(560, 440)

        # ── Page 1: Welcome ──
        p1 = self.QWizardPage()
        p1.setTitle("欢迎使用 TrafficFlow Analyzer")
        l1 = self.QVBoxLayout(p1)
        l1.addWidget(self.QLabel(
            "交通路口车辆检测/跟踪/计数系统\n\n"
            "本向导将自动安装:\n"
            "  1. Miniconda (Python 环境管理)\n"
            "  2. PyTorch + CUDA (GPU 加速)\n"
            "  3. YOLO11 + ByteTrack (检测跟踪)\n"
            "  4. 桌面应用程序\n\n"
            "系统要求: Windows 10/11, NVIDIA GPU, ~10GB 磁盘\n"
            "安装时间: 约 15-20 分钟 (需网络下载 PyTorch ~2GB)"
        ))
        l1.addWidget(self.QLabel("安装目录:"))
        self._dir_edit = self.QLineEdit(str(Path.home() / "TrafficFlowAnalyzer"))
        l1.addWidget(self._dir_edit)
        self._desktop_cb = self.QCheckBox("创建桌面快捷方式")
        self._desktop_cb.setChecked(True)
        l1.addWidget(self._desktop_cb)
        p1.setLayout(l1)
        wiz.addPage(p1)

        # ── Page 2: Install progress ──
        p2 = self.QWizardPage()
        p2.setTitle("正在安装")
        p2.setCommitPage(True)
        l2 = self.QVBoxLayout(p2)
        self._log = self.QTextEdit()
        self._log.setReadOnly(True)
        l2.addWidget(self._log)
        self._progress = self.QProgressBar()
        l2.addWidget(self._progress)
        p2.setLayout(l2)
        wiz.addPage(p2)

        # ── Install worker ──
        class Worker(self.QThread):
            log_sig = self.pyqtSignal(str)
            prog_sig = self.pyqtSignal(int)
            finished_sig = self.pyqtSignal()

            def __init__(self, install_dir, desktop):
                super().__init__()
                self.dir = install_dir
                self.desk = desktop

            def log(self, msg):
                self.log_sig.emit(msg)

            def run(self):
                try:
                    d = Path(self.dir)
                    d.mkdir(parents=True, exist_ok=True)

                    # 1. Install Miniconda from bundle
                    self.log("安装 Miniconda...")
                    mci = BUNDLE / MINICONDA_EXE
                    if not mci.exists():
                        self.log("错误: 未找到 Miniconda 安装包")
                        return
                    run(f'"{mci}" /InstallationType=JustMe /RegisterPython=0 /S /D={d / "miniconda"}')
                    self.prog_sig.emit(25)

                    # 2. Copy source
                    self.log("安装应用程序...")
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
                    self.prog_sig.emit(35)

                    # 3. Create conda env
                    conda = str(d / "miniconda" / "Scripts" / "conda.exe")
                    self.log("创建 Python 环境...")
                    run(f'"{conda}" create -n {ENV_NAME} python=3.10 -y')
                    self.prog_sig.emit(45)

                    # 4. Install PyTorch
                    self.log("安装 PyTorch + CUDA (约2GB, 需几分钟)...")
                    run(f'"{conda}" run -n {ENV_NAME} pip install torch torchvision '
                        f'--index-url https://download.pytorch.org/whl/cu121 -q')
                    self.prog_sig.emit(65)

                    # 5. Install other deps
                    self.log("安装 Python 依赖...")
                    run(f'"{conda}" run -n {ENV_NAME} pip install '
                        f'ultralytics opencv-python numpy scipy matplotlib pyyaml pyqt6 -q')
                    self.prog_sig.emit(85)

                    # 6. Verify
                    self.log("验证安装...")
                    result = run(
                        f'"{conda}" run -n {ENV_NAME} python -c '
                        f'"import torch; print(\'CUDA:\', torch.cuda.is_available()); '
                        f'import cv2; from ultralytics import YOLO; print(\'OK\')"'
                    )
                    self.log(result.stdout.strip() or "OK")
                    self.prog_sig.emit(95)

                    # 7. Shortcuts
                    if self.desk:
                        self._make_shortcut(d, conda)
                    self.prog_sig.emit(100)
                    self.log("安装完成!")
                    self.log(f"程序目录: {d}")
                    self.log(f"启动命令: {conda} run -n {ENV_NAME} python {d / 'desktop_app.py'}")
                    self.finished_sig.emit()

                except Exception as e:
                    import traceback
                    self.log(f"错误: {e}\n{traceback.format_exc()}")

            def _make_shortcut(self, d, conda):
                try:
                    desktop = Path.home() / "Desktop"
                    ps = (
                        f'$WS = New-Object -ComObject WScript.Shell; '
                        f'$SC = $WS.CreateShortcut("{desktop}\\TrafficFlow Analyzer.lnk"); '
                        f'$SC.TargetPath = "{conda}"; '
                        f'$SC.Arguments = "run -n {ENV_NAME} python {d / "desktop_app.py"}"; '
                        f'$SC.WorkingDirectory = "{d}"; '
                        f'$SC.IconLocation = "shell32.dll,15"; $SC.Save()'
                    )
                    subprocess.run(["powershell", "-Command", ps], capture_output=True)
                    self.log("桌面快捷方式已创建")
                except Exception as e:
                    self.log(f"快捷方式失败: {e}")

        self._worker = Worker(self._dir_edit.text(), self._desktop_cb.isChecked())
        self._worker.log_sig.connect(self._log.append)
        self._worker.prog_sig.connect(self._progress.setValue)
        self._worker.finished_sig.connect(lambda: (
            self._log.append("\n点击完成退出安装向导。"),
        ))

        wiz.currentIdChanged.connect(lambda cid: (
            self._worker.start() if cid == 1 else None
        ))
        return wiz


def main():
    SetupWizard().run_wizard()


if __name__ == "__main__":
    main()
