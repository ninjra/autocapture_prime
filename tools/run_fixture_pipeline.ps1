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
    [int]$VllmWaitSeconds = 45
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    try {
        return (Resolve-Path (Join-Path $PSScriptRoot "..")).ToString()
    } catch {
        return (Get-Location).ToString()
    }
}

function Ensure-Dir {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function New-RunLog {
    param([string]$RepoRoot)
    $logDir = Join-Path $RepoRoot "artifacts\\logs"
    Ensure-Dir -Path $logDir
    $stamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
    return (Join-Path $logDir "fixture_run_$stamp.jsonl")
}

function Write-RunLog {
    param(
        [string]$Path,
        [string]$Event,
        [hashtable]$Data
    )
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

function Get-ManifestValue {
    param(
        [object]$Manifest,
        [string]$Key
    )
    if ($null -eq $Manifest) { return $null }
    if ($Manifest -is [hashtable] -or $Manifest -is [System.Collections.IDictionary]) {
        if ($Manifest.ContainsKey($Key)) { return $Manifest[$Key] }
        foreach ($k in $Manifest.Keys) {
            if ($null -eq $k) { continue }
            if ($k.ToString().Trim().Equals($Key, [System.StringComparison]::InvariantCultureIgnoreCase)) {
                return $Manifest[$k]
            }
        }
        return $null
    }
    if ($Manifest.PSObject -and $Manifest.PSObject.Properties) {
        if ($Manifest.PSObject.Properties.Match($Key).Count -gt 0) {
            return $Manifest.$Key
        }
        foreach ($prop in $Manifest.PSObject.Properties) {
            if ($prop -and $prop.Name.Trim().Equals($Key, [System.StringComparison]::InvariantCultureIgnoreCase)) {
                return $prop.Value
            }
        }
    }
    return $null
}

function Normalize-ManifestObject {
    param([object]$Value)
    if ($null -eq $Value) { return $null }
    if ($Value -is [string] -or $Value -is [System.ValueType]) { return $Value }
    if ($Value -is [System.Collections.IDictionary]) {
        $out = @{}
        foreach ($k in $Value.Keys) {
            $out[[string]$k] = (Normalize-ManifestObject -Value $Value[$k])
        }
        return $out
    }
    if ($Value.PSObject -and $Value.PSObject.Properties.Match("Keys").Count -gt 0) {
        try {
            $out = @{}
            foreach ($k in $Value.Keys) {
                $out[[string]$k] = (Normalize-ManifestObject -Value $Value[$k])
            }
            return $out
        } catch {
            # fall through to enumerable handling
        }
    }
    if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
        $list = New-Object System.Collections.Generic.List[object]
        foreach ($item in $Value) {
            $list.Add((Normalize-ManifestObject -Value $item))
        }
        return $list.ToArray()
    }
    if ($Value.PSObject -and $Value.PSObject.Properties) {
        $out = @{}
        foreach ($prop in $Value.PSObject.Properties) {
            $out[$prop.Name] = (Normalize-ManifestObject -Value $prop.Value)
        }
        return $out
    }
    return $Value
}

function Read-JsonFile {
    param([string]$Path)
    $pyParsed = Parse-JsonWithPython -Path $Path
    if ($null -ne $pyParsed) {
        return $pyParsed
    }
    $raw = Get-Content $Path -Raw -Encoding UTF8
    try {
        return $raw | ConvertFrom-Json -AsHashtable
    } catch {
        try {
            return $raw | ConvertFrom-Json
        } catch {
            $serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer
            $serializer.MaxJsonLength = 2147483647
            return $serializer.DeserializeObject($raw)
        }
    }
}

function Parse-JsonWithPython {
    param([string]$Path)
    $py = Get-Command python -ErrorAction SilentlyContinue
    $launcher = "python"
    if (-not $py) {
        $py = Get-Command py -ErrorAction SilentlyContinue
        $launcher = "py"
    }
    if (-not $py) { return $null }
    $script = "import json; import sys; p=r'$Path'; print(json.dumps(json.load(open(p,'r',encoding='utf-8'))))"
    try {
        if ($launcher -eq "py") {
            $out = & $py.Source -3 -c $script
        } else {
            $out = & $py.Source -c $script
        }
    } catch {
        return $null
    }
    if (-not $out) { return $null }
    $outText = $out
    if ($out -is [System.Array]) {
        $outText = ($out | Out-String)
    }
    try {
        $serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer
        $serializer.MaxJsonLength = 2147483647
        return $serializer.DeserializeObject($outText)
    } catch {
        return $null
    }
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
            if ([string](Get-ManifestValue -Manifest $m -Key "id") -eq $ModelId) { return $m }
            if ([string](Get-ManifestValue -Manifest $m -Key "served_id") -eq $ModelId) { return $m }
        }
    }
    if ($PreferKind) {
        foreach ($m in $Models) {
            if ($null -eq $m) { continue }
            if ([string](Get-ManifestValue -Manifest $m -Key "kind") -eq $PreferKind -and (Get-ManifestValue -Manifest $m -Key "required")) { return $m }
        }
        foreach ($m in $Models) {
            if ($null -eq $m) { continue }
            if ([string](Get-ManifestValue -Manifest $m -Key "kind") -eq $PreferKind) { return $m }
        }
    }
    foreach ($m in $Models) {
        if ($null -eq $m) { continue }
        if (Get-ManifestValue -Manifest $m -Key "required") { return $m }
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
        if ([string](Get-ManifestValue -Manifest $entry -Key "id") -eq [string](Get-ManifestValue -Manifest $Model -Key "id")) {
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
        [int]$WaitSeconds,
        [string]$RunLogPath
    )
    if (-not (Test-Path $ManifestPath)) {
        Write-Host "ERROR: vLLM manifest not found at $ManifestPath"
        exit 2
    }
    $manifest = Normalize-ManifestObject -Value (Read-JsonFile -Path $ManifestPath)
    $vllm = Get-ManifestValue -Manifest $manifest -Key "vllm"
    if ($null -eq $vllm) {
        Write-Host "ERROR: vLLM section missing in manifest"
        Write-RunLog -Path $RunLogPath -Event "vllm.missing" -Data @{ manifest = $ManifestPath }
        exit 2
    }
    $server = Get-ManifestValue -Manifest $vllm -Key "server"
    $vllmHost = [string](Get-ManifestValue -Manifest $server -Key "host")
    $vllmPort = [int](Get-ManifestValue -Manifest $server -Key "port")
    if (-not $vllmHost) { $vllmHost = "127.0.0.1" }
    if (-not $vllmPort) { $vllmPort = 8000 }
    if ($vllmHost -ne "127.0.0.1") {
        Write-Host "ERROR: vLLM host must be 127.0.0.1 (got $vllmHost)"
        exit 2
    }
    $baseUrl = "http://$vllmHost`:$vllmPort"
    Write-RunLog -Path $RunLogPath -Event "vllm.server" -Data @{
        base_url = $baseUrl
        host = $vllmHost
        port = $vllmPort
    }
    if (Test-VllmServer -BaseUrl $baseUrl) {
        Write-Host "vLLM already running at $baseUrl"
        Write-RunLog -Path $RunLogPath -Event "vllm.already_running" -Data @{ base_url = $baseUrl }
        return
    }
    $wslCmd = Get-Command wsl.exe -ErrorAction SilentlyContinue
    $wslExe = $null
    if ($wslCmd) {
        $wslExe = $wslCmd.Source
    } else {
        $fallback = Join-Path $env:SystemRoot "System32\\wsl.exe"
        if (Test-Path $fallback) { $wslExe = $fallback }
    }
    Write-RunLog -Path $RunLogPath -Event "vllm.wsl_check" -Data @{
        found = [bool]$wslExe
        path = $wslExe
    }
    if (-not $wslExe) {
        Write-Host "ERROR: wsl.exe not available to start vLLM"
        Write-RunLog -Path $RunLogPath -Event "vllm.wsl_missing" -Data @{}
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
        Write-RunLog -Path $RunLogPath -Event "vllm.model_select_failed" -Data @{
            requested_model = $ModelId
            prefer_kind = $PreferKind
            available = ($models | ForEach-Object { [string](Get-ManifestValue -Manifest $_ -Key "id") })
        }
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
                Write-RunLog -Path $RunLogPath -Event "model_prep.start" -Data @{ manifest = $ManifestPath; root = $rootResolved }
                & $prepScript -Manifest $ManifestPath -RootDir $rootResolved -SkipVllm
                Write-RunLog -Path $RunLogPath -Event "model_prep.finish" -Data @{ exit_code = $LASTEXITCODE }
            }
        }
        if (-not (Test-Path $modelPath)) {
            Write-Host "ERROR: vLLM model path not found: $modelPath"
            Write-Host "Run model prep first: D:\\projects\\autocapture_prime\\tools\\model_prep.ps1"
            Write-RunLog -Path $RunLogPath -Event "vllm.model_missing" -Data @{ model_path = $modelPath }
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
        $engineArgs = @("--dtype", "auto", "--gpu-memory-utilization", "0.9", "--max-model-len", "2048")
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
        $check = & $wslExe -e bash -lc "command -v vllm"
        if ($LASTEXITCODE -eq 0 -and $check) { $hasVllm = $true }
    } catch {
        $hasVllm = $false
    }
    if (-not $hasVllm) {
        $vllmCmd = "python3 -m vllm.entrypoints.openai.api_server"
    }
    $launchCmd = "HF_HOME=$cacheDir TRANSFORMERS_CACHE=$cacheDir TOKENIZERS_PARALLELISM=false " +
        "$vllmCmd --host 127.0.0.1 --port $vllmPort $apiArg $servedArg $modelArg $engineArgString"

    Write-Host "Starting vLLM in WSL (model: $($target.id))"
    Write-RunLog -Path $RunLogPath -Event "vllm.start" -Data @{
        model_id = [string](Get-ManifestValue -Manifest $target -Key "id")
        served_id = $servedId
        model_path = $modelPath
        base_url = $baseUrl
        engine_args = $engineArgs
        prefer_kind = $PreferKind
    }
    Write-RunLog -Path $RunLogPath -Event "vllm.launch_cmd" -Data @{
        cmd = $launchCmd
        model_wsl = $modelWsl
        cache_dir = $cacheDir
    }
    $bashCmd = "nohup $launchCmd > /tmp/vllm_autocapture.log 2>&1 &"
    & $wslExe -e bash -lc "$bashCmd"

    $idleWindowSeconds = 30
    $startTime = Get-Date
    $deadline = $startTime.AddSeconds($WaitSeconds)
    $lastLogMtime = 0
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        $elapsed = [int]((Get-Date) - $startTime).TotalSeconds
        if (Test-VllmServer -BaseUrl $baseUrl) {
            Write-Host "vLLM is up at $baseUrl"
            Write-RunLog -Path $RunLogPath -Event "vllm.ready" -Data @{ base_url = $baseUrl; elapsed_s = $elapsed }
            return
        }
        if ($elapsed % 4 -eq 0) {
            try {
                $mtimeOut = & $wslExe -e bash -lc "stat -c %Y /tmp/vllm_autocapture.log 2>/dev/null"
                if ($LASTEXITCODE -eq 0 -and $mtimeOut) {
                    $mtime = [int64]($mtimeOut | Select-Object -First 1)
                    if ($mtime -gt $lastLogMtime) {
                        $lastLogMtime = $mtime
                        $deadline = [DateTime]::Max($deadline, (Get-Date).AddSeconds($idleWindowSeconds))
                        Write-RunLog -Path $RunLogPath -Event "vllm.log_activity" -Data @{ mtime = $mtime; elapsed_s = $elapsed }
                    }
                }
            } catch {
                Write-RunLog -Path $RunLogPath -Event "vllm.log_activity_error" -Data @{ error = $_.Exception.Message }
            }
        }
    }
    Write-Host "ERROR: vLLM failed to start (idle window elapsed)"
    Write-RunLog -Path $RunLogPath -Event "vllm.timeout" -Data @{ base_url = $baseUrl; wait_seconds = $WaitSeconds; idle_window_s = $idleWindowSeconds }
    try {
        $tail = & $wslExe -e bash -lc "tail -n 200 /tmp/vllm_autocapture.log"
        if ($tail) {
            Write-RunLog -Path $RunLogPath -Event "vllm.log_tail" -Data @{
                lines = ($tail | Out-String)
            }
        }
    } catch {
        Write-RunLog -Path $RunLogPath -Event "vllm.log_tail_error" -Data @{ error = $_.Exception.Message }
    }
    try {
        $procs = & $wslExe -e bash -lc "ps -ef | grep -i vllm | grep -v grep"
        if ($procs) {
            Write-RunLog -Path $RunLogPath -Event "vllm.ps" -Data @{
                lines = ($procs | Out-String)
            }
        }
    } catch {
        Write-RunLog -Path $RunLogPath -Event "vllm.ps_error" -Data @{ error = $_.Exception.Message }
    }
    exit 2
}

$repoRoot = Get-RepoRoot
Set-Location $repoRoot

$runLog = New-RunLog -RepoRoot $repoRoot
Write-Host "Run log: $runLog"
Write-RunLog -Path $runLog -Event "run.start" -Data @{
    manifest = $Manifest
    output_dir = $OutputDir
    config_template = $ConfigTemplate
    use_wsl = [bool]$UseWsl
    skip_model_prep = [bool]$SkipModelPrep
    skip_vllm_start = [bool]$SkipVllmStart
    vllm_model_id = $VllmModelId
    vllm_prefer_kind = $VllmPreferKind
}
$manifestLogPath = $ModelManifest
if (-not (Test-Path $manifestLogPath)) {
    $manifestLogPath = Join-Path $repoRoot $ModelManifest
}
try {
    $mm = Normalize-ManifestObject -Value (Read-JsonFile -Path $manifestLogPath)
    $mmKeys = @()
    if ($mm -is [System.Collections.IDictionary]) {
        $mmKeys = @($mm.Keys | ForEach-Object { $_.ToString() })
    } elseif ($mm.PSObject -and $mm.PSObject.Properties) {
        $mmKeys = @($mm.PSObject.Properties.Name)
    }
    $hf = Get-ManifestValue -Manifest $mm -Key "huggingface"
    $hfModels = @()
    if ($hf) { $hfModels = @((Get-ManifestValue -Manifest $hf -Key "models")) }
    $vllm = Get-ManifestValue -Manifest $mm -Key "vllm"
    $vllmModels = @()
    if ($vllm) { $vllmModels = @((Get-ManifestValue -Manifest $vllm -Key "models")) }
    Write-RunLog -Path $runLog -Event "manifest.summary" -Data @{
        path = $manifestLogPath
        keys = $mmKeys
        hf_models_count = $hfModels.Count
        vllm_models_count = $vllmModels.Count
    }
} catch {
    Write-RunLog -Path $runLog -Event "manifest.error" -Data @{ path = $manifestLogPath; error = $_.Exception.Message }
}

if (-not $SkipVllmStart) {
    $manifestPath = $ModelManifest
    if (-not (Test-Path $manifestPath)) {
        $manifestPath = Join-Path $repoRoot $ModelManifest
    }
    Start-VllmServer -ManifestPath $manifestPath -RootDir "" -RepoRoot $repoRoot -ModelId $VllmModelId -PreferKind $VllmPreferKind -WaitSeconds $VllmWaitSeconds -RunLogPath $runLog
}

if (-not $SkipModelPrep) {
    $prepScript = Join-Path $repoRoot "tools\model_prep.ps1"
    if (Test-Path $prepScript) {
        Write-RunLog -Path $runLog -Event "model_prep.start" -Data @{ manifest = $ModelManifest }
        & $prepScript -Manifest $ModelManifest
        if ($LASTEXITCODE -ne 0) {
            Write-RunLog -Path $runLog -Event "model_prep.finish" -Data @{ exit_code = $LASTEXITCODE }
            exit $LASTEXITCODE
        }
        Write-RunLog -Path $runLog -Event "model_prep.finish" -Data @{ exit_code = 0 }
    } else {
        Write-Host "WARNING: model_prep.ps1 not found, skipping model prep"
        Write-RunLog -Path $runLog -Event "model_prep.missing" -Data @{ path = $prepScript }
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
