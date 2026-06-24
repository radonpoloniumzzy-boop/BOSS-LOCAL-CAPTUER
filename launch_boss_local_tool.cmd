@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHONW=%ROOT%\.venv\Scripts\pythonw.exe"
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
set "APP=%ROOT%\app.py"

if exist "%PYTHONW%" (
  start "" "%PYTHONW%" "%APP%"
  exit /b 0
)

if exist "%PYTHON%" (
  start "" "%PYTHON%" "%APP%"
  exit /b 0
)

echo.
echo Python was not found under .venv\Scripts.
echo Please create the virtual environment and install dependencies first.
echo.
pause
