param(
  [int]$DurationS = 86400,
  [int]$SmokeS = 8
)

$ErrorActionPreference = "Stop"

function Get-VenvPython([string]$Path) {
  if (-not (Test-Path $Path)) { return $null }
  try {
    $bytes = Get-Content -Path $Path -Encoding Byte -TotalCount 2
    # Windows executables start with "MZ".
    if ($bytes.Length -eq 2 -and $bytes[0] -eq 0x4D -and $bytes[1] -eq 0x5A) { return $Path }
  } catch { return $null }
  return $null
}

function Resolve-Python([string]$Root) {
  $py = Get-VenvPython (Join-Path $Root ".venv_win\\Scripts\\python.exe")
  if ($py) { return @($py) }
  $py = Get-VenvPython (Join-Path $Root ".venv\\Scripts\\python.exe")
  if ($py) { return @($py) }
  $cmd = Get-Command py -ErrorAction SilentlyContinue
  if ($cmd) { return @("py", "-3") }
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) { return @("python") }
  throw "Python not found. Install Python 3.10+ or ensure py launcher is available."
}

function Ensure-VenvWin([string]$Root) {
  $venv = Join-Path $Root ".venv_win"
  $py = Get-VenvPython (Join-Path $venv "Scripts\\python.exe")
  if ($py) { return @($py) }

  $cmd = Get-Command py -ErrorAction SilentlyContinue
  if (-not $cmd) { throw "py launcher not found; cannot auto-create .venv_win. Install Python or create a venv manually." }

  Write-Host "Creating Windows venv at $venv"
  & py -3 -m venv $venv | Out-Null

  $py = Get-VenvPython (Join-Path $venv "Scripts\\python.exe")
  if (-not $py) { throw "Failed to create .venv_win (python.exe missing)" }

  Write-Host "Installing autocapture_nx (editable) into .venv_win"
  & $py -m pip install --upgrade pip | Out-Null
  & $py -m pip install -e $Root | Out-Null
  return @($py)
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
$Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")

$env:AUTOCAPTURE_CONFIG_DIR = $env:AUTOCAPTURE_CONFIG_DIR
if (-not $env:AUTOCAPTURE_CONFIG_DIR) { $env:AUTOCAPTURE_CONFIG_DIR = (Join-Path $Root ".data\\soak\\config_$Stamp") }

$env:AUTOCAPTURE_DATA_DIR = $env:AUTOCAPTURE_DATA_DIR
if (-not $env:AUTOCAPTURE_DATA_DIR) { $env:AUTOCAPTURE_DATA_DIR = (Join-Path $Root ".data\\soak\\data_$Stamp") }

New-Item -ItemType Directory -Force -Path $env:AUTOCAPTURE_CONFIG_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $env:AUTOCAPTURE_DATA_DIR | Out-Null

# Keep the soak stable (avoid host-runner subprocess explosions during capture+ingest).
$env:OMP_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"
$env:OPENBLAS_NUM_THREADS = "1"
$env:BLIS_NUM_THREADS = "1"
$env:NUMEXPR_NUM_THREADS = "1"
$env:TOKENIZERS_PARALLELISM = "false"
$env:AUTOCAPTURE_PLUGINS_HOSTING_MODE = "inproc"
$env:AUTOCAPTURE_PLUGINS_SUBPROCESS_SPAWN_CONCURRENCY = "1"
$env:AUTOCAPTURE_PLUGINS_SUBPROCESS_MAX_HOSTS = "2"

Push-Location $Root
try {
  # Prefer a Windows venv (WSL-created venvs are not usable on Windows).
  # PowerShell unboxes single-item pipeline output to a scalar; don't index.
  $py = (Ensure-VenvWin $Root)

  # Write smoke profile (force at least one screenshot blob for validation).
  & $py "$Root\\tools\\soak\\write_user_json.py" --config-dir "$env:AUTOCAPTURE_CONFIG_DIR" --profile smoke_screenshot_ingest | Out-Null

  # Stable per-machine consent: reuse the most recently accepted consent file from prior
  # soak runs under .data/soak/ so operators don't need to re-accept for every new
  # timestamped run-scoped directory (still fail-closed by default).
  $consentDst = Join-Path $env:AUTOCAPTURE_DATA_DIR "state\\consent.capture.json"
  if (-not (Test-Path $consentDst)) {
    $consentDir = Split-Path -Parent $consentDst
    New-Item -ItemType Directory -Force -Path $consentDir | Out-Null
    $latest = Get-ChildItem -Path (Join-Path $Root ".data\\soak") -Filter "consent.capture.json" -Recurse -ErrorAction SilentlyContinue `
      | Sort-Object LastWriteTime -Descending `
      | Select-Object -First 1
    if ($latest -and (Test-Path $latest.FullName)) {
      try { Copy-Item -Force -Path $latest.FullName -Destination $consentDst | Out-Null } catch { }
    }
  }

  # Consent preflight (fail closed).
  $consent = & $py -m autocapture_nx consent status --data-dir "$env:AUTOCAPTURE_DATA_DIR" --config-dir "$env:AUTOCAPTURE_CONFIG_DIR" | Out-String
  if ($consent -match '"accepted"\s*:\s*false') {
    Write-Host "ERROR: capture consent not accepted for AUTOCAPTURE_DATA_DIR=$($env:AUTOCAPTURE_DATA_DIR)"
    Write-Host "Run:"
    Write-Host "  $py -m autocapture_nx consent accept --data-dir `"$($env:AUTOCAPTURE_DATA_DIR)`" --config-dir `"$($env:AUTOCAPTURE_CONFIG_DIR)`""
    exit 2
  }

  # Smoke run to prove capture+ingest works (does not imply dedupe behavior).
  $env:PYTHONFAULTHANDLER = "1"
  $prevEAP = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $smokeOut = & $py -m autocapture_nx run --duration-s $SmokeS --status-interval-s 1 2>&1 | Out-String
  $smokeExit = $LASTEXITCODE
  $ErrorActionPreference = $prevEAP
  if ($smokeExit -ne 0) {
    Write-Host "ERROR: autocapture_nx run failed during smoke run (exit=$LASTEXITCODE). Output:"
    Write-Host $smokeOut
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $py -m autocapture_nx status 2>&1 | Out-Host
    $ErrorActionPreference = $prevEAP
    exit 3
  }
  $prevEAP = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $evidenceOut = & $py "$Root\\tools\\soak\\check_evidence.py" --record-type evidence.capture.frame 2>&1 | Out-String
  $evidenceExit = $LASTEXITCODE
  $ErrorActionPreference = $prevEAP
  if ($evidenceOut.Trim().Length -gt 0) { Write-Host ("[smoke] evidence_check=" + $evidenceOut.Trim()) }
  if ($evidenceExit -ne 0) {
    Write-Host "ERROR: no screenshot evidence was ingested during smoke run. Ensure you are on Windows and mss/Pillow can capture the desktop."
    Write-Host "[debug] status:"
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $py -m autocapture_nx status 2>&1 | Out-Host
    Write-Host "[debug] plugins list:"
    & $py -m autocapture_nx plugins list --json 2>&1 | Out-Host
    $ErrorActionPreference = $prevEAP
    exit 3
  }

  # Switch to soak profile (dedupe back on, screenshots-only, processing disabled).
  & $py "$Root\\tools\\soak\\write_user_json.py" --config-dir "$env:AUTOCAPTURE_CONFIG_DIR" --profile soak_screenshot_only | Out-Null

  Write-Host "Capture+ingest soak running for up to $DurationS seconds. Ctrl+C to stop."
  & $py -m autocapture_nx run --duration-s $DurationS --status-interval-s 60
} finally {
  Pop-Location
}
