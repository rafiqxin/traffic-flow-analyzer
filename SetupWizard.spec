# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

# SPECPATH 是 spec 文件所在目录，由 PyInstaller 提供
BUNDLE_DIR = str(Path(SPECPATH).parent / "bundle")

a = Analysis(
    ['setup_wizard.py'],
    pathex=[],
    binaries=[],
    datas=[
        (BUNDLE_DIR, 'bundle'),
    ],
    hiddenimports=[
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch',
        'torchvision',
        'ultralytics',
        'cv2',
        'opencv-python',
        'numpy',
        'scipy',
        'matplotlib',
        'pandas',
        'yaml',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    exclude_binaries=False,
    name='TrafficFlowAnalyzer_Setup_v1.0.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
