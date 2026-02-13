param(
  [string]$Branch = "soak/24h-20260209"
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
Set-Location $Root

# Keep repo clean and ensure the branch is published before running soak.
& git status --porcelain | Out-Null
if ($LASTEXITCODE -ne 0) { throw "git status failed (is git installed?)" }
$dirty = (& git status --porcelain) | Out-String
if ($dirty.Trim().Length -gt 0) { throw "git worktree is dirty; commit/stash before running soak." }

& git push | Out-Null
if ($LASTEXITCODE -ne 0) { throw "git push failed" }

& powershell -ExecutionPolicy Bypass -File (Join-Path $Root "tools\\soak\\update_and_run_24h_soak.ps1") -Branch $Branch
exit $LASTEXITCODE

