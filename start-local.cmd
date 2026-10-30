@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -u "%~dp0local_monitor.py" %*
) else (
  python -u "%~dp0local_monitor.py" %*
)
if errorlevel 1 pause
