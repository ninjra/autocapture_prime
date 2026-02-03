param(
    [string]$Manifest = "docs\\test sample\\fixture_manifest.json",
    [string]$InputDir = "",
    [string]$OutputDir = "artifacts\\fixture_runs",
    [string]$ConfigTemplate = "tools\\fixture_config_template.json",
    [switch]$UseWsl,
    [switch]$SkipModelPrep,
    [string]$ModelManifest = "tools\\model_manifest.json",
    [switch]$ForceIdle,
    [switch]$SkipVllmStart,
    [string]$VllmModelId = "",
    [string]$VllmPreferKind = "",
    [int]$VllmWaitSeconds = 60
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

function Get-ManifestValue {
    param(
        [object]$Manifest,
        [string]$Key
    )
    if ($null -eq $Manifest) { return $null }
    if ($Manifest -is [hashtable]) {
        if ($Manifest.ContainsKey($Key)) { return $Manifest[$Key] }
        return $null
    }
    if ($Manifest.PSObject.Properties.Match($Key).Count -gt 0) {
        return $Manifest.$Key
    }
    return $null
}

function Read-JsonFile {
    param([string]$Path)
    return Get-Content $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Resolve-ModelRoot {
    param(
        [string]$RootDir,
        [object]$Manifest
    )
    $resolved = $RootDir
    if (-not $resolved) {
        $resolved = [string](Get-ManifestValue -Manifest $Manifest -Key "root_dir")
    }
    if (-not $resolved) {
        $resolved = [string](Get-ManifestValue -Manifest $Manifest -Key "rootDir")
    }
    if (-not $resolved) {
        $resolved = [string]$env:AUTOCAPTURE_MODEL_ROOT
    }
    if (-not $resolved) {
        $resolved = "D:\\autocapture\\models"
    }
    if ($resolved -match '^[A-Za-z]:$') {
        $drive = $resolved
        $manifestRoot = [string](Get-ManifestValue -Manifest $Manifest -Key "root_dir")
        if ($manifestRoot -and $manifestRoot.StartsWith($drive, [System.StringComparison]::InvariantCultureIgnoreCase)) {
            $resolved = $manifestRoot
        } else {
            $resolved = "$drive\\autocapture\\models"
        }
    }
    return $resolved
}

function Test-VllmServer {
    param([string]$BaseUrl)
    try {
        $resp = Invoke-RestMethod -Uri "$BaseUrl/v1/models" -Method Get -TimeoutSec 3
        if ($resp) { return $true }
    } catch {
        return $false
    }
    return $false
}

function Select-VllmModel {
    param(
        [object[]]$Models,
        [string]$ModelId,
        [string]$PreferKind
    )
    if ($ModelId) {
        foreach ($m in $Models) {
            if ($null -eq $m) { continue }
            if ([string]$m.id -eq $ModelId) { return $m }
            if ([string]$m.served_id -eq $ModelId) { return $m }
        }
    }
    if ($PreferKind) {
        foreach ($m in $Models) {
            if ($null -eq $m) { continue }
            if ([string]$m.kind -eq $PreferKind -and $m.required) { return $m }
        }
        foreach ($m in $Models) {
            if ($null -eq $m) { continue }
            if ([string]$m.kind -eq $PreferKind) { return $m }
        }
    }
    foreach ($m in $Models) {
        if ($null -eq $m) { continue }
        if ($m.required) { return $m }
    }
    foreach ($m in $Models) {
        if ($null -eq $m) { continue }
        return $m
    }
    return $null
}

function Resolve-ModelPath {
    param(
        [object]$Model,
        [object]$Manifest,
        [string]$RootDir
    )
    if ($null -eq $Model) { return $null }
    $subdir = [string](Get-ManifestValue -Manifest $Model -Key "subdir")
    if ($subdir) {
        return (Join-Path $RootDir $subdir)
    }
    $hf = Get-ManifestValue -Manifest $Manifest -Key "huggingface"
    $hfModels = @()
    if ($hf) { $hfModels = @((Get-ManifestValue -Manifest $hf -Key "models")) }
    foreach ($entry in $hfModels) {
        if ($null -eq $entry) { continue }
        if ([string]$entry.id -eq [string]$Model.id) {
            $hfSubdir = [string](Get-ManifestValue -Manifest $entry -Key "subdir")
            if ($hfSubdir) { return (Join-Path $RootDir $hfSubdir) }
        }
    }
    return [string]$Model.id
}

function Start-VllmServer {
    param(
        [string]$ManifestPath,
        [string]$RootDir,
        [string]$RepoRoot,
        [string]$ModelId,
        [string]$PreferKind,
        [int]$WaitSeconds
    )
    if (-not (Test-Path $ManifestPath)) {
        Write-Host "ERROR: vLLM manifest not found at $ManifestPath"
        exit 2
    }
    $manifest = Read-JsonFile -Path $ManifestPath
    $vllm = Get-ManifestValue -Manifest $manifest -Key "vllm"
    if ($null -eq $vllm) {
        Write-Host "ERROR: vLLM section missing in manifest"
        exit 2
    }
    $server = Get-ManifestValue -Manifest $vllm -Key "server"
    $host = [string](Get-ManifestValue -Manifest $server -Key "host")
    $port = [int](Get-ManifestValue -Manifest $server -Key "port")
    if (-not $host) { $host = "127.0.0.1" }
    if (-not $port) { $port = 8000 }
    if ($host -ne "127.0.0.1") {
        Write-Host "ERROR: vLLM host must be 127.0.0.1 (got $host)"
        exit 2
    }
    $baseUrl = "http://$host`:$port"
    if (Test-VllmServer -BaseUrl $baseUrl) {
        Write-Host "vLLM already running at $baseUrl"
        return
    }
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        Write-Host "ERROR: wsl.exe not available to start vLLM"
        exit 2
    }

    $models = @((Get-ManifestValue -Manifest $vllm -Key "models"))
    $flat = New-Object System.Collections.Generic.List[object]
    foreach ($entry in $models) {
        if ($null -eq $entry) { continue }
        if ($entry -is [System.Array]) { foreach ($item in $entry) { $flat.Add($item) } }
        else { $flat.Add($entry) }
    }
    $models = $flat.ToArray()
    $serve = Get-ManifestValue -Manifest $vllm -Key "serve"
    if (-not $PreferKind) {
        $PreferKind = [string](Get-ManifestValue -Manifest $serve -Key "prefer_kind")
    }
    $target = Select-VllmModel -Models $models -ModelId $ModelId -PreferKind $PreferKind
    if ($null -eq $target) {
        Write-Host "ERROR: No vLLM model available to serve"
        exit 2
    }

    $rootResolved = Resolve-ModelRoot -RootDir $RootDir -Manifest $manifest
    $modelPath = Resolve-ModelPath -Model $target -Manifest $manifest -RootDir $rootResolved
    if (-not $modelPath) {
        Write-Host "ERROR: Could not resolve vLLM model path"
        exit 2
    }
    if ($modelPath -match '^[A-Za-z]:\\' -and -not (Test-Path $modelPath)) {
        if ($RepoRoot) {
            $prepScript = Join-Path $RepoRoot "tools\\model_prep.ps1"
            if (Test-Path $prepScript) {
                Write-Host "vLLM model missing; running model prep (SkipVllm) to download..."
                & $prepScript -Manifest $ManifestPath -RootDir $rootResolved -SkipVllm
            }
        }
        if (-not (Test-Path $modelPath)) {
            Write-Host "ERROR: vLLM model path not found: $modelPath"
            Write-Host "Run model prep first: D:\\projects\\autocapture_prime\\tools\\model_prep.ps1"
            exit 2
        }
    }
    $modelWsl = $modelPath
    if ($modelPath -match '^[A-Za-z]:\\') {
        $modelWsl = Convert-ToWslPath -Path $modelPath
    }
    $cacheDir = Join-Path $rootResolved "_hf_cache"
    if ($cacheDir -match '^[A-Za-z]:\\') {
        $cacheDir = Convert-ToWslPath -Path $cacheDir
    }

    $engineArgs = @()
    if ($serve) {
        $cfgArgs = Get-ManifestValue -Manifest $serve -Key "engine_args"
        if ($cfgArgs) { $engineArgs = @($cfgArgs) }
    }
    if (-not $engineArgs -or $engineArgs.Count -eq 0) {
        $engineArgs = @("--dtype", "auto", "--gpu-memory-utilization", "0.9", "--max-model-len", "4096")
    }
    $engineArgString = ($engineArgs | ForEach-Object { $_.ToString() }) -join " "
    $servedId = [string](Get-ManifestValue -Manifest $target -Key "served_id")
    $apiKey = [string](Get-ManifestValue -Manifest $server -Key "api_key")
    $servedArg = ""
    if ($servedId) { $servedArg = "--served-model-name $servedId" }
    $apiArg = ""
    if ($apiKey) { $apiArg = "--api-key $apiKey" }
    $modelArg = "--model '$modelWsl'"

    $vllmCmd = "vllm serve"
    $hasVllm = $false
    try {
        $check = & wsl.exe -e bash -lc "command -v vllm"
        if ($LASTEXITCODE -eq 0 -and $check) { $hasVllm = $true }
    } catch {
        $hasVllm = $false
    }
    if (-not $hasVllm) {
        $vllmCmd = "python3 -m vllm.entrypoints.openai.api_server"
    }
    $launchCmd = "HF_HOME=$cacheDir TRANSFORMERS_CACHE=$cacheDir TOKENIZERS_PARALLELISM=false " +
        "$vllmCmd --host 127.0.0.1 --port $port $apiArg $servedArg $modelArg $engineArgString"

    Write-Host "Starting vLLM in WSL (model: $($target.id))"
    $bashCmd = "nohup $launchCmd > /tmp/vllm_autocapture.log 2>&1 &"
    & wsl.exe -e bash -lc "$bashCmd"

    $elapsed = 0
    while ($elapsed -lt $WaitSeconds) {
        Start-Sleep -Seconds 2
        $elapsed += 2
        if (Test-VllmServer -BaseUrl $baseUrl) {
            Write-Host "vLLM is up at $baseUrl"
            return
        }
    }
    Write-Host "ERROR: vLLM failed to start within $WaitSeconds seconds"
    exit 2
}

$repoRoot = Get-RepoRoot
Set-Location $repoRoot

if (-not $SkipVllmStart) {
    $manifestPath = $ModelManifest
    if (-not (Test-Path $manifestPath)) {
        $manifestPath = Join-Path $repoRoot $ModelManifest
    }
    Start-VllmServer -ManifestPath $manifestPath -RootDir "" -RepoRoot $repoRoot -ModelId $VllmModelId -PreferKind $VllmPreferKind -WaitSeconds $VllmWaitSeconds
}

if (-not $SkipModelPrep) {
    $prepScript = Join-Path $repoRoot "tools\model_prep.ps1"
    if (Test-Path $prepScript) {
        & $prepScript -Manifest $ModelManifest
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    } else {
        Write-Host "WARNING: model_prep.ps1 not found, skipping model prep"
    }
}

$argsList = @("--manifest", $Manifest, "--output-dir", $OutputDir, "--config-template", $ConfigTemplate)
if ($InputDir) {
    $argsList += @("--input-dir", $InputDir)
}
if ($ForceIdle) {
    $argsList += "--force-idle"
}

if ($UseWsl) {
    $manifestWsl = Convert-ToWslPath -Path (Join-Path $repoRoot $Manifest)
    $outputWsl = Convert-ToWslPath -Path (Join-Path $repoRoot $OutputDir)
    $configWsl = Convert-ToWslPath -Path (Join-Path $repoRoot $ConfigTemplate)
    $wslArgs = @("python3", (Convert-ToWslPath -Path (Join-Path $repoRoot "tools/run_fixture_pipeline.py")),
        "--manifest", $manifestWsl,
        "--output-dir", $outputWsl,
        "--config-template", $configWsl
    )
    if ($InputDir) {
        $inputWsl = Convert-ToWslPath -Path $InputDir
        $wslArgs += @("--input-dir", $inputWsl)
    }
    if ($ForceIdle) {
        $wslArgs += "--force-idle"
    }
    & wsl.exe @wslArgs
    exit $LASTEXITCODE
}

& python (Join-Path $repoRoot "tools/run_fixture_pipeline.py") @argsList
exit $LASTEXITCODE
