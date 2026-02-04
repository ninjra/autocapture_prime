param(
    [string]$ModelId = "",
    [string]$Manifest = "tools\\model_manifest.json",
    [string]$RootDir = "",
    [int]$Port = 8000,
    [string]$PreferKind = "",
    [int]$WaitSeconds = 45,
    [switch]$SkipModelPrep,
    [switch]$Foreground,
    [switch]$InstallVllm,
    [bool]$ShowProgress = $true
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
    return (Join-Path $logDir "vllm_start_$stamp.jsonl")
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

function Read-JsonFile {
    param([string]$Path)
    $raw = Get-Content -Path $Path -Raw -Encoding UTF8
    return ($raw | ConvertFrom-Json)
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

$repoRoot = Get-RepoRoot
$runLog = New-RunLog -RepoRoot $repoRoot
Write-Host "Run log: $runLog"

$manifestPath = $Manifest
if (-not (Test-Path $manifestPath)) {
    $manifestPath = Join-Path $repoRoot $Manifest
}
if (-not (Test-Path $manifestPath)) {
    Write-Host "ERROR: manifest not found at $manifestPath"
    exit 2
}

$manifestObj = Read-JsonFile -Path $manifestPath
$vllmSection = Get-ManifestValue -Manifest $manifestObj -Key "vllm"
if (-not $vllmSection) {
    Write-Host "ERROR: vllm section missing in manifest"
    exit 2
}

$models = @((Get-ManifestValue -Manifest $vllmSection -Key "models"))
$flat = New-Object System.Collections.Generic.List[object]
foreach ($entry in $models) {
    if ($null -eq $entry) { continue }
    if ($entry -is [System.Array]) { foreach ($item in $entry) { $flat.Add($item) } }
    else { $flat.Add($entry) }
}
$models = $flat.ToArray()

$serve = Get-ManifestValue -Manifest $vllmSection -Key "serve"
if (-not $PreferKind) {
    $PreferKind = [string](Get-ManifestValue -Manifest $serve -Key "prefer_kind")
}

$target = Select-VllmModel -Models $models -ModelId $ModelId -PreferKind $PreferKind
if ($null -eq $target) {
    Write-Host "ERROR: No vLLM model available to serve"
    exit 2
}

$rootResolved = $RootDir
if (-not $rootResolved) {
    $rootResolved = [string](Get-ManifestValue -Manifest $manifestObj -Key "root_dir")
}
if (-not $rootResolved) {
    $rootResolved = "D:\\autocapture\\models"
}
if ($rootResolved -match '^[A-Za-z]:$') {
    $rootResolved = "$rootResolved\\autocapture\\models"
}

$subdir = [string](Get-ManifestValue -Manifest $target -Key "subdir")
if (-not $subdir) {
    $subdir = ([string](Get-ManifestValue -Manifest $target -Key "id") -replace "[^A-Za-z0-9._-]", "_")
}
$modelPath = Join-Path $rootResolved $subdir

Write-RunLog -Path $runLog -Event "start" -Data @{
    manifest = $manifestPath
    model_id = [string](Get-ManifestValue -Manifest $target -Key "id")
    model_path = $modelPath
    root_dir = $rootResolved
    prefer_kind = $PreferKind
}

if (-not $SkipModelPrep) {
    $prepScript = Join-Path $repoRoot "tools\\model_prep.ps1"
    if (Test-Path $prepScript) {
        & $prepScript -Manifest $manifestPath -RootDir $rootResolved -OnlyHfId ([string](Get-ManifestValue -Manifest $target -Key "id")) -ForceHf
    }
}

if (-not (Test-Path $modelPath)) {
    Write-Host "ERROR: model path not found: $modelPath"
    exit 2
}
if (-not (Get-ChildItem -Path $modelPath -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1)) {
    Write-Host "ERROR: model path is empty: $modelPath"
    Write-Host "Run model_prep with -ForceHf to download the files."
    exit 2
}

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
$wslHome = ""
try {
    $wslHome = & $wslExe -e bash -lc "eval echo ~"
    $wslHome = ($wslHome | Out-String).Trim()
} catch {
    $wslHome = ""
}
if (-not $wslHome -or -not ($wslHome.StartsWith("/") -and $wslHome -notmatch ":")) {
    try {
        $wslUser = & $wslExe -e bash -lc "whoami"
        $wslUser = ($wslUser | Out-String).Trim()
        if ($wslUser) {
            $wslHome = "/home/$wslUser"
        }
    } catch {
        $wslHome = ""
    }
}
$venvCandidates = @()
if ($wslHome) { $venvCandidates += "$wslHome/.venvs/vllm" }
$venvCandidates += "/mnt/d/autocapture/venvs/vllm"
$venvDir = ""
$venvPython = ""
$venvVllm = ""
$venvOk = $false
$venvChecks = @()
foreach ($candidate in $venvCandidates) {
    if (-not $candidate) { continue }
    $candPython = "$candidate/bin/python"
    try {
        & $wslExe -e bash -lc "test -x $candPython"
        if ($LASTEXITCODE -ne 0) { continue }
        $pyCheck = & $wslExe -e bash -lc "$candPython -V" 2>&1
        $pyOk = ($LASTEXITCODE -eq 0)
        $importOk = $false
        $importOut = ""
        if ($pyOk) {
            $importOut = & $wslExe -e bash -lc "$candPython -c 'import vllm'" 2>&1
            if ($LASTEXITCODE -eq 0) { $importOk = $true }
        }
        $venvChecks += @{
            venv = $candidate
            python = $candPython
            python_version = ($pyCheck | Out-String).Trim()
            ok = ($pyOk -and $importOk)
            import_ok = $importOk
            import_output = ($importOut | Out-String).Trim()
        }
        if (-not ($pyOk -and $importOk)) { continue }
        $venvDir = $candidate
        $venvPython = $candPython
        $venvVllm = "$candidate/bin/vllm"
        $venvOk = $true
        break
    } catch {
        $venvChecks += @{
            venv = $candidate
            python = $candPython
            python_version = ""
            ok = $false
            import_ok = $false
            error = $_.Exception.Message
        }
        continue
    }
}

$pythonForVllm = if ($venvOk) { $venvPython } else { "python3" }

try {
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $uname = & $wslExe -e bash -lc "uname -a"
    $pythonPath = & $wslExe -e bash -lc "command -v python3"
    $pythonVer = & $wslExe -e bash -lc "python3 -V"
    $vllmPath = & $wslExe -e bash -lc "command -v vllm"
    $checkCmd = "$pythonForVllm -c 'import vllm'"
    $vllmCheckOut = & $wslExe -e bash -lc $checkCmd 2>&1
    $gpu = & $wslExe -e bash -lc "nvidia-smi -L" 2>&1
    $ErrorActionPreference = $oldEap
    Write-RunLog -Path $runLog -Event "wsl.preflight" -Data @{
        uname = ($uname | Out-String).Trim()
        python_path = ($pythonPath | Out-String).Trim()
        python_version = ($pythonVer | Out-String).Trim()
        vllm_path = ($vllmPath | Out-String).Trim()
        vllm_module = if ($LASTEXITCODE -eq 0) { "present" } else { "missing" }
        vllm_import_output = ($vllmCheckOut | Out-String).Trim()
        vllm_version = ""
        venv_ok = $venvOk
        venv_python = $venvPython
        venv_dir = $venvDir
        venv_checks = $venvChecks
        gpu = ($gpu | Out-String).Trim()
    }
} catch {
    Write-RunLog -Path $runLog -Event "wsl.preflight_error" -Data @{ error = $_.Exception.Message }
}

$gpuText = $null
try {
    $gpuText = & $wslExe -e bash -lc "nvidia-smi -L" 2>&1
    $gpuText = ($gpuText | Out-String).Trim()
} catch {
    $gpuText = ""
}
if ($gpuText -match "NVIDIA-SMI has failed" -or $gpuText -match "not found") {
    Write-RunLog -Path $runLog -Event "gpu.missing" -Data @{ output = $gpuText }
    Write-Host "ERROR: GPU is not available inside WSL. vLLM requires CUDA."
    Write-Host "Fix WSL GPU, then retry."
    exit 2
}

$vllmModuleOk = $false
try {
    $checkCmd = "$pythonForVllm -c 'import vllm'"
    & $wslExe -e bash -lc $checkCmd 2>&1
    if ($LASTEXITCODE -eq 0) { $vllmModuleOk = $true }
} catch {
    $vllmModuleOk = $false
}

if (-not $vllmModuleOk) {
    Write-RunLog -Path $runLog -Event "vllm.missing" -Data @{}
    if ($InstallVllm) {
        $installer = Join-Path $repoRoot "tools\\install_vllm.ps1"
        if (Test-Path $installer) {
            & $installer
            if ($LASTEXITCODE -ne 0) {
                Write-Host "ERROR: vLLM install failed"
                exit 2
            }
        } else {
            Write-Host "ERROR: vLLM installer not found at $installer"
            exit 2
        }
    } else {
        Write-Host "ERROR: vLLM is not installed in WSL (venv not detected or import failed)"
        Write-Host "Run: D:\\projects\\autocapture_prime\\tools\\install_vllm.ps1"
        exit 2
    }
}

$cacheDir = Join-Path $rootResolved "_hf_cache"
$modelWsl = Convert-ToWslPath -Path $modelPath
$cacheWsl = Convert-ToWslPath -Path $cacheDir

try {
    $lsOut = & $wslExe -e bash -lc "ls -lah $modelWsl | head -n 5" 2>&1
    Write-RunLog -Path $runLog -Event "model.ls" -Data @{ output = ($lsOut | Out-String).Trim() }
} catch {
    Write-RunLog -Path $runLog -Event "model.ls_error" -Data @{ error = $_.Exception.Message }
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
$apiKey = [string](Get-ManifestValue -Manifest (Get-ManifestValue -Manifest $vllmSection -Key "server") -Key "api_key")
$servedArg = ""
if ($servedId) { $servedArg = "--served-model-name $servedId" }
$apiArg = ""
if ($apiKey) { $apiArg = "--api-key $apiKey" }

$vllmCmd = "$pythonForVllm -m vllm.entrypoints.openai.api_server"

$launchCmd = "HF_HOME=$cacheWsl TRANSFORMERS_CACHE=$cacheWsl TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1 VLLM_LOG_LEVEL=info " +
        "$vllmCmd --host 127.0.0.1 --port $Port $apiArg $servedArg --model $modelWsl $engineArgString"

Write-Host "Starting vLLM (model: $([string](Get-ManifestValue -Manifest $target -Key "id")))"
Write-RunLog -Path $runLog -Event "launch_cmd" -Data @{ cmd = $launchCmd }

    try {
        & $wslExe -e bash -lc "mkdir -p /tmp; : > /tmp/vllm_autocapture.log"
    } catch {
        Write-RunLog -Path $runLog -Event "log_init_error" -Data @{ error = $_.Exception.Message }
    }

    if ($Foreground) {
        Write-Host "Launching vLLM in foreground..."
        & $wslExe -e bash -lc "$launchCmd"
        Write-RunLog -Path $runLog -Event "foreground.exit" -Data @{ exit_code = $LASTEXITCODE }
        exit $LASTEXITCODE
    }

    $pidOut = ""
    $pidText = ""
    $pid = ""
    $launchExit = 0
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $launchLine = "$launchCmd > /tmp/vllm_autocapture.log 2>&1 & echo \$!"
        $pidOut = & $wslExe -e bash -lc $launchLine 2>&1
        $launchExit = $LASTEXITCODE
        $pidText = ($pidOut | Out-String).Trim()
        if ($pidText -match "(\d+)") { $pid = $matches[1] }
    } finally {
        $ErrorActionPreference = $oldEap
    }
    Write-RunLog -Path $runLog -Event "launch.pid" -Data @{ pid = $pid; raw = $pidText; exit_code = $launchExit; output = $pidText }
    if (-not $pid -or $launchExit -ne 0) {
        Write-RunLog -Path $runLog -Event "launch.error" -Data @{ pid = $pid; exit_code = $launchExit; output = $pidText }
        Write-Host "ERROR: vLLM failed to launch (no PID returned)."
        exit 2
    }

$baseUrl = "http://127.0.0.1:$Port"
$idleWindowSeconds = 30
$startTime = Get-Date
$deadline = $startTime.AddSeconds($WaitSeconds)
$lastLogMtime = 0
if ($ShowProgress) {
    Write-Host ("Waiting for vLLM at {0} (base {1}s, idle window {2}s)..." -f $baseUrl, $WaitSeconds, $idleWindowSeconds)
}
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    $elapsed = [int]((Get-Date) - $startTime).TotalSeconds
    if (Test-VllmServer -BaseUrl $baseUrl) {
        Write-Host "vLLM is up at $baseUrl"
        Write-RunLog -Path $runLog -Event "ready" -Data @{ base_url = $baseUrl; elapsed_s = $elapsed }
        exit 0
    }
    if ($elapsed % 4 -eq 0) {
        try {
            $mtimeOut = & $wslExe -e bash -lc "stat -c %Y /tmp/vllm_autocapture.log 2>/dev/null"
            if ($LASTEXITCODE -eq 0 -and $mtimeOut) {
                $mtime = [int64]($mtimeOut | Select-Object -First 1)
                if ($mtime -gt $lastLogMtime) {
                    $lastLogMtime = $mtime
                    $deadline = [DateTime]::Max($deadline, (Get-Date).AddSeconds($idleWindowSeconds))
                    Write-RunLog -Path $runLog -Event "log.activity" -Data @{ mtime = $mtime; elapsed_s = $elapsed }
                }
            }
        } catch {
            Write-RunLog -Path $runLog -Event "log.activity_error" -Data @{ error = $_.Exception.Message }
        }
    }
    if ($pid -and ($elapsed % 6 -eq 0)) {
        try {
            & $wslExe -e bash -lc "kill -0 $pid 2>/dev/null"
            if ($LASTEXITCODE -ne 0) {
                Write-RunLog -Path $runLog -Event "process.exit" -Data @{ pid = $pid; elapsed_s = $elapsed }
                $tail = & $wslExe -e bash -lc "tail -n 200 /tmp/vllm_autocapture.log"
                if ($tail) {
                    Write-RunLog -Path $runLog -Event "log_tail" -Data @{ lines = ($tail | Out-String) }
                }
                Write-Host "ERROR: vLLM process exited before becoming ready."
                exit 2
            }
        } catch {
            Write-RunLog -Path $runLog -Event "process.check_error" -Data @{ error = $_.Exception.Message }
        }
    }
    if ($ShowProgress -and ($elapsed % 5 -eq 0)) {
        $remaining = [int]([Math]::Max(0, ($deadline - (Get-Date)).TotalSeconds))
        Write-Host ("...still waiting ({0}s elapsed, {1}s idle window)" -f $elapsed, $remaining)
        Write-RunLog -Path $runLog -Event "wait" -Data @{ elapsed_s = $elapsed; idle_window_s = $remaining }
    }
}

Write-Host "ERROR: vLLM failed to start (idle window elapsed)"
Write-RunLog -Path $runLog -Event "timeout" -Data @{ base_url = $baseUrl; wait_seconds = $WaitSeconds; idle_window_s = $idleWindowSeconds }
try {
    $tail = & $wslExe -e bash -lc "tail -n 200 /tmp/vllm_autocapture.log"
    if ($tail) {
        Write-RunLog -Path $runLog -Event "log_tail" -Data @{
            lines = ($tail | Out-String)
        }
    }
} catch {
    Write-RunLog -Path $runLog -Event "log_tail_error" -Data @{ error = $_.Exception.Message }
}
try {
    $wslProbe = "python3 -c `"import urllib.request as u; u.urlopen('http://127.0.0.1:$Port/v1/models', timeout=2).read(); print('ok')`""
    $probeOut = & $wslExe -e bash -lc $wslProbe 2>&1
    Write-RunLog -Path $runLog -Event "wsl.http_probe" -Data @{ output = ($probeOut | Out-String).Trim(); exit_code = $LASTEXITCODE }
} catch {
    Write-RunLog -Path $runLog -Event "wsl.http_probe_error" -Data @{ error = $_.Exception.Message }
}
try {
    $psOut = & $wslExe -e bash -lc "ps -ef | grep vllm | grep -v grep" 2>&1
    Write-RunLog -Path $runLog -Event "wsl.ps" -Data @{ output = ($psOut | Out-String).Trim() }
    $ssOut = & $wslExe -e bash -lc "ss -lntp | grep :$Port" 2>&1
    Write-RunLog -Path $runLog -Event "wsl.ss" -Data @{ output = ($ssOut | Out-String).Trim() }
} catch {
    Write-RunLog -Path $runLog -Event "wsl.diag_error" -Data @{ error = $_.Exception.Message }
}
exit 2
