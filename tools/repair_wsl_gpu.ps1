param(
    [switch]$WithShutdown
)

$ErrorActionPreference = "Continue"

function Get-RepoRoot {
    try {
        return (Resolve-Path (Join-Path $PSScriptRoot "..")).ToString()
    } catch {
        return (Get-Location).ToString()
    }
}

function Write-Log {
    param([string]$Path, [string]$Event, [object]$Data)
    try {
        $payload = @{
            ts_utc = (Get-Date).ToUniversalTime().ToString("s")
            event = $Event
            data = $Data
        }
        Add-Content -Path $Path -Value ($payload | ConvertTo-Json -Compress)
    } catch {
        return
    }
}

$repoRoot = Get-RepoRoot
$logDir = Join-Path $repoRoot "artifacts\\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$stamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
$logPath = Join-Path $logDir "wsl_gpu_fix_$stamp.jsonl"
Write-Host "GPU fix log: $logPath"

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

if ($WithShutdown) {
    Write-Host "WARNING: This will shut down all running WSL instances."
    Write-Host "Shutting down WSL..."
    & $wslExe --shutdown 2>&1 | Out-Null
    Write-Log -Path $logPath -Event "wsl.shutdown" -Data @{ invoked = $true }
} else {
    Write-Host "Skipping WSL shutdown (use -WithShutdown to force)."
    Write-Log -Path $logPath -Event "wsl.shutdown" -Data @{ invoked = $false }
}

Write-Host "Updating WSL..."
$updateOut = & $wslExe --update 2>&1
Write-Log -Path $logPath -Event "wsl.update" -Data @{ output = ($updateOut | Out-String).Trim() }

Write-Host "Checking WSL GPU libraries..."
$libList = & $wslExe -e bash -lc "ls -l /usr/lib/wsl/lib | grep -i nvidia" 2>&1
Write-Log -Path $logPath -Event "wsl.libs" -Data @{ output = ($libList | Out-String).Trim() }

Write-Host "Checking WSL nvidia-smi..."
$nvsmi = & $wslExe -e /usr/lib/wsl/lib/nvidia-smi 2>&1
Write-Log -Path $logPath -Event "wsl.nvidia_smi" -Data @{ output = ($nvsmi | Out-String).Trim() }

Write-Host "Done. Review log: $logPath"
exit 0
