@echo off
chcp 65001 >nul
title Reverie Link - 开发环境启动器

echo ==========================================
echo       Reverie Link - 开发者启动脚本
echo ==========================================
echo.

:: 检查是否存在 Python 虚拟环境，如果没有则提示
if not exist "venv\Scripts\activate.bat" (
    echo [警告] 未检测到 Python 虚拟环境 (venv)！
    echo 请先在项目根目录运行: python -m venv venv
    echo 然后运行: .\venv\Scripts\activate ^& pip install -r sidecar\requirements.txt
    echo.
    pause
    exit /b
)

:: 启动 Python 后端 (sidecar/main.py，使用 uvicorn 启动 FastAPI)
echo [1/2] 正在启动 Python 后端 (FastAPI) 端口 18000...
start "Python Backend" cmd /k ".\venv\Scripts\activate && cd sidecar && uvicorn main:app --reload --port 18000"

:: 给后端 2 秒钟的时间启动
timeout /t 2 /nobreak >nul

:: 启动 Tauri 前端
echo [2/2] 正在启动 Tauri 前端 端口 17420...
echo 请保持此窗口和弹出的 Python 窗口开启。
npm run tauri dev

echo.
echo [提示] Tauri 已关闭。准备清理后台进程...
echo 请手动关闭名为 "Python Backend" 的命令行窗口。
pause