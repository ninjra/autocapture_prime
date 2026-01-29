param(
  [string]$ShortcutPath = "",
  [string]$Python = ""
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
$launcher = Join-Path $Root "ops\dev\launch_tray.ps1"
if (-not (Test-Path $launcher)) {
  Write-Error "Launcher not found: $launcher"
  exit 1
}

if (-not $ShortcutPath) {
  $ShortcutPath = Join-Path $env:USERPROFILE "Desktop\Autocapture NX.lnk"
}

$psExe = Join-Path $PSHome "powershell.exe"
if (-not (Test-Path $psExe)) {
  $psExe = "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
}

$args = "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$launcher`" -VenvPath `".venv_win`""
if ($Python) {
  $args = "$args -Python `"$Python`""
}

$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut($ShortcutPath)
$sc.TargetPath = $psExe
$sc.Arguments = $args
$sc.WorkingDirectory = $Root
$sc.IconLocation = "$psExe,0"
$sc.Save()

Write-Host "Shortcut created: $ShortcutPath"
Write-Host "Target: $psExe $args"
