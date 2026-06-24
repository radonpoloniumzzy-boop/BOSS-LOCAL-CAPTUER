$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "未找到 .venv\\Scripts\\python.exe，请先创建虚拟环境并安装依赖。"
}

& $python -m PyInstaller `
  --noconfirm `
  --clean `
  --name BossLocalTool `
  --windowed `
  --add-data "data;data" `
  --add-data "assets;assets" `
  app.py

Write-Host "Build finished. Output is under dist\\BossLocalTool"
