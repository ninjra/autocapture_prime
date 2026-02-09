param(
  [int]$DurationS = 86400,
  [int]$SmokeS = 8
)

$ErrorActionPreference = "Stop"

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
  # Write smoke profile (force at least one screenshot blob for validation).
  & "$Root\\.venv\\Scripts\\python.exe" "$Root\\tools\\soak\\write_user_json.py" --config-dir "$env:AUTOCAPTURE_CONFIG_DIR" --profile smoke_screenshot_ingest | Out-Null

  # Consent preflight (fail closed).
  $consent = & "$Root\\.venv\\Scripts\\python.exe" -m autocapture_nx consent status --data-dir "$env:AUTOCAPTURE_DATA_DIR" --config-dir "$env:AUTOCAPTURE_CONFIG_DIR" | Out-String
  if ($consent -match '"accepted"\s*:\s*false') {
    Write-Host "ERROR: capture consent not accepted for AUTOCAPTURE_DATA_DIR=$($env:AUTOCAPTURE_DATA_DIR)"
    Write-Host "Run:"
    Write-Host "  $Root\\.venv\\Scripts\\python.exe -m autocapture_nx consent accept --data-dir `"$($env:AUTOCAPTURE_DATA_DIR)`" --config-dir `"$($env:AUTOCAPTURE_CONFIG_DIR)`""
    exit 2
  }

  # Smoke run to prove capture+ingest works (does not imply dedupe behavior).
  & "$Root\\.venv\\Scripts\\python.exe" -m autocapture_nx run --duration-s $SmokeS --status-interval-s 0 | Out-Null
  $hasEvidence = & "$Root\\.venv\\Scripts\\python.exe" "$Root\\tools\\soak\\check_evidence.py" --record-type evidence.capture.frame
  if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: no screenshot evidence was ingested during smoke run. Are you running on Windows with capture enabled?"
    exit 3
  }

  # Switch to soak profile (dedupe back on, screenshots-only, processing disabled).
  & "$Root\\.venv\\Scripts\\python.exe" "$Root\\tools\\soak\\write_user_json.py" --config-dir "$env:AUTOCAPTURE_CONFIG_DIR" --profile soak_screenshot_only | Out-Null

  Write-Host "Capture+ingest soak running for up to $DurationS seconds. Ctrl+C to stop."
  & "$Root\\.venv\\Scripts\\python.exe" -m autocapture_nx run --duration-s $DurationS --status-interval-s 60
} finally {
  Pop-Location
}

