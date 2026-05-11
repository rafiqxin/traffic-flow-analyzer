"""
TrafficFlow Analyzer — Windows 安装向导
双击运行，自动配置环境并安装
"""
import sys
import os
import subprocess
import tempfile
import zipfile
import shutil
import urllib.request
from pathlib import Path

try:
    from PyQt6.QtWidgets import (
        QApplication, QWizard, QWizardPage, QVBoxLayout, QLabel,
        QProgressBar, QTextEdit, QCheckBox, QLineEdit, QMessageBox,
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal
except ImportError:
    print("PyQt6 required. Installing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyqt6", "-q"])
    from PyQt6.QtWidgets import (
        QApplication, QWizard, QWizardPage, QVBoxLayout, QLabel,
        QProgressBar, QTextEdit, QCheckBox, QLineEdit, QMessageBox,
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal

MINICONDA_URL = "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe"
REPO_URL = "https://github.com/rafiqxin/traffic-flow-analyzer/archive/refs/heads/master.zip"
DEFAULT_DIR = str(Path.home() / "TrafficFlowAnalyzer")


class InstallWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)

    def __init__(self, install_dir, create_desktop):
        super().__init__()
        self.install_dir = install_dir
        self.create_desktop = create_desktop

    def log(self, msg):
        self.log_signal.emit(msg)

    def run(self):
        try:
            installdir = Path(self.install_dir)
            installdir.mkdir(parents=True, exist_ok=True)

            # Step 1: Check conda
            self.log("检查 conda...")
            conda_exe = shutil.which("conda")
            if not conda_exe:
                conda_exe = str(installdir / "miniconda" / "Scripts" / "conda.exe")
            if not Path(conda_exe).exists():
                self.log("安装 Miniconda (约需2分钟)...")
                self._install_miniconda(installdir)
            else:
                self.log(f"conda: {conda_exe}")
            self.progress_signal.emit(20)

            # Step 2: Download source or use bundled
            self.log("准备源码...")
            src_dir = installdir / "traffic-flow-analyzer"
            if (src_dir / "gui_app.py").exists():
                self.log("源码已存在, 更新中...")
            else:
                self._download_source(src_dir)
            self.progress_signal.emit(30)

            # Step 3: Create conda env
            env_name = "yolovenv"
            conda_path = str(installdir / "miniconda" / "Scripts" / "conda.exe")
            if not Path(conda_path).exists():
                conda_path = "conda"

            self.log("创建 conda 环境 (约需5分钟)...")
            subprocess.run(
                f'"{conda_path}" create -n {env_name} python=3.10 -y',
                shell=True, capture_output=True, cwd=str(installdir)
            )
            self.progress_signal.emit(50)

            self.log("安装 PyTorch + CUDA (约需5分钟)...")
            subprocess.run(
                f'"{conda_path}" run -n {env_name} pip install torch torchvision '
                f'--index-url https://download.pytorch.org/whl/cu121 -q',
                shell=True, capture_output=True, cwd=str(installdir)
            )
            self.progress_signal.emit(70)

            self.log("安装 Python 依赖...")
            subprocess.run(
                f'"{conda_path}" run -n {env_name} pip install '
                f'ultralytics opencv-python numpy scipy matplotlib pyyaml gradio pyqt6 -q',
                shell=True, capture_output=True, cwd=str(installdir)
            )
            self.progress_signal.emit(90)

            # Verify
            self.log("验证安装...")
            result = subprocess.run(
                f'"{conda_path}" run -n {env_name} python -c '
                f'"import torch; print(\'CUDA:\', torch.cuda.is_available()); '
                f'import cv2; from ultralytics import YOLO; print(\'OK\')"',
                shell=True, capture_output=True, text=True, cwd=str(src_dir)
            )
            self.log(result.stdout.strip())
            self.progress_signal.emit(95)

            # Create shortcuts
            if self.create_desktop:
                self._create_shortcuts(installdir, src_dir, conda_path, env_name)

            self.progress_signal.emit(100)
            self.log("安装完成!")
            self.log(f"安装目录: {installdir}")
            self.log(f"启动桌面版: {src_dir / 'desktop_app.py'}")
            self.log(f"启动 Web 版: {src_dir / 'gui_app.py'}")

        except Exception as e:
            self.log(f"错误: {e}")
            import traceback
            self.log(traceback.format_exc())

    def _install_miniconda(self, installdir):
        mcdir = installdir / "miniconda"
        installer = installdir / "miniconda_installer.exe"
        if not installer.exists():
            self.log("下载 Miniconda...")
            urllib.request.urlretrieve(MINICONDA_URL, installer)
        self.log("安装 Miniconda (静默)...")
        subprocess.run(
            f'"{installer}" /InstallationType=JustMe /RegisterPython=0 /S '
            f'/D={mcdir}',
            shell=True, capture_output=True
        )
        try:
            installer.unlink()
        except Exception:
            pass

    def _download_source(self, src_dir):
        self.log("下载源码...")
        zip_path = src_dir.parent / "source.zip"
        urllib.request.urlretrieve(REPO_URL, zip_path)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(src_dir.parent)
        extracted = src_dir.parent / "traffic-flow-analyzer-master"
        if extracted.exists():
            if src_dir.exists():
                shutil.rmtree(src_dir)
            shutil.move(str(extracted), str(src_dir))
        zip_path.unlink()

    def _create_shortcuts(self, installdir, src_dir, conda_path, env_name):
        try:
            desktop = Path.home() / "Desktop"
            ps = f'''
$WS = New-Object -ComObject WScript.Shell
$SC = $WS.CreateShortcut("{desktop}\\TrafficFlow Analyzer.lnk")
$SC.TargetPath = "{conda_path}"
$SC.Arguments = "run -n {env_name} python {src_dir / 'desktop_app.py'}"
$SC.WorkingDirectory = "{src_dir}"
$SC.IconLocation = "shell32.dll,15"
$SC.Save()
'''
            subprocess.run(["powershell", "-Command", ps], capture_output=True)
            self.log("桌面快捷方式已创建")
        except Exception as e:
            self.log(f"快捷方式创建失败: {e}")


class InstallWizard(QWizard):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TrafficFlow Analyzer 安装向导")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(560, 420)

        self._page1 = self._create_welcome_page()
        self._page2 = self._create_install_page()
        self.addPage(self._page1)
        self.addPage(self._page2)

    def _create_welcome_page(self):
        page = QWizardPage()
        page.setTitle("欢迎使用 TrafficFlow Analyzer")
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(
            "本向导将安装交通流检测系统及其依赖。\n\n"
            "需要:\n"
            "  • Windows 10/11 64位\n"
            "  • NVIDIA GPU (推荐 8GB+ VRAM)\n"
            "  • 约 10GB 磁盘空间\n"
            "  • 网络连接 (下载约 3GB)\n\n"
            "安装时间: 约 10-20 分钟"
        ))
        layout.addWidget(QLabel("安装目录:"))
        self._dir_edit = QLineEdit(DEFAULT_DIR)
        layout.addWidget(self._dir_edit)
        self._desktop_cb = QCheckBox("创建桌面快捷方式")
        self._desktop_cb.setChecked(True)
        layout.addWidget(self._desktop_cb)
        page.setLayout(layout)
        return page

    def _create_install_page(self):
        page = QWizardPage()
        page.setTitle("正在安装")
        page.setCommitPage(True)
        layout = QVBoxLayout(page)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        layout.addWidget(self._log)
        self._progress = QProgressBar()
        layout.addWidget(self._progress)
        page.setLayout(layout)
        return page

    def initializePage(self, current_id):
        if current_id == 1:  # Install page
            self.button(QWizard.WizardButton.BackButton).setEnabled(False)
            self.button(QWizard.WizardButton.NextButton).setEnabled(False)
            self.button(QWizard.WizardButton.CancelButton).setEnabled(False)

            self._worker = InstallWorker(
                self._dir_edit.text(),
                self._desktop_cb.isChecked()
            )
            self._worker.log_signal.connect(self._log.append)
            self._worker.progress_signal.connect(self._progress.setValue)
            self._worker.finished.connect(self._on_finished)
            self._worker.start()

    def _on_finished(self):
        self._log.append("\n安装完成! 点击完成退出。")
        self.button(QWizard.WizardButton.NextButton).setEnabled(True)
        self.button(QWizard.WizardButton.CancelButton).setEnabled(True)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 检查是否已安装(有 conda env), 直接启动
    wizard = InstallWizard()
    wizard.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
