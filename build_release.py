"""
Release 打包脚本 — 生成 GitHub Release 用的 zip
用法: python build_release.py
"""
import zipfile
import os
from pathlib import Path

ROOT = Path(__file__).parent
VERSION = "1.0.0"
NAME = f"traffic-flow-analyzer-v{VERSION}"

EXCLUDE = {
    "__pycache__", ".git", ".vscode", ".idea",
    "output", "*.mp4", "*.avi", "*.pt",
    "_test*.py", "build_release.py",
}

INCLUDE = [
    "README.md", "LICENSE", ".gitignore",
    "pyproject.toml", "requirements.txt",
    "setup.bat", "run.bat",
    "main.py", "gui_app.py", "desktop_app.py",
    "pipeline.py", "calibrate_roi.py",
    "config/model_config.yaml", "config/camera_roi.yaml",
    "src/__init__.py", "src/detector.py", "src/tracker.py",
    "src/roi_filter.py", "src/visualizer.py", "src/data_processor.py",
]


def should_exclude(path_parts):
    import fnmatch
    for part in path_parts:
        if part.startswith("_") or part.endswith(".pyc"):
            return True
        for pat in EXCLUDE:
            if fnmatch.fnmatch(part, pat):
                return True
    return False


def build():
    out_path = ROOT.parent / f"{NAME}.zip"
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(ROOT.rglob("*")):
            if f.is_dir():
                continue
            rel = f.relative_to(ROOT)
            parts = rel.parts
            if should_exclude(parts):
                continue
            zf.write(f, f"{NAME}/{rel}")
            print(f"  + {NAME}/{rel}")

    size_mb = os.path.getsize(out_path) / (1024 * 1024)
    print(f"\n  Release zip: {out_path} ({size_mb:.1f} MB)")
    return out_path


if __name__ == "__main__":
    build()
