param(
    [string]$RepoRoot = "D:\\projects\\autocapture_prime",
    [string]$ModelRoot = "D:\\autocapture\\models",
    [string]$Manifest = "D:\\projects\\autocapture_prime\\docs\\test sample\\fixture_manifest.json",
    [string]$ModelManifest = "D:\\projects\\autocapture_prime\\tools\\model_manifest.json",
    [string]$VllmModelId = "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
    [int]$VllmPort = 8000,
    [bool]$SkipSqlcipher = $true
)

$ErrorActionPreference = "Stop"

function New-LogFile {
    param([string]$BaseDir)
    Ensure-Dir -Path $BaseDir
    $stamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
    return (Join-Path $BaseDir "run_full_pipeline_$stamp.log")
}

function Log {
    param([string]$Message)
    $stamp = (Get-Date).ToString("s")
    $line = "[$stamp] $Message"
    Add-Content -Path $script:LogPath -Value $line -Encoding UTF8
    Write-Host $line
}

function Fail {
    param([string]$Message)
    if ($script:LogPath) {
        Log "ERROR: $Message"
        Log "Log file: $script:LogPath"
    }
    throw $Message
}

function Invoke-Logged {
    param(
        [string]$Label,
        [string]$Exe,
        [string[]]$Arguments
    )
    $cmdLine = $Exe + " " + ($Arguments -join " ")
    Log "${Label}: $cmdLine"
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $output = & $Exe @Arguments 2>&1
    $ErrorActionPreference = $oldEap
    $code = $LASTEXITCODE
    if ($output) {
        foreach ($line in @($output)) {
            Add-Content -Path $script:LogPath -Value $line -Encoding UTF8
            Write-Host $line
        }
    }
    return $code
}

function Require-Path {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path $Path)) { Fail "Missing $Label at $Path" }
}

function Ensure-Dir {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Resolve-MetadataPath {
    param([string]$RunDir)
    $primary = Join-Path $RunDir "data\\metadata.db"
    if (Test-Path $primary) { return $primary }
    $legacy = Join-Path $RunDir "data\\metadata\\metadata.db"
    if (Test-Path $legacy) { return $legacy }
    return $primary
}

function Test-WslSocket {
    param([int]$Port)
    $socketScript = Join-Path $RepoRoot "tools\\wsl_socket_check.ps1"
    $args = @("-NoProfile","-ExecutionPolicy","Bypass","-File",$socketScript)
    if ($Port -ne 0) {
        Log "WARN: wsl_socket_check.ps1 ignores port override (using ephemeral bind)."
    }
    return (Invoke-Logged -Label "wsl socket test" -Exe "powershell.exe" -Arguments $args)
}

$logDir = Join-Path $RepoRoot "artifacts\\logs"
$script:LogPath = New-LogFile -BaseDir $logDir
Set-Content -Path $script:LogPath -Value "" -Encoding UTF8
Log "RepoRoot: $RepoRoot"
Log "ModelRoot: $ModelRoot"
Log "Manifest: $Manifest"
Log "ModelManifest: $ModelManifest"

Require-Path -Path $RepoRoot -Label "repo root"
Require-Path -Path $Manifest -Label "fixture manifest"
Require-Path -Path $ModelManifest -Label "model manifest"

# Validate manifest screenshot paths are full Windows paths.
try {
    $manifestObj = Get-Content -Raw -Path $Manifest | ConvertFrom-Json
} catch {
    Fail "Unable to parse manifest JSON: $Manifest"
}
$screens = $manifestObj.inputs.screenshots
if (-not $screens) { Fail "Manifest has no screenshots: $Manifest" }
foreach ($item in $screens) {
    $p = ([string]$item.path).Trim()
    if (-not $p -or $p -notmatch '^[A-Za-z]:\\') {
        Fail "Manifest screenshot path must be full Windows path. Got: $p"
    }
    if (-not (Test-Path $p)) {
        Fail "Screenshot path does not exist: $p"
    }
}

# Ensure Python venv on Windows
$venvPath = Join-Path $RepoRoot ".venv_win"
$pythonExe = Join-Path $venvPath "Scripts\\python.exe"
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
$pyExe = $null
$pyArgs = @()
if ($pyLauncher) {
    $pyExe = $pyLauncher.Source
    $pyArgs = @("-3")
} else {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $pyExe = $pythonCmd.Source
        $pyArgs = @()
    }
}
if (-not $pyExe) {
    Fail "Python not found. Install Python 3.x and retry."
}
if (-not (Test-Path $pythonExe)) {
    Log "Creating venv at $venvPath"
    & $pyExe @pyArgs -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { Fail "venv creation failed" }
}

$env:PATH = "$venvPath\\Scripts;$env:PATH"
$env:PYTHONPATH = $RepoRoot

Log "Upgrading pip..."
if ((Invoke-Logged -Label "pip upgrade" -Exe $pythonExe -Arguments @("-m","pip","install","-U","pip")) -ne 0) {
    Fail "pip upgrade failed"
}

Log "Installing Python deps (ocr, embeddings, vision)..."
if ((Invoke-Logged -Label "pip install core extras" -Exe $pythonExe -Arguments @("-m","pip","install","-e","$RepoRoot[ocr,embeddings,vision]")) -ne 0) {
    Fail "pip install failed"
}

if ($SkipSqlcipher) {
    Log "Skipping SQLCipher install (SkipSqlcipher=true)."
} else {
    Log "Attempting SQLCipher deps (optional)..."
    if ((Invoke-Logged -Label "pip install sqlcipher" -Exe $pythonExe -Arguments @("-m","pip","install","-e","$RepoRoot[sqlcipher]")) -ne 0) {
        Log "WARN: SQLCipher install failed; continuing with encrypted SQLite fallback."
    }
}

# Download models (OCR/VLM/embeddings + vLLM models)
Log "Running model_prep..."
$prepArgs = @("-NoProfile","-ExecutionPolicy","Bypass","-File","$RepoRoot\\tools\\model_prep.ps1",
    "-Manifest",$ModelManifest,
    "-RootDir",$ModelRoot,
    "-AllowInstallHfCli",
    "-ShowProgress")
if ((Invoke-Logged -Label "model_prep" -Exe "powershell.exe" -Arguments $prepArgs) -ne 0) {
    Fail "model_prep failed"
}

# Verify external vLLM is responding (owned by sidecar repo)
Log "Checking external vLLM at http://127.0.0.1:$VllmPort/v1/models"
try {
    Invoke-RestMethod "http://127.0.0.1:$VllmPort/v1/models" -TimeoutSec 5 | Out-Null
} catch {
    Fail "External vLLM unavailable on 127.0.0.1:$VllmPort. This repo no longer starts vLLM; start it from the sidecar/hypervisor repo."
}

# Run fixture pipeline with full processing
Log "Running fixture pipeline (force idle)..."
$fixtureArgs = @("-NoProfile","-ExecutionPolicy","Bypass","-File","$RepoRoot\\tools\\run_fixture_pipeline.ps1",
    "-Manifest",$Manifest,
    "-ModelManifest",$ModelManifest,
    "-ForceIdle")
if ((Invoke-Logged -Label "fixture pipeline" -Exe "powershell.exe" -Arguments $fixtureArgs) -ne 0) {
    Fail "fixture pipeline failed"
}

# Locate latest run
$runsDir = Join-Path $RepoRoot "artifacts\\fixture_runs"
Require-Path -Path $runsDir -Label "fixture_runs dir"
$latest = Get-ChildItem -Path $runsDir | Sort-Object Name -Descending | Select-Object -First 1
if (-not $latest) { Fail "No fixture run output found in $runsDir" }
$runDir = $latest.FullName
Log "Latest run: $runDir"

# Verify DB files exist
$metadataPath = Resolve-MetadataPath -RunDir $runDir
$dbPaths = @{
    metadata = $metadataPath
    lexical = (Join-Path $runDir "data\\lexical.db")
    vector = (Join-Path $runDir "data\\vector.db")
    state_tape = (Join-Path $runDir "data\\state\\state_tape.db")
    state_vector = (Join-Path $runDir "data\\state\\state_vector.db")
    audit = (Join-Path $runDir "data\\audit\\kernel_audit.db")
}
foreach ($key in $dbPaths.Keys) {
    $path = $dbPaths[$key]
    Require-Path -Path $path -Label "$key db"
    $size = (Get-Item $path).Length
    Log ("OK {0}: {1} bytes ({2})" -f $key, $size, $path)
}

# Count lexical/vector records (fail if empty)
$vectorPath = $dbPaths["vector"]
$vectorCode = "import sqlite3,sys; con=sqlite3.connect(r'''$vectorPath'''); c=con.execute('select count(*) from vectors').fetchone()[0]; print('vector_count', c); sys.exit(0 if c>0 else 2)"
if ((Invoke-Logged -Label "vector count" -Exe $pythonExe -Arguments @("-c",$vectorCode)) -ne 0) {
    Fail "vector.db has zero records"
}

$lexPath = $dbPaths["lexical"]
$lexCode = "import sqlite3,sys; con=sqlite3.connect(r'''$lexPath'''); c=con.execute('select count(*) from fts').fetchone()[0]; print('lexical_count', c); sys.exit(0 if c>0 else 2)"
if ((Invoke-Logged -Label "lexical count" -Exe $pythonExe -Arguments @("-c",$lexCode)) -ne 0) {
    Fail "lexical.db has zero records"
}

# Run the user query against the populated run
$env:AUTOCAPTURE_CONFIG_DIR = Join-Path $runDir "config"
$env:AUTOCAPTURE_DATA_DIR = Join-Path $runDir "data"
Log "Running query against latest run..."
if ((Invoke-Logged -Label "query" -Exe $pythonExe -Arguments @("-m","autocapture_nx","query","How many days do I have left to get in touch with my tax accountant?")) -ne 0) {
    Fail "query command failed"
}

Log "DONE: full pipeline completed."
Log "Log file: $script:LogPath"
