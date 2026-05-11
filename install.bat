@echo off
chcp 65001 >nul
title TrafficFlow Analyzer 在线安装
echo ============================================
echo   TrafficFlow Analyzer v1.0.0 在线安装
echo ============================================
echo.

:: 1. 检查 conda
where conda >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 conda, 请先安装 Miniconda
    echo 下载: https://docs.conda.io/en/latest/miniconda.html
    start https://docs.conda.io/en/latest/miniconda.html
    pause
    exit /b 1
)

:: 2. 设置安装目录
set INSTALL_DIR=%USERPROFILE%\TrafficFlowAnalyzer
echo [1/4] 安装目录: %INSTALL_DIR%

:: 3. 下载源码
echo [2/4] 下载源码...
if exist "%INSTALL_DIR%" (
    echo   目录已存在, 更新代码...
    cd /d "%INSTALL_DIR%"
    git pull 2>nul || (
        echo   更新失败, 重新下载...
        cd ..
        rmdir /s /q "%INSTALL_DIR%"
        git clone https://github.com/rafiqxin/traffic-flow-analyzer.git "%INSTALL_DIR%"
    )
) else (
    git clone https://github.com/rafiqxin/traffic-flow-analyzer.git "%INSTALL_DIR%"
    cd /d "%INSTALL_DIR%"
)

if %errorlevel% neq 0 (
    echo [错误] 下载失败, 检查网络连接
    pause
    exit /b 1
)

:: 4. 创建 conda 环境
set ENV_NAME=yolovenv
call conda info --envs 2>nul | findstr /C:"%ENV_NAME%" >nul
if %errorlevel% neq 0 (
    echo [3/4] 创建 conda 环境...
    call conda create -n %ENV_NAME% python=3.10 -y
) else (
    echo [3/4] conda 环境已存在
)

:: 5. 安装依赖
echo [4/4] 安装 Python 依赖 (需要几分钟)...
call conda run -n %ENV_NAME% pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121 -q
call conda run -n %ENV_NAME% pip install ultralytics opencv-python numpy scipy matplotlib pyyaml gradio pyqt6 -q

:: 6. 验证
call conda run -n %ENV_NAME% python -c "import torch; print('PyTorch', torch.__version__, 'CUDA:', torch.cuda.is_available()); import cv2; from ultralytics import YOLO; print('OK')"
if %errorlevel% neq 0 (
    echo [错误] 安装失败
    pause
    exit /b 1
)

:: 7. 创建启动快捷方式
echo.
echo 创建桌面快捷方式...
powershell -Command "$WS = New-Object -ComObject WScript.Shell; $SC = $WS.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\TrafficFlow Analyzer.lnk'); $SC.TargetPath = '%INSTALL_DIR%\run.bat'; $SC.WorkingDirectory = '%INSTALL_DIR%'; $SC.Save()"

echo.
echo ============================================
echo   安装完成!
echo   双击桌面 "TrafficFlow Analyzer" 启动
echo   或者运行: %INSTALL_DIR%\run.bat
echo ============================================
start "" "%INSTALL_DIR%"
pause
