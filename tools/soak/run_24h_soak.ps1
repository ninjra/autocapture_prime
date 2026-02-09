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

$LogDir = Join-Path $env:AUTOCAPTURE_DATA_DIR "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir ("soak_" + $Stamp + ".log")

function Write-Log([string]$Text) {
  try { Add-Content -Path $LogPath -Value $Text -Encoding UTF8 } catch { }
}

Write-Log ("=== autocapture soak start ts_utc=" + $Stamp + " ===")
Write-Log ("root=" + $Root)
Write-Log ("config_dir=" + $env:AUTOCAPTURE_CONFIG_DIR)
Write-Log ("data_dir=" + $env:AUTOCAPTURE_DATA_DIR)

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
  Write-Log "=== write_user_json smoke_screenshot_ingest ==="
  & $py "$Root\\tools\\soak\\write_user_json.py" --config-dir "$env:AUTOCAPTURE_CONFIG_DIR" --profile smoke_screenshot_ingest 2>&1 `
    | Out-File -FilePath $LogPath -Append -Encoding utf8

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
  Write-Log "=== consent status ==="
  $consent = & $py -m autocapture_nx consent status --data-dir "$env:AUTOCAPTURE_DATA_DIR" --config-dir "$env:AUTOCAPTURE_CONFIG_DIR" 2>&1 | Out-String
  Write-Log $consent
  if ($consent -match '"accepted"\s*:\s*false') {
    $cmd = "$py -m autocapture_nx consent accept --data-dir `"$($env:AUTOCAPTURE_DATA_DIR)`" --config-dir `"$($env:AUTOCAPTURE_CONFIG_DIR)`""
    Write-Log "ERROR: capture consent not accepted"
    Write-Log ("consent_accept_cmd=" + $cmd)
    Write-Host ("ERROR: capture consent not accepted. log=" + $LogPath)
    Write-Host "Run:"
    Write-Host ("  " + $cmd)
    exit 2
  }

  # Smoke run to prove capture+ingest works (does not imply dedupe behavior).
  $env:PYTHONFAULTHANDLER = "1"
  $prevEAP = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  Write-Log "=== smoke run autocapture_nx run ==="
  $smokeOut = & $py -m autocapture_nx run --duration-s $SmokeS --status-interval-s 1 2>&1 | Out-String
  $smokeExit = $LASTEXITCODE
  $ErrorActionPreference = $prevEAP
  Write-Log $smokeOut
  if ($smokeExit -ne 0) {
    Write-Log ("ERROR: smoke run failed exit=" + $smokeExit)
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    Write-Log "=== debug status ==="
    & $py -m autocapture_nx status 2>&1 | Out-File -FilePath $LogPath -Append -Encoding utf8
    Write-Log "=== debug plugins load-report ==="
    & $py -m autocapture_nx plugins load-report 2>&1 | Out-File -FilePath $LogPath -Append -Encoding utf8
    $ErrorActionPreference = $prevEAP
    Write-Host ("ERROR: smoke run failed (exit=" + $smokeExit + "). log=" + $LogPath)
    exit 3
  }
  $prevEAP = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  Write-Log "=== smoke evidence check ==="
  $evidenceOut = & $py "$Root\\tools\\soak\\check_evidence.py" --record-type evidence.capture.frame 2>&1 | Out-String
  $evidenceExit = $LASTEXITCODE
  $ErrorActionPreference = $prevEAP
  Write-Log $evidenceOut
  if ($evidenceOut.Trim().Length -gt 0) { Write-Host ("[smoke] evidence_check=" + $evidenceOut.Trim()) }
  if ($evidenceExit -ne 0) {
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    Write-Log "ERROR: no screenshot evidence ingested during smoke run"
    Write-Log "=== debug status ==="
    & $py -m autocapture_nx status 2>&1 | Out-File -FilePath $LogPath -Append -Encoding utf8
    Write-Log "=== debug plugins list ==="
    & $py -m autocapture_nx plugins list --json 2>&1 | Out-File -FilePath $LogPath -Append -Encoding utf8
    $ErrorActionPreference = $prevEAP
    Write-Host ("ERROR: no screenshot evidence ingested during smoke run. log=" + $LogPath)
    exit 3
  }

  # Switch to soak profile (dedupe back on, screenshots-only, processing disabled).
  Write-Log "=== write_user_json soak_screenshot_only ==="
  & $py "$Root\\tools\\soak\\write_user_json.py" --config-dir "$env:AUTOCAPTURE_CONFIG_DIR" --profile soak_screenshot_only 2>&1 `
    | Out-File -FilePath $LogPath -Append -Encoding utf8

  Write-Host ("OK: capture+ingest soak starting. log=" + $LogPath)
  Write-Log ("=== soak run start duration_s=" + $DurationS + " ===")
  & $py -m autocapture_nx run --duration-s $DurationS --status-interval-s 60 2>&1 `
    | Out-File -FilePath $LogPath -Append -Encoding utf8
} finally {
  Pop-Location
}
