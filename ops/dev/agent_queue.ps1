param(
  [string]$QueuePath = "",
  [switch]$Watch,
  [int]$PollSeconds = 2,
  [switch]$AutoApprove,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
$devDir = Join-Path $Root ".dev"
$logDir = Join-Path $devDir "logs"
if (-not (Test-Path $logDir)) { New-Item -Path $logDir -ItemType Directory -Force | Out-Null }
$logPath = Join-Path $logDir "agent_queue.log"
$resultsPath = Join-Path $devDir "agent_queue.results.json"

if (-not $QueuePath) {
  $QueuePath = Join-Path $devDir "agent_queue.json"
}

function Write-Log {
  param([string]$Message)
  $timestamp = (Get-Date).ToString("s")
  $line = "[$timestamp] $Message"
  $line | Tee-Object -FilePath $logPath -Append | Out-Host
}

function Test-DeleteCommand {
  param([string]$CommandText)
  if (-not $CommandText) { return $false }
  $normalized = $CommandText
  $normalized = $normalized -replace "``", ""
  $normalized = $normalized -replace "`"", ""
  $normalized = $normalized -replace "'", ""
  $patterns = @(
    "(?i)\\bdel\\b",
    "(?i)\\berase\\b",
    "(?i)\\brmdir\\b",
    "(?i)\\brd\\b",
    "(?i)\\brm\\b",
    "(?i)\\brimraf\\b",
    "(?i)\\bremove-item\\b",
    "(?i)\\bremove-childitem\\b",
    "(?i)\\bremove-itemproperty\\b",
    "(?i)\\bclear-content\\b",
    "(?i)\\bclear-item\\b",
    "(?i)\\bclear-itemproperty\\b",
    "(?i)\\bremove-\\w+\\b",
    "(?i)\\btruncate\\b",
    "(?i)\\bgit\\s+clean\\b",
    "(?i)\\bgit\\s+reset\\s+--hard\\b"
  )
  foreach ($pattern in $patterns) {
    if ($normalized -match $pattern) { return $true }
  }
  return $false
}

function Load-Queue {
  if (-not (Test-Path $QueuePath)) {
    Write-Log "Queue file not found: $QueuePath"
    return $null
  }
  try {
    $raw = Get-Content $QueuePath -Raw
    if (-not $raw.Trim()) { return $null }
    return ($raw | ConvertFrom-Json)
  } catch {
    Write-Log ("Queue parse failed: " + $_.Exception.Message)
    return $null
  }
}

function Save-Results {
  param([object]$Results)
  try {
    ($Results | ConvertTo-Json -Depth 8) | Set-Content -Path $resultsPath -Encoding UTF8
  } catch {
    Write-Log ("Failed to write results: " + $_.Exception.Message)
  }
}

function Confirm-Step {
  param([string]$Id, [string]$CommandText)
  if ($AutoApprove) { return $true }
  Write-Host ""
  Write-Host "Ready to run step: $Id"
  Write-Host "Command: $CommandText"
  while ($true) {
    $resp = Read-Host "Run this step? (Y/N or 1/0)"
    if ($resp -match "^(?i)(y|yes|1)$") { return $true }
    if ($resp -match "^(?i)(n|no|0)$") { return $false }
  }
}

function Invoke-Step {
  param([pscustomobject]$Step, [hashtable]$Results)
  $id = $Step.id
  if (-not $id) { $id = ("step_{0}" -f ([guid]::NewGuid().ToString("N"))) }
  $cmd = [string]$Step.command
  $cwd = [string]$Step.cwd
  $shell = [string]$Step.shell
  if (-not $shell) { $shell = "powershell" }
  if (-not $cmd) {
    Write-Log "Skipping empty command for $id"
    $Results[$id] = @{ status = "skipped"; reason = "empty_command" }
    return
  }
  if (Test-DeleteCommand $cmd) {
    Write-Log "Blocked delete command for $id"
    $Results[$id] = @{ status = "blocked"; reason = "delete_command" }
    return
  }
  if (-not (Confirm-Step -Id $id -CommandText $cmd)) {
    Write-Log "Skipped by user: $id"
    $Results[$id] = @{ status = "skipped"; reason = "user_skip" }
    return
  }
  if ($DryRun) {
    Write-Log "Dry run: $id"
    $Results[$id] = @{ status = "dry_run" }
    return
  }
  if ($cwd) {
    if (-not (Test-Path $cwd)) {
      Write-Log ("Invalid cwd for {0}: {1}" -f $id, $cwd)
      $Results[$id] = @{ status = "failed"; reason = "cwd_missing" }
      return
    }
    Push-Location $cwd
  }
  try {
    Write-Log "Running step: $id"
    $output = @()
    $exitCode = 0
    if ($shell -eq "cmd") {
      $output = & cmd.exe /c $cmd 2>&1
      $exitCode = $LASTEXITCODE
    } elseif ($shell -eq "pwsh") {
      $output = & pwsh -NoProfile -Command $cmd 2>&1
      $exitCode = $LASTEXITCODE
    } else {
      $output = & powershell -NoProfile -ExecutionPolicy Bypass -Command $cmd 2>&1
      $exitCode = $LASTEXITCODE
    }
    $output | Tee-Object -FilePath $logPath -Append | Out-Host
    if ($exitCode -ne 0) {
      Write-Log "Step failed ($id) exit=$exitCode"
      $Results[$id] = @{ status = "failed"; exit_code = $exitCode }
      return
    }
    Write-Log "Step complete: $id"
    $Results[$id] = @{ status = "ok"; exit_code = 0 }
  } finally {
    if ($cwd) { Pop-Location }
  }
}

function Run-QueueOnce {
  $queue = Load-Queue
  if (-not $queue) { return }
  $steps = $queue.steps
  if (-not $steps) {
    Write-Log "Queue has no steps."
    return
  }
  $results = @{}
  foreach ($step in $steps) {
    Invoke-Step -Step $step -Results $results
    Save-Results -Results $results
  }
}

if ($Watch) {
  Write-Log "Watching queue: $QueuePath"
  while ($true) {
    Run-QueueOnce
    Start-Sleep -Seconds $PollSeconds
  }
} else {
  Run-QueueOnce
}
