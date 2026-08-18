@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title 初始化网页工作台

where py >nul 2>nul
if errorlevel 1 (
  echo 未检测到官方 CPython 3.12，请先从 python.org 安装 Python 3.12，并确保 py -3.12 可用。
  pause
  exit /b 1
)

py -3.12 -V >nul 2>nul
if errorlevel 1 (
  echo 未检测到官方 CPython 3.12，请先从 python.org 安装 Python 3.12，并确保 py -3.12 可用。
  pause
  exit /b 1
)

py -3.12 "setup_web_workbench.py"
set "SETUP_EXIT=%ERRORLEVEL%"
pause
exit /b %SETUP_EXIT%
