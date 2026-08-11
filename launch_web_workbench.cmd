@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title ???????

if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "launch_web_workbench.py"
  exit /b 0
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "launch_web_workbench.py"
  exit /b %errorlevel%
)

echo ??????????????????????
pause
exit /b 1
