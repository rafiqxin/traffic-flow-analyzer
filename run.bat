@echo off
title 交通流检测系统
echo ========================================
echo   交通流检测系统 TrafficFlow Analyzer
echo ========================================
echo.

:: 查找 conda 环境
set YOLO_ENV=yolovenv
call conda info --envs 2>nul | findstr /C:"%YOLO_ENV%" >nul
if %errorlevel% neq 0 (
    echo [警告] 未找到 conda 环境 '%YOLO_ENV%', 使用系统 Python
    python gui_app.py
) else (
    echo [信息] 使用 conda 环境: %YOLO_ENV%
    conda run -n %YOLO_ENV% python gui_app.py
)

pause
