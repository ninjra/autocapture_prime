param(
    [Parameter(Mandatory = $true)]
    [string]$Id,
    [string]$RootDir = "D:\\autocapture\\models",
    [switch]$ShowProgress
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).ToString()
$prepScript = Join-Path $repoRoot "tools\\model_prep.ps1"
if (-not (Test-Path $prepScript)) {
    Write-Host "ERROR: model_prep.ps1 not found at $prepScript"
    exit 2
}

& $prepScript -RootDir $RootDir -OnlyHfId $Id -ForceHf -ShowProgress:$ShowProgress
exit $LASTEXITCODE
