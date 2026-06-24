$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Boss Local Capture Tool.lnk"
$targetPath = Join-Path $env:SystemRoot "System32\wscript.exe"
$scriptPath = Join-Path $root "launch_boss_local_tool.vbs"
$iconPath = Join-Path $root ".venv\Scripts\pythonw.exe"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.Arguments = '"' + $scriptPath + '"'
$shortcut.WorkingDirectory = $root
if (Test-Path $iconPath) {
    $shortcut.IconLocation = $iconPath
}
$shortcut.Description = "Double-click to launch Boss Local Capture Tool"
$shortcut.Save()

Write-Host "Desktop shortcut created:" $shortcutPath
