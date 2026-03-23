@echo off
chcp 65001 >nul
title Reverie Link - 开发者一键启动脚本

echo ==========================================
echo       Reverie Link - 开发者启动与修复脚本
echo ==========================================
echo.

:: ==========================================
:: 第一阶段：前端检查
:: ==========================================
where npm >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未检测到 npm！请先安装 Node.js。
    pause
    exit /b
)

if exist "node_modules\" goto frontend_ready
echo [1/4] 未检测到 node_modules，正在自动安装前端依赖...
call npm install
goto check_backend

:frontend_ready
echo [1/4] 前端依赖已就绪。

:check_backend
:: ==========================================
:: 第二阶段：后端检查与构建
:: ==========================================
if exist "venv\Scripts\activate.bat" goto backend_ready

echo [2/4] 未检测到虚拟环境，正在智能配置 Python 环境...

:: 探测 py -3.10
py -3.10 --version >nul 2>nul
if %errorlevel% equ 0 goto use_py
goto use_python

:use_py
echo - 成功探测到 Python 3.10，正在创建纯净 venv...
py -3.10 -m venv venv
goto install_deps

:use_python
echo - [警告] 未探测到 py -3.10，退化使用默认 python 命令...
python -m venv venv
goto install_deps

:install_deps
echo - 正在激活环境并修补底层构建工具...
call .\venv\Scripts\activate.bat

echo - 正在锁定 pip 版本并打补丁...
python -m pip install "pip==24.0" setuptools wheel

echo - 正在安装后端依赖，包含深度学习组件，请耐心等待...
pip install -r sidecar\requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [错误] 后端依赖安装失败！请检查上方红字报错。
    pause
    exit /b
)
echo - 后端依赖安装完成！
goto start_services

:backend_ready
echo [2/4] Python 虚拟环境已就绪。

:start_services
:: ==========================================
:: 第三阶段：启动服务
:: ==========================================
echo [3/4] 正在启动 Python 后端 (FastAPI) 端口 18000...
start "Reverie Link Backend" cmd /k ".\venv\Scripts\activate.bat && cd sidecar && uvicorn main:app --reload --port 18000"

timeout /t 3 /nobreak >nul

echo [4/4] 正在唤醒 Tauri 前端界面...
echo ==========================================
echo [保持开启] 请不要关闭当前窗口和弹出的 Python 黑色窗口。
echo ==========================================
call npm run tauri dev

echo.
echo [提示] Tauri 前端已关闭。
echo 请手动关闭名为 "Reverie Link Backend" 的 Python 命令行窗口以彻底退出。
pause