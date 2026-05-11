@echo off
chcp 65001 >nul
title TrafficFlow Analyzer - 环境安装
echo ============================================
echo   TrafficFlow Analyzer v1.0.0 环境安装
echo ============================================
echo.

:: 检查 conda
where conda >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 conda, 请先安装 Miniconda/Anaconda
    echo 下载: https://docs.conda.io/en/latest/miniconda.html
    pause
    exit /b 1
)

:: 创建环境
set ENV_NAME=yolovenv
call conda info --envs 2>nul | findstr /C:"%ENV_NAME%" >nul
if %errorlevel% neq 0 (
    echo [1/3] 创建 conda 环境: %ENV_NAME%
    call conda create -n %ENV_NAME% python=3.10 -y
) else (
    echo [1/3] conda 环境已存在: %ENV_NAME%
)

:: 安装依赖
echo [2/3] 安装 Python 依赖...
call conda run -n %ENV_NAME% pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121 -q
call conda run -n %ENV_NAME% pip install ultralytics opencv-python numpy scipy matplotlib pyyaml gradio pyqt6 -q

:: 验证
echo [3/3] 验证安装...
call conda run -n %ENV_NAME% python -c "import torch; print('PyTorch', torch.__version__, 'CUDA:', torch.cuda.is_available()); import cv2; print('OpenCV', cv2.__version__); from ultralytics import YOLO; print('Ultralytics OK')"

if %errorlevel% neq 0 (
    echo [错误] 安装验证失败
    pause
    exit /b 1
)

echo.
echo ============================================
echo   安装完成!
echo.
echo   启动 Web 版:     python gui_app.py
echo   启动桌面版:      python desktop_app.py
echo   命令行:          python main.py --help
echo ============================================
pause
