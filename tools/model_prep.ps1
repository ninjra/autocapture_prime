param(
    [string]$Manifest = "tools\\model_manifest.json",
    [string]$RootDir = "",
    [switch]$SkipVllm,
    [switch]$SkipHuggingFace,
    [switch]$SkipWarm,
    [switch]$AllowInstallHfCli
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
    return Get-Content $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Ensure-Dir {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
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
    if ($Manifest -is [hashtable]) {
        if ($Manifest.ContainsKey($Key)) { return $Manifest[$Key] }
        return $null
    }
    if ($Manifest.PSObject.Properties.Match($Key).Count -gt 0) {
        return $Manifest.$Key
    }
    return $null
}

function Ensure-Vllm {
    param(
        [hashtable]$Server,
        [object[]]$Models,
        [switch]$SkipWarm
    )
    $vllmHost = ""
    $vllmPort = 0
    $apiKey = ""
    if ($Server) {
        if ($Server.PSObject.Properties.Name -contains "host") { $vllmHost = [string]$Server.host }
        if ($Server.PSObject.Properties.Name -contains "port") { $vllmPort = [int]$Server.port }
        if ($Server.PSObject.Properties.Name -contains "api_key") { $apiKey = [string]$Server.api_key }
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

    $serverOk = $false
    $available = @()
    try {
        $resp = Invoke-RestMethod -Uri "$baseUrl/v1/models" -Method Get -Headers $headers -TimeoutSec 4
        if ($resp) { $serverOk = $true }
    } catch {
        $serverOk = $false
    }
    if (-not $serverOk) {
        Write-Status "ERROR" "vLLM server not responding on $baseUrl"
        return @{ ok = $false; error = "vllm_server_unavailable"; base_url = $baseUrl }
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
        $mid = [string]$model.id
        if (-not $mid) { continue }
        $servedId = $mid
        if ($model.PSObject.Properties.Name -contains "served_id") { $servedId = [string]$model.served_id }
        if ($model.PSObject.Properties.Name -contains "served_name") { $servedId = [string]$model.served_name }
        if (-not $servedId) { $servedId = $mid }
        $required = $false
        if ($model.PSObject.Properties.Name -contains "required") {
            $required = [bool]$model.required
        }
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
    $hf = Get-Command huggingface-cli -ErrorAction SilentlyContinue
    if ($hf) { return @{ ok = $true; cmd = $hf.Source } }
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
    $hf = Get-Command huggingface-cli -ErrorAction SilentlyContinue
    if ($hf) { return @{ ok = $true; cmd = $hf.Source } }
    return @{ ok = $false; error = "huggingface_cli_missing" }
}

function Download-HfModels {
    param(
        [object[]]$Models,
        [string]$RootDir,
        [switch]$AllowInstall
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
        $id = [string]$model.id
        if (-not $id) { continue }
        $required = $false
        if ($model.PSObject.Properties.Name -contains "required") {
            $required = [bool]$model.required
        }
        $subdir = if ($model.PSObject.Properties.Name -contains "subdir") { [string]$model.subdir } else { "" }
        if (-not $subdir) {
            $subdir = ($id -replace "[^A-Za-z0-9._-]", "_")
        }
        $dest = Join-Path $RootDir $subdir
        Ensure-Dir -Path $dest
        if ((Get-ChildItem -Path $dest -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1)) {
            $results += [pscustomobject]@{ id = $id; ok = $true; status = "present"; required = $required; error = $null; dest = $dest }
            continue
        }
        $candidates = @()
        if ($model.PSObject.Properties.Name -contains "candidates") {
            $candidates = @($model.candidates)
        }
        if (-not $candidates -or $candidates.Count -eq 0) { $candidates = @($id) }
        $downloaded = $false
        $error = $null
        foreach ($candidate in $candidates) {
            Write-Status "INFO" "huggingface-cli download $candidate -> $dest"
            $ok = Try-Invoke { & $cli.cmd download $candidate --local-dir $dest --local-dir-use-symlinks False }
            if ($ok) {
                $downloaded = $true
                $error = $null
                break
            }
            $error = "download_failed"
        }
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
$manifest = Read-Manifest -Path $manifestPath
$manifestHash = ""
try {
    $manifestHash = (Get-FileHash -Path $manifestPath -Algorithm SHA256).Hash
} catch {
    $manifestHash = ""
}

$rootDir = if ($RootDir) { $RootDir } else { [string](Get-ManifestValue -Manifest $manifest -Key "root_dir") }
if (-not $rootDir) {
    $rootDir = [string](Get-ManifestValue -Manifest $manifest -Key "rootDir")
}
if (-not $rootDir) {
    $rootDir = [string]$env:AUTOCAPTURE_MODEL_ROOT
}
if (-not $rootDir) {
    $rootDir = "D:\\autocapture\\models"
}
if ($rootDir -match '^[A-Za-z]:$') {
    $drive = $rootDir
    $manifestRoot = [string]$manifest.root_dir
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

if (-not $SkipVllm) {
    $vllmModels = @()
    $vllmSection = Get-ManifestValue -Manifest $manifest -Key "vllm"
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
    $vllmResult = Ensure-Vllm -Server $vllmServer -Models $vllmModels -SkipWarm:$SkipWarm
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

if (-not $SkipHuggingFace) {
    $hfModels = @()
    $hfSection = Get-ManifestValue -Manifest $manifest -Key "huggingface"
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
    $hfResult = Download-HfModels -Models $hfModels -RootDir $rootDir -AllowInstall:$AllowInstallHfCli
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

Write-Host ""
Write-Status "INFO" "Model prep summary"
Write-Host ($summary | ConvertTo-Json -Depth 6)

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
} catch {
    Write-Status "ERROR" "Failed to write model lockfile to $lockPath"
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
    exit 2
}

Write-AuditEvent -Action "models.prep.finish" -Outcome "ok" -Details @{
    manifest = $manifestPath
    manifest_sha256 = $manifestHash
    root_dir = $rootDir
    lock_path = $lockPath
}
Write-Status "OK" "Model prep complete"
exit 0
