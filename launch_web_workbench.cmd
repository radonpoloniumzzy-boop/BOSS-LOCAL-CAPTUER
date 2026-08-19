@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title 启动网页工作台

if not exist ".venv\Scripts\pythonw.exe" (
  echo 缺少网页工作台运行环境，请先运行 setup_web_workbench.cmd 完成初始化。
  pause
  exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "launch_web_workbench.py"
exit /b 0
