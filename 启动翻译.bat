@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [错误] 没有找到虚拟环境 .venv
    echo         请先执行:  python scripts\bootstrap_dev.py
    pause
    exit /b 1
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
rem 让未捕获异常直接写日志文件，避免托盘程序静默崩溃
set QT_LOGGING_RULES=qt.qpa.*=false

start "" "%PY%" -m fanyi %*
exit /b 0
