@echo off
setlocal
cd /d "%~dp0"
node "%~dp0pm2-local.cjs" stop
exit /b %errorlevel%
