param(
  [int]$DurationSeconds = 86400,
  [int]$StatusIntervalSeconds = 30,
  [string]$Python = "",
  [string]$DataDir = ""
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
$devDir = Join-Path $Root ".dev"
$logDir = Join-Path $devDir "logs"
if (-not (Test-Path $logDir)) { New-Item -Path $logDir -ItemType Directory -Force | Out-Null }

if (-not $DataDir) { $DataDir = $env:AUTOCAPTURE_DATA_DIR }
if (-not $DataDir) { $DataDir = "D:\\autocapture" }
$env:AUTOCAPTURE_DATA_DIR = $DataDir
if (-not (Test-Path $DataDir)) { New-Item -Path $DataDir -ItemType Directory -Force | Out-Null }

function Resolve-PythonExe {
  param([string]$Explicit)
  if ($Explicit) {
    if (-not (Test-Path $Explicit)) { throw "Python not found: $Explicit" }
    return (Resolve-Path $Explicit).Path
  }
  if ($env:AUTOCAPTURE_PYTHON_EXE -and (Test-Path $env:AUTOCAPTURE_PYTHON_EXE)) {
    return (Resolve-Path $env:AUTOCAPTURE_PYTHON_EXE).Path
  }
  $candidates = @(
    (Join-Path $Root ".venv_win311\\Scripts\\python.exe"),
    (Join-Path $Root ".venv_win310\\Scripts\\python.exe"),
    (Join-Path $Root ".venv_win\\Scripts\\python.exe"),
    (Join-Path $Root ".venv\\Scripts\\python.exe")
  )
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) { return (Resolve-Path $candidate).Path }
  }
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Path }
  throw "Python not found. Pass -Python or set AUTOCAPTURE_PYTHON_EXE."
}

$pythonExe = Resolve-PythonExe -Explicit $Python

$ts = (Get-Date).ToString("yyyyMMdd_HHmmss")
$logPath = Join-Path $logDir ("soak_screenshot_{0}.log" -f $ts)

Write-Host ("Repo: {0}" -f $Root)
Write-Host ("Python: {0}" -f $pythonExe)
Write-Host ("DataDir: {0}" -f $DataDir)
Write-Host ("DurationSeconds: {0}" -f $DurationSeconds)
Write-Host ("StatusIntervalSeconds: {0}" -f $StatusIntervalSeconds)
Write-Host ("Log: {0}" -f $logPath)

Push-Location $Root
try {
  & $pythonExe -m autocapture_nx.cli run --duration-s $DurationSeconds --status-interval-s $StatusIntervalSeconds 2>&1 | Tee-Object -FilePath $logPath
} finally {
  Pop-Location
}

