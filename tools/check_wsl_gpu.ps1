param()

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
$logPath = Join-Path $logDir "wsl_gpu_$stamp.jsonl"
Write-Host "GPU log: $logPath"

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

$winSmi = Join-Path $env:SystemRoot "System32\\nvidia-smi.exe"
if (Test-Path $winSmi) {
    $winOut = & $winSmi 2>&1
    Write-Log -Path $logPath -Event "windows.nvidia_smi" -Data @{ output = ($winOut | Out-String).Trim() }
} else {
    Write-Log -Path $logPath -Event "windows.nvidia_smi" -Data @{ output = "not_found" }
}

$wslStatus = & $wslExe --status 2>&1
Write-Log -Path $logPath -Event "wsl.status" -Data @{ output = ($wslStatus | Out-String).Trim() }

$wslList = & $wslExe -l -v 2>&1
Write-Log -Path $logPath -Event "wsl.list" -Data @{ output = ($wslList | Out-String).Trim() }

$uname = & $wslExe -e bash -lc "uname -a" 2>&1
Write-Log -Path $logPath -Event "wsl.uname" -Data @{ output = ($uname | Out-String).Trim() }

$dxg = & $wslExe -e bash -lc "ls -l /dev/dxg" 2>&1
Write-Log -Path $logPath -Event "wsl.dxg" -Data @{ output = ($dxg | Out-String).Trim() }

$nvsmi = & $wslExe -e bash -lc "nvidia-smi -L" 2>&1
Write-Log -Path $logPath -Event "wsl.nvidia_smi" -Data @{ output = ($nvsmi | Out-String).Trim() }

$lsmod = & $wslExe -e bash -lc "lsmod | grep -i nvidia" 2>&1
Write-Log -Path $logPath -Event "wsl.lsmod" -Data @{ output = ($lsmod | Out-String).Trim() }

$procVer = & $wslExe -e bash -lc "cat /proc/version" 2>&1
Write-Log -Path $logPath -Event "wsl.proc_version" -Data @{ output = ($procVer | Out-String).Trim() }

Write-Host "Done. Review log: $logPath"
exit 0
