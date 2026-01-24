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

    $pipArgs = @("-m", "pip", "install", "-e", ".")
    if ($wheelhouse) {
        Write-Host "Using wheelhouse: $wheelhouse"
        $pipArgs = @("-m", "pip", "install", "-e", ".", "--no-index", "--find-links", $wheelhouse)
    } elseif (-not $allowNetwork) {
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

try {
    & $pythonExe "-c" "import cryptography" | Out-Null
} catch {
    Invoke-EnsureDeps
}

Invoke-Python @("-m", "autocapture_nx", "doctor")
Invoke-Python @("-m", "autocapture_nx", "--safe-mode", "doctor")
Invoke-Python @("-m", "unittest", "tests/test_blueprint_spec_validation.py", "-q")
Invoke-Python @("-m", "unittest", "discover", "-s", "tests", "-q")

Write-Host "OK: all tests and invariants passed"
