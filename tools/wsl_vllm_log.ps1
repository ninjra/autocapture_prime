param(
    [string]$WslExe = "C:\Windows\System32\wsl.exe",
    [string]$OutDir = "D:\projects\autocapture_prime\artifacts\logs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (!(Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
}

$timestamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
$outPath = Join-Path $OutDir "vllm_wsl_${timestamp}.log"

$cmd = "if [ -f /tmp/vllm_autocapture.log ]; then tail -n 400 /tmp/vllm_autocapture.log; else echo 'missing:/tmp/vllm_autocapture.log'; fi"
$output = & $WslExe --% -e bash -lc "$cmd" 2>&1
$output | Out-File -FilePath $outPath -Encoding utf8
Write-Host "Wrote: $outPath"
