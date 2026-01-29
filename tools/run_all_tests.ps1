# Run the full local test + invariant suite on Windows in one command.
$ErrorActionPreference = "Stop"

$repoRoot = $null
try {
    $repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
} catch {
    $repoRoot = Split-Path -Parent $PSScriptRoot
}
if (-not $repoRoot) {
    $repoRoot = Get-Location
}
$repoRoot = $repoRoot.ToString()
Set-Location $repoRoot

$env:PYTHONPATH = $repoRoot
$testRoot = Join-Path $repoRoot ".dev\\test_env"
if (Test-Path $testRoot) {
    Remove-Item -Recurse -Force $testRoot | Out-Null
}
$env:AUTOCAPTURE_CONFIG_DIR = Join-Path $testRoot "config"
$env:AUTOCAPTURE_DATA_DIR = Join-Path $testRoot "data"
New-Item -ItemType Directory -Path $env:AUTOCAPTURE_CONFIG_DIR -Force | Out-Null
New-Item -ItemType Directory -Path $env:AUTOCAPTURE_DATA_DIR -Force | Out-Null

$logDir = Join-Path $repoRoot "tools"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logPath = Join-Path $logDir "run_all_tests.log"
$reportPath = Join-Path $logDir "run_all_tests_report.json"
Set-Content -Path $logPath -Value "" -Encoding UTF8
Write-Host "Logging to: $logPath"
Write-Host "Report to: $reportPath"

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

trap {
    Write-Log ("UNHANDLED ERROR: " + $_.Exception.Message)
    Write-Report -Status "failed" -Step "script_exception" -ExitCode 1
    break
}

$bootstrapExe = $null
$bootstrapPrefix = @()
$cmdPython = Get-Command python -ErrorAction SilentlyContinue
if ($cmdPython) {
    $path = $cmdPython.Path
    $isNonWindows = $false
    if ($path.StartsWith("/") -or $path -match "[/\\\\]usr[/\\\\]bin" -or $path -like "\\\\wsl$\\*") { $isNonWindows = $true }
    if ($path -match "WindowsApps[/\\\\]python.exe") { $isNonWindows = $true }
    if ($path -like "$repoRoot\\*\\.venv\\*\\python.exe" -or $path -like "$repoRoot\\*\\.venv_win\\*\\python.exe") { $isNonWindows = $true }
    if (-not $isNonWindows) {
        $bootstrapExe = "python"
    }
}
if (-not $bootstrapExe) {
    $cmdPy = Get-Command py -ErrorAction SilentlyContinue
    if ($cmdPy) {
        $bootstrapExe = "py"
        $bootstrapPrefix = @("-3")
    }
}

if (-not $bootstrapExe) {
    Write-Log "Python not found. Install Python 3.x and retry."
    Write-Report -Status "failed" -Step "python_missing" -ExitCode 1
    exit 1
}

function Test-PosixVenv {
    param([string]$CfgPath)
    if (Test-Path $CfgPath) {
        try {
            $cfgText = Get-Content $CfgPath -Raw
            if ($cfgText -match "home\\s*=\\s*/" -or $cfgText -match "executable\\s*=\\s*/" -or $cfgText -match "command\\s*=\\s*/") {
                return $true
            }
        } catch { }
    }
    try {
        $root = Split-Path -Parent $CfgPath
        $binDir = Join-Path $root "bin"
        if (Test-Path (Join-Path $binDir "activate")) { return $true }
        if (Test-Path (Join-Path $binDir "python")) { return $true }
    } catch { }
    return $false
}

function Validate-PythonExe {
    param([string]$ExePath)
    try {
        $out = & $ExePath "-c" "import sys; print(sys.executable)" 2>&1
        $exitCode = $LASTEXITCODE
    } catch {
        return [pscustomobject]@{ ok = $false; message = $_.Exception.Message }
    }
    if ($exitCode -ne 0) {
        return [pscustomobject]@{ ok = $false; message = ($out | Out-String).Trim() }
    }
    $text = ($out | Out-String).Trim()
    if ($text -match "No Python at" -or $text.StartsWith("/") -or $text -match "[/\\\\]usr[/\\\\]bin" -or $text -like "\\\\wsl$\\*") {
        return [pscustomobject]@{ ok = $false; message = "python resolved to non-Windows path: $text" }
    }
    return [pscustomobject]@{ ok = $true; message = $text }
}

function Ensure-VenvPython {
    param([string]$VenvRoot)
    $venvPython = Join-Path $VenvRoot "Scripts\\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host "Creating venv at $VenvRoot"
        & $bootstrapExe @bootstrapPrefix "-m" "venv" $VenvRoot
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    return $venvPython
}

$venvPath = Join-Path $repoRoot ".venv_win"
if ($env:AUTOCAPTURE_WINDOWS_VENV_PATH) {
    $venvPath = $env:AUTOCAPTURE_WINDOWS_VENV_PATH
}
if ($env:AUTOCAPTURE_ALLOW_REPO_VENV -eq "1") {
    $repoVenv = Join-Path $repoRoot ".venv"
    $repoCfg = Join-Path $repoVenv "pyvenv.cfg"
    if (-not (Test-PosixVenv $repoCfg)) {
        $venvPath = $repoVenv
    } else {
        Write-Host "WARN Repo .venv looks like WSL; staying on .venv_win."
    }
}

$venvPython = Ensure-VenvPython -VenvRoot $venvPath
$validation = Validate-PythonExe -ExePath $venvPython
if (-not $validation.ok -and ($venvPath -like "*\\.venv")) {
    Write-Host "WARN Invalid venv python ($($validation.message)). Falling back to .venv_win."
    $venvPath = Join-Path $repoRoot ".venv_win"
    $venvPython = Ensure-VenvPython -VenvRoot $venvPath
    $validation = Validate-PythonExe -ExePath $venvPython
}
if (-not $validation.ok) {
    Write-Log ("Python in venv is invalid: " + $validation.message)
    Write-Report -Status "failed" -Step "python_invalid" -ExitCode 1
    exit 1
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
        $pipArgs = @("-m", "pip", "install", "-e", $target, "--no-index", "--find-links", $wheelhouse)
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
    $output = & $pythonExe @pythonPrefix @PyArgs 2>&1
    $exitCode = $LASTEXITCODE
    $output | Tee-Object -FilePath $logPath -Append | Out-Host
    if ($exitCode -ne 0) {
        Write-Report -Status "failed" -Step $Step -ExitCode $exitCode
        Write-Log ("FAILED: " + $Step + " (code " + $exitCode + ")")
        Write-Log ("See " + $logPath + " and " + $reportPath)
        exit $exitCode
    }
}

function Invoke-Launcher {
    param([string]$Step, [string[]]$Args)
    $launcher = Join-Path $repoRoot "ops\\dev\\launch_tray.ps1"
    $cmd = @("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcher) + $Args
    Write-Log ("Running: " + ($cmd -join " "))
    $output = & $cmd[0] @($cmd[1..($cmd.Length - 1)]) 2>&1
    $exitCode = $LASTEXITCODE
    $output | Tee-Object -FilePath $logPath -Append | Out-Host
    if ($exitCode -ne 0) {
        Write-Report -Status "failed" -Step $Step -ExitCode $exitCode
        Write-Log ("FAILED: " + $Step + " (code " + $exitCode + ")")
        Write-Log ("See " + $logPath + " and " + $reportPath)
        exit $exitCode
    }
}

function Ensure-Pip {
    & $pythonExe "-m" "ensurepip" "--upgrade" | Out-Null
    & $pythonExe "-m" "pip" "install" "--upgrade" "pip" "setuptools" "wheel"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Test-Module {
    param([string]$ModuleName)
    try {
        $output = & $pythonExe "-c" "import $ModuleName" 2>&1
        $exitCode = $LASTEXITCODE
    } catch {
        Write-Log ("Module check exception (" + $ModuleName + "): " + $_.Exception.Message)
        return $false
    }
    if ($exitCode -ne 0) {
        $text = ($output | Out-String).Trim()
        if ($text) { Write-Log ("Module check failed (" + $ModuleName + "): " + $text) }
        return $false
    }
    return $true
}

$requiredModules = @("cryptography", "tzdata")
$needInstall = $false
foreach ($module in $requiredModules) {
    if (-not (Test-Module $module)) {
        $needInstall = $true
        break
    }
}

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

Invoke-Launcher -Step "tray_launcher_selftest" -Args @("-Python", $pythonExe, "-SelfTest", "-NoBootstrap")
Invoke-Launcher -Step "tray_launcher_smoketest" -Args @("-Python", $pythonExe, "-SmokeTest", "-NoBootstrap")

Invoke-Python -Step "deps_lock" -PyArgs @("tools/gate_deps_lock.py")
Invoke-Python -Step "canon_gate" -PyArgs @("tools/gate_canon.py")
Invoke-Python -Step "concurrency_gate" -PyArgs @("tools/gate_concurrency.py")
Invoke-Python -Step "ledger_gate" -PyArgs @("tools/gate_ledger.py")
Invoke-Python -Step "perf_gate" -PyArgs @("tools/gate_perf.py")
Invoke-Python -Step "security_gate" -PyArgs @("tools/gate_security.py")
Invoke-Python -Step "static_gate" -PyArgs @("tools/gate_static.py")
Invoke-Python -Step "vuln_gate" -PyArgs @("tools/gate_vuln.py")
Invoke-Python -Step "doctor_gate" -PyArgs @("tools/gate_doctor.py")
Invoke-Python -Step "doctor" -PyArgs @("-m", "autocapture_nx", "doctor")
Invoke-Python -Step "doctor_safe_mode" -PyArgs @("-m", "autocapture_nx", "--safe-mode", "doctor")
Invoke-Python -Step "spec_gate" -PyArgs @("-m", "unittest", "tests/test_blueprint_spec_validation.py", "-q")
Invoke-Python -Step "tests" -PyArgs @("-m", "unittest", "discover", "-s", "tests", "-q")

Write-Report -Status "ok" -Step "complete" -ExitCode 0
Write-Log "OK: all tests and invariants passed"
