param(
    [string]$PipArgs = "",
    [string]$VenvDir = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    try {
        return (Resolve-Path (Join-Path $PSScriptRoot "..")).ToString()
    } catch {
        return (Get-Location).ToString()
    }
}

$repoRoot = Get-RepoRoot
$logDir = Join-Path $repoRoot "artifacts\\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$stamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
$logPath = Join-Path $logDir "vllm_install_$stamp.jsonl"
Write-Host "Install log: $logPath"

function Write-Log {
    param([string]$Event, [hashtable]$Data)
    try {
        $payload = @{
            ts_utc = (Get-Date).ToUniversalTime().ToString("s")
            event = $Event
            data = $Data
        }
        Add-Content -Path $logPath -Value ($payload | ConvertTo-Json -Compress)
    } catch {
        return
    }
}

$wslCmd = Get-Command wsl.exe -ErrorAction SilentlyContinue
$wslExe = $null
if ($wslCmd) {
    $wslExe = $wslCmd.Source
} else {
    $fallback = Join-Path $env:SystemRoot "System32\\wsl.exe"
    if (Test-Path $fallback) { $wslExe = $fallback }
}
if (-not $wslExe) {
    Write-Host "ERROR: wsl.exe not available"
    exit 2
}

$pipExtra = $PipArgs.Trim()
$venv = $VenvDir
if (-not $venv) {
    $wslHome = & $wslExe -e bash -lc "eval echo ~"
    $wslHome = ($wslHome | Out-String).Trim()
    if (-not $wslHome -or -not ($wslHome.StartsWith("/") -and $wslHome -notmatch ":")) {
        $wslUser = & $wslExe -e bash -lc "whoami"
        $wslUser = ($wslUser | Out-String).Trim()
        if ($wslUser) {
            $wslHome = "/home/$wslUser"
        } else {
            $wslHome = "/home"
        }
    }
    $venv = "$wslHome/.venvs/vllm"
}
$pythonBin = "$venv/bin/python"
$pipCmd = if ($pipExtra) { "$pythonBin -m pip install -U vllm $pipExtra" } else { "$pythonBin -m pip install -U vllm" }

if (-not $Force) {
    $venvExists = $false
    $importOk = $false
    try {
        & $wslExe -e bash -lc "test -x $pythonBin"
        if ($LASTEXITCODE -eq 0) { $venvExists = $true }
    } catch {
        $venvExists = $false
    }
    if ($venvExists) {
        try {
            & $wslExe -e bash -lc "$pythonBin -c 'import vllm; print(getattr(vllm, \"__version__\", \"\"))'" 2>&1
            if ($LASTEXITCODE -eq 0) { $importOk = $true }
        } catch {
            $importOk = $false
        }
    }
    if ($venvExists -and $importOk) {
        Write-Host "vLLM already installed in WSL venv; skipping install."
        Write-Log -Event "install.skip" -Data @{ venv = $venv; reason = "import_ok" }
        exit 0
    }
}

Write-Host "Installing vLLM in WSL venv..."
Write-Log -Event "install.venv" -Data @{ venv = $venv }

& $wslExe -e bash -lc "python3 -m venv $venv"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: venv creation failed (python3-venv may be missing)"
    Write-Log -Event "install.venv_error" -Data @{ exit_code = $LASTEXITCODE }
    exit 2
}

& $wslExe -e bash -lc "$pythonBin -m pip install -U pip"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pip bootstrap failed in venv"
    Write-Log -Event "install.pip_error" -Data @{ exit_code = $LASTEXITCODE }
    exit 2
}

Write-Log -Event "install.cmd" -Data @{ cmd = $pipCmd }
& $wslExe -e bash -lc "$pipCmd"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: vLLM install failed"
    Write-Log -Event "install.error" -Data @{ exit_code = $LASTEXITCODE }
    exit 2
}

Write-Host "vLLM install complete"
Write-Log -Event "install.ok" -Data @{}
exit 0
