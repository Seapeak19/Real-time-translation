@echo off
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [ERROR] Virtualenv .venv not found.
    echo         Run first:  python scripts\bootstrap_dev.py
    pause
    exit /b 1
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
rem Disable unrelated Qt logging noise for a tray-only app
set QT_LOGGING_RULES=qt.qpa.*=false

start "" "%PY%" -m fanyi %*
exit /b 0
