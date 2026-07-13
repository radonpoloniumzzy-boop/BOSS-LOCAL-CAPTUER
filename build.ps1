$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python was not found under .venv\Scripts."
}

& $python -m PyInstaller `
  --noconfirm `
  --clean `
  --name BossLocalTool `
  --windowed `
  --add-data "assets;assets" `
  app.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

Write-Host "Build finished. Output is under dist\BossLocalTool"
