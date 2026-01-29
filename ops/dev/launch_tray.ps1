param(
  [string]$Python = "",
  [string]$VenvPath = "",
  [switch]$OpenBrowser,
  [switch]$NoBootstrap,
  [switch]$SelfTest,
  [switch]$SmokeTest
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
$devDir = Join-Path $Root ".dev"
$logDir = Join-Path $devDir "logs"
if (-not (Test-Path $logDir)) { New-Item -Path $logDir -ItemType Directory -Force | Out-Null }
$dataDir = $env:AUTOCAPTURE_DATA_DIR
if (-not $dataDir) { $dataDir = "D:\\autocapture"; $env:AUTOCAPTURE_DATA_DIR = $dataDir }
if (-not (Test-Path $dataDir)) { New-Item -Path $dataDir -ItemType Directory -Force | Out-Null }
$timestamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
$logLatest = Join-Path $logDir "tray_launcher.latest.log"
$logRun = Join-Path $logDir ("tray_launcher_{0}.log" -f $timestamp)
$procOut = Join-Path $logDir "tray_process.out.log"
$procErr = Join-Path $logDir "tray_process.err.log"
$LauncherVersion = "2026-01-29d"

try { Set-Content -Path $logLatest -Value "" -Encoding UTF8 } catch { }
try { Set-Content -Path $logRun -Value "" -Encoding UTF8 } catch { }

function Write-LogLine {
  param([string]$Message, [switch]$Error)
  $timestamp = (Get-Date).ToString("s")
  $line = "[$timestamp] $Message"
  try { Add-Content -Path $logRun -Value $line } catch { }
  try { Add-Content -Path $logLatest -Value $line } catch { }
  if ($Error) { Write-Error $Message } else { Write-Host $Message }
}

function Test-PosixVenv {
  param([string]$CfgPath)
  if (Test-Path $CfgPath) {
    try {
      $cfgText = Get-Content $CfgPath -Raw
      if ($cfgText -match "home\\s*=\\s*/" -or $cfgText -match "executable\\s*=\\s*/" -or $cfgText -match "command\\s*=\\s*/") {
        return $true
      }
    } catch { }
  }
  try {
    $root = Split-Path -Parent $CfgPath
    $binDir = Join-Path $root "bin"
    if (Test-Path (Join-Path $binDir "activate")) { return $true }
    if (Test-Path (Join-Path $binDir "python")) { return $true }
  } catch { }
  return $false
}

function Test-NonWindowsPythonPath {
  param([string]$Path)
  if (-not $Path) { return $true }
  if ($Path.StartsWith("/")) { return $true }
  if ($Path -match "[/\\\\]usr[/\\\\]bin") { return $true }
  if ($Path -like "\\\\wsl$\\*") { return $true }
  return $false
}

function Test-WindowsAppsStub {
  param([string]$Path)
  return ($Path -match "WindowsApps[/\\\\]python.exe")
}

function Resolve-ExplicitPython {
  param([string]$Explicit)
  if (Test-NonWindowsPythonPath $Explicit) {
    Write-LogLine -Error "Provided -Python path looks like WSL/POSIX. Use a Windows python.exe path."
    exit 1
  }
  if (-not (Test-Path $Explicit)) {
    Write-LogLine -Error "Python not found at $Explicit"
    exit 1
  }
  return (Resolve-Path $Explicit).Path
}

function Resolve-VenvRoot {
  param([string]$Explicit)
  if ($Explicit) {
    $full = $Explicit
    if (-not ([System.IO.Path]::IsPathRooted($full))) {
      $full = Join-Path $Root $Explicit
    }
    $cfg = Join-Path $full "pyvenv.cfg"
    if (Test-PosixVenv $cfg) {
      Write-LogLine -Error "Venv at $full looks like WSL (pyvenv.cfg home is POSIX). Choose a Windows venv path."
      exit 1
    }
    return $full
  }
  return (Join-Path $Root ".venv_win")
}

function Resolve-BootstrapPython {
  $result = [ordered]@{ exe = $null; prefix = @() }
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) {
    if (Test-NonWindowsPythonPath $cmd.Path) {
      Write-LogLine "WARN Skipping non-Windows python: $($cmd.Path)"
    } elseif ($cmd.Path -like "$Root\\*\\.venv\\*\\python.exe" -or $cmd.Path -like "$Root\\*\\.venv_win\\*\\python.exe") {
      $venvRoot = Split-Path -Parent (Split-Path -Parent $cmd.Path)
      $cfg = Join-Path $venvRoot "pyvenv.cfg"
      if (Test-PosixVenv $cfg) {
        Write-LogLine "WARN Skipping WSL venv python for bootstrap: $($cmd.Path)"
      } else {
        Write-LogLine "WARN Skipping repo venv python for bootstrap: $($cmd.Path)"
      }
    } elseif (Test-WindowsAppsStub $cmd.Path) {
      Write-LogLine "WARN Skipping WindowsApps python stub: $($cmd.Path)"
    } else {
      $result.exe = $cmd.Path
      return [pscustomobject]$result
    }
  }
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    $result.exe = $py.Path
    $result.prefix = @("-3")
    return [pscustomobject]$result
  }
  return [pscustomobject]$result
}

function Ensure-Venv {
  param(
    [string]$VenvRoot,
    [string]$BootstrapExe,
    [string[]]$BootstrapPrefix
  )
  $venvPy = Join-Path $VenvRoot "Scripts\\python.exe"
  if (Test-Path $venvPy) { return (Resolve-Path $venvPy).Path }
  if ($NoBootstrap) {
    Write-LogLine -Error "No Windows venv found at $VenvRoot. Run tools\\run_all_tests.ps1 or create a venv."
    exit 1
  }
  if (-not $BootstrapExe) {
    Write-LogLine -Error "Python not found. Provide -Python with full path or install Python 3.x."
    exit 1
  }
  Write-LogLine "Creating venv at $VenvRoot"
  & $BootstrapExe @BootstrapPrefix "-m" "venv" $VenvRoot
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  if (-not (Test-Path $venvPy)) {
    Write-LogLine -Error "Venv creation failed; missing $venvPy"
    exit 1
  }
  return (Resolve-Path $venvPy).Path
}

function Ensure-Pip {
  param([string]$PythonExe)
  & $PythonExe "-m" "ensurepip" "--upgrade" | Out-Null
  & $PythonExe "-m" "pip" "install" "--upgrade" "pip" "setuptools" "wheel"
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Invoke-EnsureDeps {
  param([string]$PythonExe)
  $wheelhouse = $env:AUTO_CAPTURE_WHEELHOUSE
  if (-not $wheelhouse) {
    $candidate = Join-Path $Root "wheels"
    if (Test-Path $candidate) { $wheelhouse = $candidate }
  }
  $allowNetwork = $env:AUTO_CAPTURE_ALLOW_NETWORK
  if (-not $allowNetwork) { $allowNetwork = "1" }
  $extra = $env:AUTO_CAPTURE_EXTRAS
  $target = "."
  if ($extra) { $target = ".[{0}]" -f $extra }
  $pipArgs = @("-m", "pip", "install", "-e", $target)
  if ($wheelhouse) {
    Write-LogLine "Using wheelhouse: $wheelhouse"
    $pipArgs = @("-m", "pip", "install", "-e", $target, "--no-index", "--find-links", $wheelhouse)
  } elseif ($allowNetwork -ne "1") {
    Write-LogLine -Error "Missing dependencies and no wheelhouse found. Set AUTO_CAPTURE_WHEELHOUSE or AUTO_CAPTURE_ALLOW_NETWORK=1."
    exit 1
  }
  & $PythonExe @pipArgs
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Test-Module {
  param([string]$PythonExe, [string]$ModuleName)
  try {
    $output = & $PythonExe "-c" "import $ModuleName" 2>&1
    $exitCode = $LASTEXITCODE
  } catch {
    Write-LogLine ("Module check exception (" + $ModuleName + "): " + $_.Exception.Message)
    return $false
  }
  if ($exitCode -ne 0) {
    $text = ($output | Out-String).Trim()
    if ($text) { Write-LogLine "Module check failed ($ModuleName): $text" }
    return $false
  }
  return $true
}

function Ensure-Dependencies {
  param([string]$PythonExe, [switch]$AllowInstall)
  if (-not $AllowInstall) {
    $required = @("uvicorn", "fastapi", "webview")
    $missing = @()
    foreach ($module in $required) {
      if (-not (Test-Module -PythonExe $PythonExe -ModuleName $module)) { $missing += $module }
    }
    if ($missing.Count -gt 0) {
      Write-LogLine -Error ("Missing dependencies: " + ($missing -join ", "))
      exit 1
    }
    return
  }
  Write-LogLine "Ensuring dependencies via pip install -e ."
  Ensure-Pip -PythonExe $PythonExe
  Invoke-EnsureDeps -PythonExe $PythonExe
  $verify = @("uvicorn", "fastapi", "webview")
  $stillMissing = @()
  foreach ($module in $verify) {
    if (-not (Test-Module -PythonExe $PythonExe -ModuleName $module)) { $stillMissing += $module }
  }
  if ($stillMissing.Count -gt 0) {
    Write-LogLine -Error ("Dependency install failed; still missing: " + ($stillMissing -join ", "))
    exit 1
  }
}

function Test-Port {
  param([string]$HostName, [int]$Port)
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect($HostName, $Port)
    $client.Close()
    return $true
  } catch {
    return $false
  }
}

function Get-FreePort {
  $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
  $listener.Start()
  $port = ($listener.LocalEndpoint).Port
  $listener.Stop()
  return $port
}

function Validate-PythonExe {
  param([string]$PythonExe)
  try {
    $output = & $PythonExe "-c" "import sys; print(sys.executable)" 2>&1
    $exitCode = $LASTEXITCODE
  } catch {
    return [pscustomobject]@{ ok = $false; message = $_.Exception.Message }
  }
  if ($exitCode -ne 0) {
    return [pscustomobject]@{ ok = $false; message = ($output | Out-String).Trim() }
  }
  $text = ($output | Out-String).Trim()
  if ($text -match "No Python at" -or $text.StartsWith("/") -or $text -match "[/\\\\]usr[/\\\\]bin" -or $text -like "\\\\wsl$\\*") {
    return [pscustomobject]@{ ok = $false; message = "python resolved to non-Windows path: $text" }
  }
  return [pscustomobject]@{ ok = $true; message = $text }
}

$usingManagedVenv = $false
$venvRoot = $null
if ($Python) {
$pythonExe = Resolve-ExplicitPython -Explicit $Python
} else {
  $venvRoot = Resolve-VenvRoot -Explicit $VenvPath
  $bootstrap = Resolve-BootstrapPython
  $pythonExe = Ensure-Venv -VenvRoot $venvRoot -BootstrapExe $bootstrap.exe -BootstrapPrefix $bootstrap.prefix
  $usingManagedVenv = $true
}
Write-LogLine "Launcher: $LauncherVersion"
Write-LogLine "Repo root: $Root"
Write-LogLine "Log (latest): $logLatest"
Write-LogLine "Log (run): $logRun"

$fixedHost = "127.0.0.1"
$fixedPort = 8787
$bindHost = $fixedHost
$bindPort = $fixedPort
$cfgHost = $null
$cfgPort = $null
try {
  $cfg = Get-Content (Join-Path $Root "config\default.json") -Raw | ConvertFrom-Json
  if ($cfg.web.bind_host) { $cfgHost = $cfg.web.bind_host }
  if ($cfg.web.bind_port) { $cfgPort = [int]$cfg.web.bind_port }
} catch {
  Write-LogLine "WARN Could not parse config/default.json; using ${bindHost}:${bindPort}"
}
try {
  $userCfgPath = Join-Path $Root "config\user.json"
  if (Test-Path $userCfgPath) {
    $userCfg = Get-Content $userCfgPath -Raw | ConvertFrom-Json
    if ($userCfg.web.bind_host) { $cfgHost = $userCfg.web.bind_host }
    if ($userCfg.web.bind_port) { $cfgPort = [int]$userCfg.web.bind_port }
  }
} catch {
  Write-LogLine "WARN Could not parse config/user.json; using ${bindHost}:${bindPort}"
}

$bindHost = $fixedHost
$bindPort = $fixedPort
if ($cfgHost -and $cfgHost -ne $fixedHost) {
  Write-LogLine "WARN Config bind_host ignored; using ${bindHost}:${bindPort}"
}
if ($cfgPort -and $cfgPort -ne $fixedPort) {
  Write-LogLine "WARN Config bind_port ignored; using ${bindHost}:${bindPort}"
}
$uiUrl = "http://${bindHost}:${bindPort}/ui/#settings"

$env:PYTHONPATH = $Root

$validation = Validate-PythonExe -PythonExe $pythonExe
if (-not $validation.ok) {
  if ($usingManagedVenv -and $venvRoot -and ($venvRoot -like "*\\.venv")) {
    Write-LogLine "WARN Invalid venv python ($($validation.message)). Falling back to .venv_win."
    $venvRoot = Join-Path $Root ".venv_win"
    $bootstrap = Resolve-BootstrapPython
    $pythonExe = Ensure-Venv -VenvRoot $venvRoot -BootstrapExe $bootstrap.exe -BootstrapPrefix $bootstrap.prefix
    $validation = Validate-PythonExe -PythonExe $pythonExe
  }
}
if (-not $validation.ok) {
Write-LogLine -Error "Python check failed: $($validation.message)"
  exit 1
}
Write-LogLine "Python: $pythonExe"
$env:AUTOCAPTURE_PYTHON_EXE = $pythonExe

Ensure-Dependencies -PythonExe $pythonExe -AllowInstall:$usingManagedVenv

if ($SelfTest -and $SmokeTest) {
  Write-LogLine -Error "Use either -SelfTest or -SmokeTest, not both."
  exit 1
}

if ($SelfTest) {
  try { & $pythonExe -c "import autocapture_nx.tray" | Out-Null } catch {
    Write-LogLine -Error "Failed to import autocapture_nx.tray"
    exit 1
  }
  try { & $pythonExe -c "import autocapture_nx.windows.tray" | Out-Null } catch {
    Write-LogLine -Error "Failed to import autocapture_nx.windows.tray"
    exit 1
  }
  Write-LogLine "Self-test OK."
  try { Stop-Transcript | Out-Null } catch { }
  exit 0
}

if ($SmokeTest) {
  $bindHost = "127.0.0.1"
  $bindPort = Get-FreePort
  $env:AUTOCAPTURE_TRAY_SMOKE = "1"
  $env:AUTOCAPTURE_TRAY_BIND_HOST = $bindHost
  $env:AUTOCAPTURE_TRAY_BIND_PORT = "$bindPort"
  $uiUrl = "http://${bindHost}:${bindPort}/ui/#settings"
} else {
  if (Test-Port -HostName $bindHost -Port $bindPort) {
    $healthy = $false
    try {
      $resp = Invoke-WebRequest -Uri "http://${bindHost}:${bindPort}/api/status" -UseBasicParsing -TimeoutSec 2
      if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) {
        $healthy = $true
      }
    } catch {
      $healthy = $false
    }
    if ($healthy) {
      Write-LogLine "UI already listening on ${bindHost}:${bindPort}"
      if ($OpenBrowser) { Start-Process $uiUrl }
      exit 0
    }
    Write-LogLine -Error "Port ${bindHost}:${bindPort} in use but /api/status is unhealthy."
    exit 1
  }
}

$pidDir = Join-Path $Root ".dev\pids"
if (-not (Test-Path $pidDir)) { New-Item -Path $pidDir -ItemType Directory | Out-Null }
$pidFile = Join-Path $pidDir "tray.pid"

$env:AUTOCAPTURE_TRAY_BIND_HOST = $bindHost
$env:AUTOCAPTURE_TRAY_BIND_PORT = "$bindPort"
$process = Start-Process -FilePath $pythonExe -ArgumentList "-m autocapture_nx.tray" -WorkingDirectory $Root -RedirectStandardOutput $procOut -RedirectStandardError $procErr -PassThru
$process.Id | Out-File -FilePath $pidFile -Encoding ascii

$deadline = (Get-Date).AddSeconds(20)
$statusReadyDeadline = $null
while ((Get-Date) -lt $deadline) {
  if ($process.HasExited) {
    Write-LogLine -Error "Tray process exited early (code $($process.ExitCode))"
    try { Start-Process notepad.exe $procErr | Out-Null } catch { }
    exit 1
  }
  if (Test-Port -HostName $bindHost -Port $bindPort) {
    if (-not $statusReadyDeadline) {
      $statusReadyDeadline = (Get-Date).AddSeconds(12)
    }
    $healthy = $false
    try {
      $resp = Invoke-WebRequest -Uri "http://${bindHost}:${bindPort}/api/status" -UseBasicParsing -TimeoutSec 2
      if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) {
        $healthy = $true
      }
    } catch {
      $healthy = $false
    }
    if ($healthy) {
      if ($OpenBrowser) { Start-Process $uiUrl }
      Write-LogLine "Tray running (pid $($process.Id)). UI: $uiUrl"
      if ($SmokeTest) {
        try { Stop-Process -Id $process.Id -Force } catch { }
        Write-LogLine "Smoke test OK."
        exit 0
      }
      exit 0
    }
    if ($statusReadyDeadline -and (Get-Date) -gt $statusReadyDeadline) {
      Write-LogLine -Error "UI port opened but /api/status is unhealthy."
      try { Start-Process notepad.exe $procErr | Out-Null } catch { }
      exit 1
    }
  }
  Start-Sleep -Milliseconds 200
}

Write-LogLine -Error "UI failed to start on ${bindHost}:${bindPort}"
try { Start-Process notepad.exe $logLatest | Out-Null } catch { }
try { Start-Process notepad.exe $logRun | Out-Null } catch { }
try { Start-Process notepad.exe $procOut | Out-Null } catch { }
try { Start-Process notepad.exe $procErr | Out-Null } catch { }
Write-LogLine "Log (latest): $logLatest"
Write-LogLine "Log (run): $logRun"
Write-LogLine "Process out: $procOut"
Write-LogLine "Process err: $procErr"
Write-LogLine "Press Enter to close..."
[void][System.Console]::ReadLine()
exit 1
