param(
    [string]$Manifest = "tools\\model_manifest.json",
    [string]$RootDir = "",
    [switch]$SkipVllm,
    [switch]$SkipHuggingFace,
    [switch]$SkipWarm,
    [switch]$AllowInstallHfCli,
    [string]$OnlyHfId = "",
    [switch]$ForceHf,
    [switch]$ShowProgress
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    try {
        return (Resolve-Path (Join-Path $PSScriptRoot "..")).ToString()
    } catch {
        return (Get-Location).ToString()
    }
}

function Write-Status {
    param(
        [string]$Level,
        [string]$Message
    )
    $stamp = (Get-Date).ToString("s")
    Write-Host "[$stamp][$Level] $Message"
}

function Ensure-Dir {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function New-PrepLog {
    param([string]$RepoRoot)
    $logDir = Join-Path $RepoRoot "artifacts\\logs"
    Ensure-Dir -Path $logDir
    $stamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
    return (Join-Path $logDir "model_prep_$stamp.jsonl")
}

function Write-PrepLog {
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

function Write-AuditEvent {
    param(
        [string]$Action,
        [string]$Outcome,
        [hashtable]$Details
    )
    try {
        $repoRoot = Resolve-RepoRoot
        $auditDir = Join-Path $repoRoot "artifacts\\audit"
        if (-not (Test-Path $auditDir)) {
            New-Item -ItemType Directory -Path $auditDir -Force | Out-Null
        }
        $payload = @{
            schema_version = 1
            ts_utc = (Get-Date).ToUniversalTime().ToString("s")
            action = $Action
            actor = "tools.model_prep"
            outcome = $Outcome
            details = $Details
        }
        $line = ($payload | ConvertTo-Json -Compress)
        Add-Content -Path (Join-Path $auditDir "audit.jsonl") -Value $line
    } catch {
        return
    }
}

function Get-DirFileHashes {
    param([string]$Path)
    $results = @()
    if (-not (Test-Path $Path)) { return $results }
    $root = (Resolve-Path $Path).ToString()
    $files = Get-ChildItem -Path $root -Recurse -File -ErrorAction SilentlyContinue
    foreach ($file in $files) {
        try {
            $hash = Get-FileHash -Path $file.FullName -Algorithm SHA256
            $rel = $file.FullName.Substring($root.Length).TrimStart("\", "/")
            $results += [pscustomobject]@{
                path = $rel
                sha256 = $hash.Hash
                size_bytes = $file.Length
            }
        } catch {
            continue
        }
    }
    return $results
}

function Read-Manifest {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw "Manifest not found: $Path"
    }
    $pyParsed = Parse-ManifestWithPython -Path $Path
    if ($null -ne $pyParsed -and -not ($pyParsed -is [string]) -and -not ($pyParsed -is [System.Array])) {
        $schema = Get-ManifestValue -Manifest $pyParsed -Key "schema_version"
        $hf = Get-ManifestValue -Manifest $pyParsed -Key "huggingface"
        $vllm = Get-ManifestValue -Manifest $pyParsed -Key "vllm"
        if ($schema -or $hf -or $vllm) {
            Write-PrepLog -Path $prepLog -Event "manifest.parse" -Data @{
                method = "python"
                type = $pyParsed.GetType().FullName
            }
            return $pyParsed
        }
        Write-PrepLog -Path $prepLog -Event "manifest.parse_error" -Data @{
            method = "python"
            error = "missing_expected_keys"
        }
    }
    $raw = Get-Content $Path -Raw -Encoding UTF8
    $parsed = Parse-ManifestRaw -Raw $raw -Path $Path
    if ($null -eq $parsed -or ($parsed -is [string]) -or ($parsed -is [System.Array])) {
        Write-PrepLog -Path $prepLog -Event "manifest.parse_error" -Data @{
            method = "powershell"
            error = "parse_failed"
        }
        throw "Manifest parse failed"
    }
    $schema = Get-ManifestValue -Manifest $parsed -Key "schema_version"
    $hf = Get-ManifestValue -Manifest $parsed -Key "huggingface"
    $vllm = Get-ManifestValue -Manifest $parsed -Key "vllm"
    if (-not ($schema -or $hf -or $vllm)) {
        Write-PrepLog -Path $prepLog -Event "manifest.parse_error" -Data @{
            method = "powershell"
            error = "missing_expected_keys"
        }
        throw "Manifest parse failed"
    }
    Write-PrepLog -Path $prepLog -Event "manifest.parse" -Data @{
        method = "powershell"
        type = $parsed.GetType().FullName
    }
    return $parsed
}

function Parse-ManifestRaw {
    param(
        [string]$Raw,
        [string]$Path
    )
    $parsed = $null
    $method = ""
    try {
        $parsed = $Raw | ConvertFrom-Json -ErrorAction Stop
        $method = "ConvertFrom-Json"
    } catch {
        try {
            $serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer
            $serializer.MaxJsonLength = 2147483647
            $parsed = $serializer.DeserializeObject($Raw)
            $method = "JavaScriptSerializer"
        } catch {
            $parsed = $Raw
            $method = "raw"
            Write-PrepLog -Path $prepLog -Event "manifest.parse_error" -Data @{
                method = "ConvertFrom-Json"
                error = $_.Exception.Message
            }
        }
    }

    $needsFallback = $false
    if ($parsed -is [string] -or $parsed -is [System.Array]) { $needsFallback = $true }
    if (-not $needsFallback) {
        $schema = Get-ManifestValue -Manifest $parsed -Key "schema_version"
        if (-not $schema -and $Raw -match '"schema_version"') { $needsFallback = $true }
    }
    if ($needsFallback) {
        $pyParsed = Parse-ManifestWithPython -Path $Path
        if ($null -ne $pyParsed) {
            $parsed = $pyParsed
            $method = "python"
        }
    }

    $typeName = ""
    if ($null -ne $parsed) { $typeName = $parsed.GetType().FullName }
    Write-PrepLog -Path $prepLog -Event "manifest.parse" -Data @{
        path = $Path
        method = $method
        type = $typeName
    }

    return $parsed
}

function Parse-ManifestWithPython {
    param([string]$Path)
    $py = Get-Command python -ErrorAction SilentlyContinue
    $launcher = "python"
    if (-not $py) {
        $py = Get-Command py -ErrorAction SilentlyContinue
        $launcher = "py"
    }
    if (-not $py) {
        Write-PrepLog -Path $prepLog -Event "manifest.parse_error" -Data @{
            method = "python"
            error = "python_not_found"
        }
        return $null
    }
    $script = "import json; import sys; p=r'$Path'; print(json.dumps(json.load(open(p,'r',encoding='utf-8'))))"
    try {
        if ($launcher -eq "py") {
            $out = & $py.Source -3 -c $script
        } else {
            $out = & $py.Source -c $script
        }
    } catch {
        Write-PrepLog -Path $prepLog -Event "manifest.parse_error" -Data @{
            method = "python"
            error = $_.Exception.Message
        }
        return $null
    }
    if (-not $out) { return $null }
    $outText = $out
    if ($out -is [System.Array]) {
        $outText = ($out | Out-String)
    }
    $prefix = $outText
    if ($prefix.Length -gt 200) { $prefix = $prefix.Substring(0, 200) }
    Write-PrepLog -Path $prepLog -Event "manifest.python_output" -Data @{
        length = $outText.Length
        prefix = $prefix
    }
    try {
        $serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer
        $serializer.MaxJsonLength = 2147483647
        return $serializer.DeserializeObject($outText)
    } catch {
        return $null
    }
}

function Try-Invoke {
    param([scriptblock]$Action)
    try {
        & $Action
        return $true
    } catch {
        return $false
    }
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

function Ensure-Vllm {
    param(
        [hashtable]$Server,
        [object[]]$Models,
        [switch]$SkipWarm,
        [string]$RootDir
    )
    $vllmHost = ""
    $vllmPort = 0
    $apiKey = ""
    if ($Server) {
        $vllmHost = [string](Get-ManifestValue -Manifest $Server -Key "host")
        $vllmPort = [int](Get-ManifestValue -Manifest $Server -Key "port")
        $apiKey = [string](Get-ManifestValue -Manifest $Server -Key "api_key")
    }
    if (-not $vllmHost) { $vllmHost = "127.0.0.1" }
    if ($vllmHost -ne "127.0.0.1") {
        Write-Status "ERROR" "vLLM host must be 127.0.0.1 (got $vllmHost)"
        return @{ ok = $false; error = "vllm_host_not_localhost" }
    }
    if (-not $vllmPort) { $vllmPort = 8000 }

    $baseUrl = "http://$vllmHost`:$vllmPort"
    $headers = @{}
    if ($apiKey) { $headers["Authorization"] = "Bearer $apiKey" }

    Write-PrepLog -Path $prepLog -Event "vllm.check" -Data @{
        base_url = $baseUrl
        root_dir = $RootDir
    }
    $serverOk = $false
    $available = @()
    try {
        $resp = Invoke-RestMethod -Uri "$baseUrl/v1/models" -Method Get -Headers $headers -TimeoutSec 4
        if ($resp) { $serverOk = $true }
    } catch {
        $serverOk = $false
    }
    if (-not $serverOk) {
        Write-Status "WARN" "vLLM server not responding on $baseUrl (will verify local model paths only)"
        Write-PrepLog -Path $prepLog -Event "vllm.server_unavailable" -Data @{ base_url = $baseUrl }
        $results = @()
        $missingRequired = $false
        foreach ($model in $Models) {
            $mid = [string](Get-ManifestValue -Manifest $model -Key "id")
            if (-not $mid) { continue }
            $servedId = $mid
            $servedIdCandidate = [string](Get-ManifestValue -Manifest $model -Key "served_id")
            if ($servedIdCandidate) { $servedId = $servedIdCandidate }
            $servedNameCandidate = [string](Get-ManifestValue -Manifest $model -Key "served_name")
            if ($servedNameCandidate) { $servedId = $servedNameCandidate }
            if (-not $servedId) { $servedId = $mid }
            $required = [bool](Get-ManifestValue -Manifest $model -Key "required")
            $subdir = [string](Get-ManifestValue -Manifest $model -Key "subdir")
            if (-not $subdir) { $subdir = ($mid -replace "[^A-Za-z0-9._-]", "_") }
            $localPath = ""
            $exists = $false
            if ($RootDir) {
                $localPath = Join-Path $RootDir $subdir
                if ((Get-ChildItem -Path $localPath -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1)) {
                    $exists = $true
                }
            }
            $status = if ($exists) { "local_only" } else { "missing" }
            $ok = $exists
            $error = if ($exists) { "server_unavailable" } else { "missing" }
            if ($required -and -not $ok) { $missingRequired = $true }
            $results += [pscustomobject]@{
                id = $mid
                served_id = $servedId
                ok = $ok
                status = $status
                required = $required
                error = $error
                local_path = $localPath
            }
        }
        return @{
            ok = (-not $missingRequired)
            error = "vllm_server_unavailable"
            base_url = $baseUrl
            local_only = $true
            results = $results
        }
    }
    if ($resp -and $resp.data) {
        foreach ($entry in $resp.data) {
            if ($entry -and $entry.id) { $available += [string]$entry.id }
        }
    }
    $availableSet = @{}
    foreach ($mid in $available) { $availableSet[$mid] = $true }

    $results = @()
    foreach ($model in $Models) {
        $mid = [string](Get-ManifestValue -Manifest $model -Key "id")
        if (-not $mid) { continue }
        $servedId = $mid
        $servedIdCandidate = [string](Get-ManifestValue -Manifest $model -Key "served_id")
        if ($servedIdCandidate) { $servedId = $servedIdCandidate }
        $servedNameCandidate = [string](Get-ManifestValue -Manifest $model -Key "served_name")
        if ($servedNameCandidate) { $servedId = $servedNameCandidate }
        if (-not $servedId) { $servedId = $mid }
        $required = [bool](Get-ManifestValue -Manifest $model -Key "required")
        $status = "missing"
        $ok = $false
        $error = "missing"
        if ($availableSet.ContainsKey($servedId)) {
            $status = "present"
            $ok = $true
            $error = $null
        }
        if ($ok -and -not $SkipWarm) {
            $payload = @{
                model = $servedId
                messages = @(@{ role = "user"; content = "warmup" })
                max_tokens = 1
                temperature = 0
            }
            try {
                Invoke-RestMethod -Uri "$baseUrl/v1/chat/completions" -Method Post -Headers $headers -Body ($payload | ConvertTo-Json -Depth 6) -ContentType "application/json" -TimeoutSec 10 | Out-Null
                $status = "present_warm"
            } catch {
                $status = "present_warm_failed"
                $ok = $false
                $error = "warm_failed"
            }
        }
        $results += [pscustomobject]@{ id = $mid; served_id = $servedId; ok = $ok; status = $status; required = $required; error = $error }
    }

    return @{ ok = $true; results = $results; base_url = $baseUrl }
}

function Ensure-HfCli {
    param([switch]$AllowInstall)
    $hf = Get-Command hf -ErrorAction SilentlyContinue
    if ($hf) { return @{ ok = $true; cmd = $hf.Source; mode = "hf" } }
    $hf = Get-Command huggingface-cli -ErrorAction SilentlyContinue
    if ($hf) { return @{ ok = $true; cmd = $hf.Source; mode = "huggingface-cli" } }
    if (-not $AllowInstall) {
        return @{ ok = $false; error = "huggingface_cli_missing" }
    }
    Write-Status "INFO" "Installing huggingface_hub (user scope)"
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        return @{ ok = $false; error = "python_missing" }
    }
    $ok = Try-Invoke { & $py.Source -m pip install --user -U huggingface_hub }
    if (-not $ok) {
        return @{ ok = $false; error = "pip_install_failed" }
    }
    $hf = Get-Command hf -ErrorAction SilentlyContinue
    if ($hf) { return @{ ok = $true; cmd = $hf.Source; mode = "hf" } }
    $hf = Get-Command huggingface-cli -ErrorAction SilentlyContinue
    if ($hf) { return @{ ok = $true; cmd = $hf.Source; mode = "huggingface-cli" } }
    return @{ ok = $false; error = "huggingface_cli_missing" }
}

function Download-HfModels {
    param(
        [object[]]$Models,
        [string]$RootDir,
        [switch]$AllowInstall,
        [switch]$ForceDownload
    )
    $cli = Ensure-HfCli -AllowInstall:$AllowInstall
    if (-not $cli.ok) {
        Write-Status "ERROR" "huggingface-cli unavailable ($($cli.error))"
        $results = @()
        foreach ($model in $Models) {
            $id = [string]$model.id
            if (-not $id) { continue }
            $required = $false
            if ($model.PSObject.Properties.Name -contains "required") {
                $required = [bool]$model.required
            }
            $results += [pscustomobject]@{ id = $id; ok = $false; status = "missing_cli"; required = $required; error = $cli.error }
        }
        return @{ ok = $false; results = $results }
    }

    $results = @()
    foreach ($model in $Models) {
        $id = [string](Get-ManifestValue -Manifest $model -Key "id")
        if (-not $id) { continue }
        $required = [bool](Get-ManifestValue -Manifest $model -Key "required")
        $subdir = [string](Get-ManifestValue -Manifest $model -Key "subdir")
        if (-not $subdir) {
            $subdir = ($id -replace "[^A-Za-z0-9._-]", "_")
        }
        $dest = Join-Path $RootDir $subdir
        Ensure-Dir -Path $dest
        if (-not $ForceDownload) {
            if ((Get-ChildItem -Path $dest -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1)) {
                $results += [pscustomobject]@{ id = $id; ok = $true; status = "present"; required = $required; error = $null; dest = $dest }
                continue
            }
        }
        $candidates = @()
        $candidateValue = Get-ManifestValue -Manifest $model -Key "candidates"
        if ($candidateValue) { $candidates = @($candidateValue) }
        if (-not $candidates -or $candidates.Count -eq 0) { $candidates = @($id) }
        $downloaded = $false
        $error = $null
        $oldPyEnc = $env:PYTHONIOENCODING
        $oldPyUtf8 = $env:PYTHONUTF8
        $oldDisableBars = $env:HF_HUB_DISABLE_PROGRESS_BARS
        $oldDisableTelemetry = $env:HF_HUB_DISABLE_TELEMETRY
        $env:PYTHONIOENCODING = "utf-8"
        $env:PYTHONUTF8 = "1"
        if ($ShowProgress) {
            $env:HF_HUB_DISABLE_PROGRESS_BARS = "0"
        } else {
            $env:HF_HUB_DISABLE_PROGRESS_BARS = "1"
        }
        $env:HF_HUB_DISABLE_TELEMETRY = "1"
        foreach ($candidate in $candidates) {
            $label = if ($cli.mode) { $cli.mode } else { "huggingface-cli" }
            Write-Status "INFO" "$label download $candidate -> $dest"
            $exitCode = 0
            $invokeError = $null
            try {
                if ($cli.mode -eq "hf") {
                    & $cli.cmd download $candidate --local-dir $dest
                } else {
                    & $cli.cmd download $candidate --local-dir $dest --local-dir-use-symlinks False
                }
                $exitCode = $LASTEXITCODE
            } catch {
                $exitCode = 1
                $invokeError = $_.Exception.Message
            }
            if ($exitCode -eq 0) {
                if ((Get-ChildItem -Path $dest -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1)) {
                    $downloaded = $true
                    $error = $null
                    break
                }
                $error = "download_empty"
            } else {
                if ($invokeError) {
                    $error = "download_failed:$invokeError"
                } else {
                    $error = "download_failed"
                }
            }
        }
        $env:PYTHONIOENCODING = $oldPyEnc
        $env:PYTHONUTF8 = $oldPyUtf8
        $env:HF_HUB_DISABLE_PROGRESS_BARS = $oldDisableBars
        $env:HF_HUB_DISABLE_TELEMETRY = $oldDisableTelemetry
        if ($downloaded) {
            $results += [pscustomobject]@{ id = $id; ok = $true; status = "downloaded"; required = $required; error = $null; dest = $dest }
        } else {
            $results += [pscustomobject]@{ id = $id; ok = $false; status = "download_failed"; required = $required; error = $error; dest = $dest }
        }
    }

    return @{ ok = $true; results = $results }
}

$repoRoot = Resolve-RepoRoot
$manifestPath = $Manifest
$manifestRooted = $false
try {
    $manifestRooted = [System.IO.Path]::IsPathRooted($manifestPath)
} catch {
    $manifestRooted = $false
}
if (-not (Test-Path $manifestPath) -and -not $manifestRooted) {
    $manifestPath = Join-Path $repoRoot $Manifest
}
Write-Status "INFO" "Using manifest path: $manifestPath"
$prepLog = New-PrepLog -RepoRoot $repoRoot
Write-Status "INFO" "Prep log: $prepLog"
$manifestRaw = Read-Manifest -Path $manifestPath
$rawType = $null
if ($manifestRaw) { $rawType = $manifestRaw.GetType().FullName }
$manifestObj = $manifestRaw
$manifestKeys = @()
if ($manifestObj -is [System.Collections.IDictionary]) {
    $manifestKeys = @($manifestObj.Keys | ForEach-Object { $_.ToString() })
} elseif ($manifestObj.PSObject -and $manifestObj.PSObject.Properties) {
    $manifestKeys = @($manifestObj.PSObject.Properties.Name)
}
$manifestType = $null
if ($manifestObj) { $manifestType = $manifestObj.GetType().FullName }
$hfSection = Get-ManifestValue -Manifest $manifestObj -Key "huggingface"
$hfModels = @()
if ($hfSection) { $hfModels = @((Get-ManifestValue -Manifest $hfSection -Key "models")) }
$vllmSection = Get-ManifestValue -Manifest $manifestObj -Key "vllm"
$vllmModels = @()
if ($vllmSection) { $vllmModels = @((Get-ManifestValue -Manifest $vllmSection -Key "models")) }
Write-PrepLog -Path $prepLog -Event "manifest.loaded" -Data @{
    manifest = $manifestPath
    keys = $manifestKeys
    hf_models_count = $hfModels.Count
    vllm_models_count = $vllmModels.Count
    type = $manifestType
    raw_type = $rawType
}
if ($manifestKeys.Count -eq 1 -and $manifestKeys[0] -eq "Length") {
    Write-PrepLog -Path $prepLog -Event "manifest.parse_error" -Data @{
        method = "post_parse"
        error = "parsed_as_string_or_array"
    }
    throw "Manifest parse failed"
}
if (-not $hfSection -and -not $vllmSection) {
    Write-PrepLog -Path $prepLog -Event "manifest.parse_error" -Data @{
        method = "post_parse"
        error = "missing_hf_and_vllm_sections"
    }
    throw "Manifest parse failed"
}
$manifestHash = ""
try {
    $manifestHash = (Get-FileHash -Path $manifestPath -Algorithm SHA256).Hash
} catch {
    $manifestHash = ""
}

    $rootDir = if ($RootDir) { $RootDir } else { [string](Get-ManifestValue -Manifest $manifestObj -Key "root_dir") }
if (-not $rootDir) {
    $rootDir = [string](Get-ManifestValue -Manifest $manifestObj -Key "rootDir")
}
if (-not $rootDir) {
    $rootDir = [string]$env:AUTOCAPTURE_MODEL_ROOT
}
if (-not $rootDir) {
    $rootDir = "D:\\autocapture\\models"
}
if ($rootDir -match '^[A-Za-z]:$') {
    $drive = $rootDir
    $manifestRoot = [string](Get-ManifestValue -Manifest $manifestObj -Key "root_dir")
    if ($manifestRoot -and $manifestRoot.StartsWith($drive, [System.StringComparison]::InvariantCultureIgnoreCase)) {
        $rootDir = $manifestRoot
    } else {
        $rootDir = "$drive\\autocapture\\models"
    }
}
if (-not $rootDir) {
    throw "Model root not specified"
}
Write-Status "INFO" "Using model root: $rootDir"
Ensure-Dir -Path $rootDir

$errors = @()
$summary = @{}

Write-AuditEvent -Action "models.prep.start" -Outcome "ok" -Details @{
    manifest = $manifestPath
    manifest_sha256 = $manifestHash
    root_dir = $rootDir
    network_permitted = $true
}

if (-not $SkipHuggingFace) {
    $hfModels = @()
    $hfSection = Get-ManifestValue -Manifest $manifestObj -Key "huggingface"
    if ($null -ne $hfSection) {
        $hfModels = @((Get-ManifestValue -Manifest $hfSection -Key "models"))
        $flat = New-Object System.Collections.Generic.List[object]
        foreach ($entry in $hfModels) {
            if ($null -eq $entry) { continue }
            if ($entry -is [System.Array]) {
                foreach ($item in $entry) { $flat.Add($item) }
            } else {
                $flat.Add($entry)
            }
        }
        $hfModels = $flat.ToArray()
    }
    if (-not $hfModels -or $hfModels.Count -eq 0) {
        Write-Status "WARN" "No HuggingFace models listed in manifest"
    }
    if ($OnlyHfId) {
        $needle = ($OnlyHfId -replace '\s+', '').Trim()
        $filtered = @()
        foreach ($entry in $hfModels) {
            if ($null -eq $entry) { continue }
            $mid = [string](Get-ManifestValue -Manifest $entry -Key "id")
            $midKey = ($mid -replace '\s+', '').Trim()
            if ($midKey -and $midKey.Equals($needle, [System.StringComparison]::InvariantCultureIgnoreCase)) {
                $filtered += $entry
            }
        }
        if ($filtered.Count -eq 0) {
            Write-Status "ERROR" "No HuggingFace model matched OnlyHfId: $OnlyHfId"
            Write-PrepLog -Path $prepLog -Event "hf.only_id.missing" -Data @{ id = $OnlyHfId }
            Write-PrepLog -Path $prepLog -Event "finish.error" -Data @{ errors = @("hf_only_id_missing") }
            exit 2
        } else {
            $hfModels = $filtered
            Write-PrepLog -Path $prepLog -Event "hf.only_id" -Data @{ id = $OnlyHfId; count = $hfModels.Count }
        }
    }
    $force = $false
    if ($ForceHf -or $OnlyHfId) { $force = $true }
    $hfResult = Download-HfModels -Models $hfModels -RootDir $rootDir -AllowInstall:$AllowInstallHfCli -ForceDownload:$force
    $summary["huggingface"] = $hfResult
    $requiredFailed = $false
    foreach ($entry in $hfResult.results) {
        if ($entry.required -and -not $entry.ok) { $requiredFailed = $true }
    }
    if ($requiredFailed) {
        $errors += "hf_required_failed"
    }
} else {
    Write-Status "INFO" "Skipping HuggingFace"
}

if (-not $SkipVllm) {
    $vllmModels = @()
    $vllmSection = Get-ManifestValue -Manifest $manifestObj -Key "vllm"
    $vllmServer = $null
    if ($null -ne $vllmSection) {
        $vllmServer = Get-ManifestValue -Manifest $vllmSection -Key "server"
        $vllmModels = @((Get-ManifestValue -Manifest $vllmSection -Key "models"))
        $flat = New-Object System.Collections.Generic.List[object]
        foreach ($entry in $vllmModels) {
            if ($null -eq $entry) { continue }
            if ($entry -is [System.Array]) {
                foreach ($item in $entry) { $flat.Add($item) }
            } else {
                $flat.Add($entry)
            }
        }
        $vllmModels = $flat.ToArray()
    }
    if (-not $vllmModels -or $vllmModels.Count -eq 0) {
        Write-Status "WARN" "No vLLM models listed in manifest"
    }
    $vllmResult = Ensure-Vllm -Server $vllmServer -Models $vllmModels -SkipWarm:$SkipWarm -RootDir $rootDir
    $summary["vllm"] = $vllmResult
    if (-not $vllmResult.ok) {
        $errors += "vllm_failed"
    }
    $requiredFailed = $false
    foreach ($entry in $vllmResult.results) {
        if ($entry.required -and -not $entry.ok) { $requiredFailed = $true }
    }
    if ($requiredFailed) {
        $errors += "vllm_required_failed"
    }
} else {
    Write-Status "INFO" "Skipping vLLM"
}

Write-Host ""
Write-Status "INFO" "Model prep summary"
Write-Host ($summary | ConvertTo-Json -Depth 6)
Write-PrepLog -Path $prepLog -Event "summary" -Data @{
    summary = $summary
}

$lockPath = Join-Path $repoRoot "tools\\model_manifest.lock.json"
$lock = @{
    schema_version = 1
    generated_utc = (Get-Date).ToUniversalTime().ToString("s")
    manifest_path = $manifestPath
    manifest_sha256 = $manifestHash
    root_dir = $rootDir
    results = @{
        vllm = @()
        huggingface = @()
    }
}
if ($summary.ContainsKey("vllm")) {
    foreach ($entry in $summary["vllm"].results) {
        $lock.results.vllm += @{
            id = $entry.id
            served_id = $entry.served_id
            ok = $entry.ok
            status = $entry.status
            required = $entry.required
            error = $entry.error
        }
    }
}
if ($summary.ContainsKey("huggingface")) {
    foreach ($entry in $summary["huggingface"].results) {
        $files = @()
        if ($entry.ok -and $entry.dest) {
            $files = Get-DirFileHashes -Path $entry.dest
        }
        $lock.results.huggingface += @{
            id = $entry.id
            ok = $entry.ok
            status = $entry.status
            required = $entry.required
            error = $entry.error
            dest = $entry.dest
            files = $files
        }
    }
}
try {
    $lock | ConvertTo-Json -Depth 6 | Set-Content -Path $lockPath -Encoding UTF8
    Write-Status "INFO" "Wrote model lockfile to $lockPath"
    Write-PrepLog -Path $prepLog -Event "lockfile.written" -Data @{ path = $lockPath }
} catch {
    Write-Status "ERROR" "Failed to write model lockfile to $lockPath"
    Write-PrepLog -Path $prepLog -Event "lockfile.error" -Data @{ path = $lockPath }
}

if ($errors.Count -gt 0) {
    Write-AuditEvent -Action "models.prep.finish" -Outcome "error" -Details @{
        manifest = $manifestPath
        manifest_sha256 = $manifestHash
        root_dir = $rootDir
        lock_path = $lockPath
        errors = $errors
    }
    Write-Status "ERROR" "Model prep completed with errors: $($errors -join ', ')"
    Write-PrepLog -Path $prepLog -Event "finish.error" -Data @{ errors = $errors }
    exit 2
}

Write-AuditEvent -Action "models.prep.finish" -Outcome "ok" -Details @{
    manifest = $manifestPath
    manifest_sha256 = $manifestHash
    root_dir = $rootDir
    lock_path = $lockPath
}
Write-Status "OK" "Model prep complete"
Write-PrepLog -Path $prepLog -Event "finish.ok" -Data @{}
exit 0
