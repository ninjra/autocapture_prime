param(
    [string]$DataDir,
    [string]$OutputDir = "artifacts\\reprocess_runs",
    [string]$ConfigTemplate = "tools\\reprocess_config_template.json",
    [string]$ModelManifest = "tools\\model_manifest.json",
    [string]$ModelRoot = "",
    [switch]$ForceIdle,
    [switch]$RunModelPrep,
    [switch]$UseWsl
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    try {
        return (Resolve-Path (Join-Path $PSScriptRoot "..")).ToString()
    } catch {
        return (Get-Location).ToString()
    }
}

function Convert-ToWslPath {
    param([string]$Path)
    $resolved = (Resolve-Path $Path).ToString()
    $out = wsl.exe wslpath -a "$resolved"
    return $out.Trim()
}

if (-not $DataDir) {
    Write-Host "ERROR: DataDir is required"
    exit 2
}

$repoRoot = Get-RepoRoot
Set-Location $repoRoot

if ($RunModelPrep) {
    $prepScript = Join-Path $repoRoot "tools\\model_prep.ps1"
    if (Test-Path $prepScript) {
        & $prepScript -Manifest $ModelManifest
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    } else {
        Write-Host "WARNING: model_prep.ps1 not found, skipping model prep"
    }
}

$argsList = @("--data-dir", $DataDir, "--output-dir", $OutputDir, "--config-template", $ConfigTemplate, "--model-manifest", $ModelManifest)
if ($ForceIdle) {
    $argsList += "--force-idle"
}
if ($ModelRoot) {
    $argsList += @("--model-root", $ModelRoot)
}

if ($UseWsl) {
    $dataWsl = Convert-ToWslPath -Path $DataDir
    $outputWsl = Convert-ToWslPath -Path (Join-Path $repoRoot $OutputDir)
    $configWsl = Convert-ToWslPath -Path (Join-Path $repoRoot $ConfigTemplate)
    $manifestWsl = Convert-ToWslPath -Path (Join-Path $repoRoot $ModelManifest)
    $wslArgs = @(
        "python3",
        (Convert-ToWslPath -Path (Join-Path $repoRoot "tools/reprocess_models.py")),
        "--data-dir", $dataWsl,
        "--output-dir", $outputWsl,
        "--config-template", $configWsl,
        "--model-manifest", $manifestWsl
    )
    if ($ForceIdle) { $wslArgs += "--force-idle" }
    if ($ModelRoot) {
        $modelRootWsl = Convert-ToWslPath -Path $ModelRoot
        $wslArgs += @("--model-root", $modelRootWsl)
    }
    & wsl.exe @wslArgs
    exit $LASTEXITCODE
}

& python (Join-Path $repoRoot "tools/reprocess_models.py") @argsList
exit $LASTEXITCODE
