# Run the full local test + invariant suite on Windows in one command.
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$env:PYTHONPATH = $repoRoot

$pythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = @("python")
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = @("py", "-3")
}

if (-not $pythonCmd) {
    Write-Error "Python not found. Install Python 3.x and retry."
    exit 1
}

function Invoke-Python {
    param([string[]]$Args)
    $cmd = @($pythonCmd + $Args)
    $exe = $cmd[0]
    $exeArgs = @()
    if ($cmd.Count -gt 1) {
        $exeArgs = $cmd[1..($cmd.Count - 1)]
    }
    Write-Host ("Running: " + ($cmd -join " "))
    & $exe @exeArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Invoke-Python @("-m", "autocapture_nx", "doctor")
Invoke-Python @("-m", "autocapture_nx", "--safe-mode", "doctor")
Invoke-Python @("-m", "unittest", "tests/test_blueprint_spec_validation.py", "-q")
Invoke-Python @("-m", "unittest", "discover", "-s", "tests", "-q")

Write-Host "OK: all tests and invariants passed"
