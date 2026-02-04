param(
    [string]$RepoRoot = "D:\\projects\\autocapture_prime",
    [string]$ModelPath = "D:\\autocapture\\models\\tinyllama-1.1b-chat-v1.0",
    [int]$Port = 8000,
    [int]$TimeoutSec = 20,
    [string]$WslExe = "C:\\Windows\\System32\\wsl.exe"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Ensure-Dir {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Convert-ToWslPath {
    param([string]$Path)
    $resolved = $Path
    try {
        $resolved = (Resolve-Path $Path).ToString()
    } catch {
        $resolved = $Path
    }
    if ($resolved -match '^([A-Za-z]):\\') {
        $drive = $matches[1].ToLower()
        $rest = $resolved.Substring(2) -replace '\\', '/'
        return "/mnt/$drive$rest"
    }
    return ($resolved -replace '\\', '/')
}

$logDir = Join-Path $RepoRoot "artifacts\\logs"
Ensure-Dir -Path $logDir
$stamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
$logPath = Join-Path $logDir "vllm_probe_$stamp.log"

$probeScript = Join-Path $RepoRoot "tools\\vllm_probe.sh"
if (-not (Test-Path $probeScript)) {
    throw "Missing probe script: $probeScript"
}

$modelWsl = Convert-ToWslPath -Path $ModelPath
$scriptWsl = Convert-ToWslPath -Path $probeScript

$cmd = "bash $scriptWsl $modelWsl $Port $TimeoutSec"
$oldEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$output = & $WslExe -e bash -lc $cmd 2>&1
$exitCode = $LASTEXITCODE
$ErrorActionPreference = $oldEap
$output | Out-File -FilePath $logPath -Encoding utf8
Write-Host "Wrote: $logPath"
Write-Host "ExitCode: $exitCode"
