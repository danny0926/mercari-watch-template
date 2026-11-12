@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  node "%~dp0pm2-local.cjs" start
  exit /b
)
if /i "%~1"=="--stop" (
  call "%~dp0stop-local.cmd"
  exit /b
)
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -X utf8 -u "%~dp0local_monitor.py" %*
) else (
  python -X utf8 -u "%~dp0local_monitor.py" %*
)
exit /b %errorlevel%
