param(
    [Parameter(Position = 0)]
    [string]$Verb = "doctor",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    try {
        return (Resolve-Path (Join-Path $PSScriptRoot ".")).ToString()
    } catch {
        return (Get-Location).ToString()
    }
}

$repoRoot = Get-RepoRoot
Set-Location $repoRoot

$devDir = Join-Path $repoRoot ".dev"
$logDir = Join-Path $devDir "logs"
$pidDir = Join-Path $devDir "pids"
$stateDir = Join-Path $devDir "state"
$cacheDir = Join-Path $devDir "cache"

$commonEnv = Join-Path $repoRoot "ops\dev\common.env"
$portsEnv = Join-Path $repoRoot "ops\dev\ports.env"

function Ensure-DevDirs {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    New-Item -ItemType Directory -Path $pidDir -Force | Out-Null
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null
}

function Import-EnvFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line) { return }
        if ($line.StartsWith("#")) { return }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { return }
        $key = $line.Substring(0, $idx).Trim()
        $val = $line.Substring($idx + 1).Trim()
        if (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'"))) {
            $val = $val.Substring(1, $val.Length - 2)
        }
        $env:$key = $val
    }
}

function Load-Env {
    Import-EnvFile $commonEnv
    Import-EnvFile $portsEnv
}

function Test-UiDetected {
    if (Test-Path (Join-Path $repoRoot "package.json")) { return $true }
    foreach ($d in @("ui", "frontend", "client", "web", "apps")) {
        if (Test-Path (Join-Path $repoRoot $d)) { return $true }
    }
    return $false
}

function Get-PidPath { param([string]$Name) return (Join-Path $pidDir "$Name.pid") }
function Get-LogPath { param([string]$Name) return (Join-Path $logDir "$Name.log") }

function Test-PidAlive {
    param([string]$PidFile)
    if (-not (Test-Path $PidFile)) { return $false }
    $pid = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $pid) { return $false }
    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
    return ($null -ne $proc)
}

function Stop-ServiceProcess {
    param([string]$Name)
    $pidFile = Get-PidPath $Name
    if (-not (Test-Path $pidFile)) {
        Write-Host "$Name: not running"
        return
    }
    $pid = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $pid) {
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        Write-Host "$Name: stale pid file removed"
        return
    }
    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "$Name: stopping (pid $pid)"
        Stop-Process -Id $pid -Force
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    Write-Host "$Name: stopped"
}

function Start-ServiceProcess {
    param([string]$Name, [string]$Cmd)
    if (-not $Cmd) { throw "$Name: missing start command" }
    Ensure-DevDirs
    $logFile = Get-LogPath $Name
    if (-not (Test-Path $logFile)) { New-Item -ItemType File -Path $logFile -Force | Out-Null }
    Write-Host "$Name: starting"
    $proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $Cmd -RedirectStandardOutput $logFile -RedirectStandardError $logFile -PassThru
    $proc.Id | Set-Content -Path (Get-PidPath $Name) -Encoding ASCII
    $Cmd | Set-Content -Path (Join-Path $stateDir "$Name.cmd") -Encoding ASCII
    Write-Host "$Name: started (pid $($proc.Id))"
}

function Test-PortFree {
    param([int]$Port)
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        $listener.Stop()
        return $true
    } catch {
        return $false
    }
}

function Test-PortOpen {
    param([int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect("127.0.0.1", $Port)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Get-PortOwnerPid {
    param([int]$Port)
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn) { return $conn.OwningProcess }
    } catch {
        return $null
    }
    return $null
}

function Test-HealthUrl {
    param([string]$Url)
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return ($resp.StatusCode -lt 400)
    } catch {
        return $false
    }
}

function Check-Ready {
    param([string]$Name, [string]$PortVar, [string]$HealthVar)
    $pidFile = Get-PidPath $Name
    if (-not (Test-PidAlive $pidFile)) { return $false }
    $port = $env:$PortVar
    $health = $env:$HealthVar
    if ($health) { return (Test-HealthUrl $health) }
    if ($port) { return (Test-PortOpen -Port ([int]$port)) }
    return $true
}

function Wait-Ready {
    param([string]$Name, [string]$PortVar, [string]$HealthVar)
    $timeout = 20
    if ($env:DEV_READY_TIMEOUT) { $timeout = [int]$env:DEV_READY_TIMEOUT }
    for ($i = 0; $i -lt $timeout; $i++) {
        if (Check-Ready -Name $Name -PortVar $PortVar -HealthVar $HealthVar) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Service-Up {
    param([string]$Name, [string]$CmdVar, [string]$PortVar, [string]$HealthVar)
    $pidFile = Get-PidPath $Name
    if (Test-PidAlive $pidFile) {
        if (Check-Ready -Name $Name -PortVar $PortVar -HealthVar $HealthVar) {
            Write-Host "$Name: already running"
            return
        }
        Write-Host "$Name: running but not ready, restarting"
        Stop-ServiceProcess $Name
    }
    $cmd = $env:$CmdVar
    if (-not $cmd) { throw "$Name: start command unknown. Set $CmdVar in ops/dev/common.env" }
    Start-ServiceProcess -Name $Name -Cmd $cmd
    if (-not (Wait-Ready -Name $Name -PortVar $PortVar -HealthVar $HealthVar)) {
        throw "$Name: failed to become ready"
    }
    Write-Host "$Name: ready"
}

function Convert-ToWslPath {
    param([string]$Path)
    if ($env:DEV_WSL_CWD) { return $env:DEV_WSL_CWD }
    if ($Path -match "^([A-Za-z]):\\(.*)$") {
        $drive = $matches[1].ToLower()
        $rest = $matches[2] -replace "\\", "/"
        return "/mnt/$drive/$rest"
    }
    return ($Path -replace "\\", "/")
}

function Quote-BashArg {
    param([string]$Arg)
    return "'" + ($Arg -replace "'", "'\"'\"'") + "'"
}

function Invoke-WslDev {
    param([string]$Verb, [string[]]$Args)
    $wslPath = Convert-ToWslPath $repoRoot
    $parts = @("cd $(Quote-BashArg $wslPath)", "&&", "./dev.sh", (Quote-BashArg $Verb))
    foreach ($arg in $Args) {
        $parts += (Quote-BashArg $arg)
    }
    $cmd = $parts -join " "
    & wsl.exe -e bash -lc $cmd
    exit $LASTEXITCODE
}

function Local-Doctor {
    Load-Env
    Ensure-DevDirs

    $fails = 0
    function Check-File([string]$Path, [string]$Label) {
        if (Test-Path $Path) { Write-Host "PASS $Label" } else { Write-Host "FAIL $Label"; $script:fails++ }
    }

    Check-File (Join-Path $repoRoot "DEV_HARNESS.md") "DEV_HARNESS.md present"
    Check-File (Join-Path $repoRoot "dev.sh") "dev.sh present"
    Check-File (Join-Path $repoRoot "dev.ps1") "dev.ps1 present"
    Check-File (Join-Path $repoRoot "ops\dev\common.env.example") "ops/dev/common.env.example present"
    Check-File (Join-Path $repoRoot "ops\dev\ports.env.example") "ops/dev/ports.env.example present"

    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Write-Host "FAIL python not found (required for this repo)"
        $fails++
    } else {
        $ver = & python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
        $parts = $ver.Split(".")
        if ([int]$parts[0] -gt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10)) {
            Write-Host "PASS python >= 3.10 ($ver)"
        } else {
            Write-Host "FAIL python < 3.10 ($ver)"
            $fails++
        }
    }

    if ($env:DEV_BACKEND_PORT) {
        $port = [int]$env:DEV_BACKEND_PORT
        if (Test-PortFree -Port $port) {
            Write-Host "PASS backend port $port is free"
        } else {
            $owner = Get-PortOwnerPid -Port $port
            $pidFile = Get-PidPath "backend"
            if ($owner -and (Test-Path $pidFile)) {
                $expected = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($expected -eq $owner) {
                    Write-Host "PASS backend port $port in use by expected pid $owner"
                } else {
                    Write-Host "FAIL backend port $port in use by pid $owner (expected $expected)"
                    $fails++
                }
            } else {
                Write-Host "FAIL backend port $port is in use"
                $fails++
            }
        }
    }

    if ($env:DEV_UI_PORT) {
        $port = [int]$env:DEV_UI_PORT
        if (Test-PortFree -Port $port) {
            Write-Host "PASS ui port $port is free"
        } else {
            $owner = Get-PortOwnerPid -Port $port
            $pidFile = Get-PidPath "ui"
            if ($owner -and (Test-Path $pidFile)) {
                $expected = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($expected -eq $owner) {
                    Write-Host "PASS ui port $port in use by expected pid $owner"
                } else {
                    Write-Host "FAIL ui port $port in use by pid $owner (expected $expected)"
                    $fails++
                }
            } else {
                Write-Host "FAIL ui port $port is in use"
                $fails++
            }
        }
    }

    if ($fails -gt 0) { exit 2 }
    exit 0
}

function Local-Up { Load-Env; Ensure-DevDirs; Service-Up -Name "backend" -CmdVar "DEV_BACKEND_CMD" -PortVar "DEV_BACKEND_PORT" -HealthVar "DEV_BACKEND_HEALTH_URL" }
function Local-Down { Load-Env; Ensure-DevDirs; Stop-ServiceProcess "backend"; Stop-ServiceProcess "ui" }
function Local-Logs([string]$Service, [string]$Follow) {
    Ensure-DevDirs
    if (-not $Service) { $Service = "backend" }
    $logFile = Get-LogPath $Service
    if (-not (Test-Path $logFile)) { throw "$Service: no log file at $logFile" }
    if ($Follow -eq "-f" -or $Follow -eq "--follow") { Get-Content $logFile -Tail 200 -Wait } else { Get-Content $logFile -Tail 200 }
}
function Local-Test { & (Join-Path $repoRoot "tools\run_all_tests.ps1") }
function Local-Fmt {
    Load-Env
    if (-not $env:DEV_FMT_CMD) { throw "formatter not configured. Set DEV_FMT_CMD in ops/dev/common.env" }
    & cmd.exe /c $env:DEV_FMT_CMD
}
function Local-Reset { Local-Down; if (Test-Path $devDir) { Remove-Item $devDir -Recurse -Force } Write-Host "reset: cleared $devDir" }
function Local-Ui {
    Load-Env
    Ensure-DevDirs
    if (-not (Test-UiDetected)) {
        Write-Host "No UI detected (no package.json or ui/frontend/client/web/apps directory)"
        exit 2
    }
    if (-not $env:DEV_UI_CMD) { throw "UI detected but launch command unclear. Set DEV_UI_CMD in ops/dev/common.env" }
    Service-Up -Name "ui" -CmdVar "DEV_UI_CMD" -PortVar "DEV_UI_PORT" -HealthVar "DEV_UI_HEALTH_URL"
}

$useWsl = $true
if ($env:DEV_USE_WSL -eq "0") { $useWsl = $false }

switch ($Verb) {
    "doctor" {
        if ($useWsl) {
            if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { throw "WSL not available. Set DEV_USE_WSL=0 or install WSL." }
            Invoke-WslDev -Verb "doctor" -Args $Args
        } else {
            Local-Doctor
        }
    }
    "up" {
        if ($useWsl) {
            Invoke-WslDev -Verb "up" -Args $Args
        } else {
            Local-Up
        }
    }
    "down" {
        if ($useWsl) {
            Invoke-WslDev -Verb "down" -Args $Args
        } else {
            Local-Down
        }
    }
    "logs" {
        if ($useWsl) {
            Invoke-WslDev -Verb "logs" -Args $Args
        } else {
            $service = $null; $follow = $null
            if ($Args.Length -gt 0) { $service = $Args[0] }
            if ($Args.Length -gt 1) { $follow = $Args[1] }
            Local-Logs -Service $service -Follow $follow
        }
    }
    "test" {
        if ($useWsl) {
            Invoke-WslDev -Verb "test" -Args $Args
        } else {
            Local-Test
        }
    }
    "fmt" {
        if ($useWsl) {
            Invoke-WslDev -Verb "fmt" -Args $Args
        } else {
            Local-Fmt
        }
    }
    "reset" {
        if ($useWsl) {
            Invoke-WslDev -Verb "reset" -Args $Args
        } else {
            Local-Reset
        }
    }
    "ui" {
        if (-not (Test-UiDetected)) {
            Write-Host "No UI detected (no package.json or ui/frontend/client/web/apps directory)"
            exit 2
        }
        if ($useWsl) {
            Invoke-WslDev -Verb "up" -Args @()
            if (-not $env:DEV_UI_CMD) { throw "UI detected but launch command unclear. Set DEV_UI_CMD in ops/dev/common.env" }
            & cmd.exe /c $env:DEV_UI_CMD
        } else {
            Local-Ui
        }
    }
    "help" { Write-Host "Usage: .\\dev.ps1 <verb> [args]" }
    default {
        Write-Host "Unknown verb: $Verb"
        Write-Host "Usage: .\\dev.ps1 <verb> [args]"
        exit 2
    }
}
