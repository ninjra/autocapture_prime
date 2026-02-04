param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("export", "import")]
    [string]$Mode,
    [Parameter(Mandatory = $true)]
    [string]$BundlePath,
    [string]$RepoRoot = "D:\\projects\\autocapture_prime",
    [string]$DataDir = "",
    [string]$ConfigDir = "",
    [string]$PythonExe = "",
    [string]$Passphrase = ""
)

$ErrorActionPreference = "Stop"

function Fail {
    param([string]$Message)
    throw $Message
}

if (-not (Test-Path $RepoRoot)) { Fail "RepoRoot not found: $RepoRoot" }
$scriptPath = Join-Path $RepoRoot "tools\\keyring_bundle.py"
if (-not (Test-Path $scriptPath)) { Fail "Missing tool: $scriptPath" }

if (-not $PythonExe) {
    $venvPython = Join-Path $RepoRoot ".venv_win\\Scripts\\python.exe"
    if (Test-Path $venvPython) {
        $PythonExe = $venvPython
    } else {
        $cmdPy = Get-Command py -ErrorAction SilentlyContinue
        if ($cmdPy) {
            $PythonExe = $cmdPy.Source
            $env:PYTHONIOENCODING = "utf-8"
        } else {
            $cmdPython = Get-Command python -ErrorAction SilentlyContinue
            if ($cmdPython) {
                $PythonExe = $cmdPython.Source
            }
        }
    }
}
if (-not $PythonExe) { Fail "Python not found. Install Python 3.x or set -PythonExe." }

$argsList = @()
if ($PythonExe -match "(^|\\\\)py\\.exe$") {
    $argsList += "-3"
}
$argsList += $scriptPath
if ($DataDir) { $argsList += @("--data-dir", $DataDir) }
if ($ConfigDir) { $argsList += @("--config-dir", $ConfigDir) }

if ($Mode -eq "export") {
    $argsList += @("export", "--out", $BundlePath)
} else {
    if (-not (Test-Path $BundlePath)) { Fail "Bundle not found: $BundlePath" }
    $argsList += @("import", "--bundle", $BundlePath)
}
if ($Passphrase) { $argsList += @("--passphrase", $Passphrase) }

Write-Host ("Running: {0} {1}" -f $PythonExe, ($argsList -join " "))
& $PythonExe @argsList
if ($LASTEXITCODE -ne 0) { Fail "keyring bundle $Mode failed" }
Write-Host "OK: keyring bundle $Mode completed"
