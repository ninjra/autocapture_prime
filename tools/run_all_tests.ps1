# Run the full local test + invariant suite on Windows in one command.
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$env:PYTHONPATH = $repoRoot

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
    param([string[]]$PyArgs)
    $cmd = @($pythonExe) + $pythonPrefix + $PyArgs
    Write-Host ("Running: " + ($cmd -join " "))
    & $pythonExe @pythonPrefix @PyArgs
    if ($LASTEXITCODE -ne 0) {
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
    Write-Host "Installing dependencies..."
    Ensure-Pip
    Invoke-EnsureDeps
    if (-not (Test-Module "cryptography")) {
        Write-Error "Dependency install did not succeed (cryptography still missing)."
        exit 1
    }
}

Invoke-Python @("-m", "autocapture_nx", "doctor")
Invoke-Python @("-m", "autocapture_nx", "--safe-mode", "doctor")
Invoke-Python @("-m", "unittest", "tests/test_blueprint_spec_validation.py", "-q")
Invoke-Python @("-m", "unittest", "discover", "-s", "tests", "-q")

Write-Host "OK: all tests and invariants passed"
