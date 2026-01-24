# Run the full local test + invariant suite on Windows in one command.
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$env:PYTHONPATH = $repoRoot

$logPath = Join-Path $repoRoot "tools\\run_all_tests.log"
$reportPath = Join-Path $repoRoot "tools\\run_all_tests_report.json"
New-Item -ItemType File -Path $logPath -Force | Out-Null

function Write-Log {
    param([string]$Message)
    $timestamp = (Get-Date).ToString("s")
    $line = "[$timestamp] $Message"
    $line | Tee-Object -FilePath $logPath -Append | Out-Host
}

function Write-Report {
    param(
        [string]$Status,
        [string]$Step,
        [int]$ExitCode
    )
    $tail = @()
    if (Test-Path $logPath) {
        $tail = Get-Content $logPath -Tail 60
    }
    $report = [ordered]@{
        status = $Status
        failed_step = $Step
        exit_code = $ExitCode
        python = $pythonExe
        timestamp_utc = (Get-Date).ToUniversalTime().ToString("s") + "Z"
        log_path = $logPath
        tail = $tail
    }
    $report | ConvertTo-Json -Depth 5 | Set-Content -Path $reportPath -Encoding UTF8
    Write-Host ("REPORT: status={0} failed_step={1} exit_code={2} log_path={3}" -f $Status, $Step, $ExitCode, $logPath)
}

$bootstrapExe = $null
$bootstrapPrefix = @()
if (Get-Command python -ErrorAction SilentlyContinue) {
    $bootstrapExe = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $bootstrapExe = "py"
    $bootstrapPrefix = @("-3")
}

if (-not $bootstrapExe) {
    Write-Error "Python not found. Install Python 3.x and retry."
    exit 1
}

$venvPath = Join-Path $repoRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating venv at $venvPath"
    & $bootstrapExe @bootstrapPrefix "-m" "venv" $venvPath
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$pythonExe = $venvPython
$pythonPrefix = @()

function Invoke-EnsureDeps {
    $wheelhouse = $env:AUTO_CAPTURE_WHEELHOUSE
    if (-not $wheelhouse) {
        $candidate = Join-Path $repoRoot "wheels"
        if (Test-Path $candidate) { $wheelhouse = $candidate }
    }
    $allowNetwork = $env:AUTO_CAPTURE_ALLOW_NETWORK
    if (-not $allowNetwork) { $allowNetwork = "1" }

    $extra = $env:AUTO_CAPTURE_EXTRAS
    $target = "."
    if ($extra) { $target = ".[{0}]" -f $extra }
    $pipArgs = @("-m", "pip", "install", "-e", $target)
    if ($wheelhouse) {
        Write-Host "Using wheelhouse: $wheelhouse"
        $pipArgs = @("-m", "pip", "install", "-e", ".", "--no-index", "--find-links", $wheelhouse)
    } elseif ($allowNetwork -ne "1") {
        Write-Error "Missing dependencies and no wheelhouse found. Set AUTO_CAPTURE_WHEELHOUSE to a folder of wheels or set AUTO_CAPTURE_ALLOW_NETWORK=1 to allow pip downloads."
        exit 1
    }
    & $pythonExe @pipArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Invoke-Python {
    param([string]$Step, [string[]]$PyArgs)
    $cmd = @($pythonExe) + $pythonPrefix + $PyArgs
    Write-Log ("Running: " + ($cmd -join " "))
    & $pythonExe @pythonPrefix @PyArgs 2>&1 | Tee-Object -FilePath $logPath -Append | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Report -Status "failed" -Step $Step -ExitCode $LASTEXITCODE
        Write-Log ("FAILED: " + $Step + " (code " + $LASTEXITCODE + ")")
        Write-Log ("See " + $logPath + " and " + $reportPath)
        exit $LASTEXITCODE
    }
}

function Ensure-Pip {
    & $pythonExe "-m" "ensurepip" "--upgrade" | Out-Null
    & $pythonExe "-m" "pip" "install" "--upgrade" "pip" "setuptools" "wheel"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Test-Module {
    param([string]$ModuleName)
    & $pythonExe "-c" "import $ModuleName" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

$needInstall = -not (Test-Module "cryptography")

if ($needInstall) {
    Write-Log "Installing dependencies..."
    Ensure-Pip
    Invoke-EnsureDeps
    if (-not (Test-Module "cryptography")) {
        Write-Report -Status "failed" -Step "deps" -ExitCode 2
        Write-Log "Dependency install did not succeed (cryptography still missing)."
        exit 1
    }
}

Invoke-Python -Step "doctor" -PyArgs @("-m", "autocapture_nx", "doctor")
Invoke-Python -Step "doctor_safe_mode" -PyArgs @("-m", "autocapture_nx", "--safe-mode", "doctor")
Invoke-Python -Step "spec_gate" -PyArgs @("-m", "unittest", "tests/test_blueprint_spec_validation.py", "-q")
Invoke-Python -Step "tests" -PyArgs @("-m", "unittest", "discover", "-s", "tests", "-q")

Write-Report -Status "ok" -Step "complete" -ExitCode 0
Write-Log "OK: all tests and invariants passed"
