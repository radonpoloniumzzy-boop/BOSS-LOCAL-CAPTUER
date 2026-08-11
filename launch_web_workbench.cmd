@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title 启动网页工作台

if not exist ".venv\Scripts\pythonw.exe" (
  echo 缺少本地运行环境，请重新安装完整项目后再试。
  pause
  exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "launch_web_workbench.py"
exit /b 0
