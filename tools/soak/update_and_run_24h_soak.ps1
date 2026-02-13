param(
  [string]$Branch = "soak/24h-20260209"
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
Push-Location $Root
try {
  $dirty = (& git status --porcelain) | Out-String
  if ($dirty.Trim().Length -gt 0) {
    throw "git worktree is dirty; commit/stash before running soak."
  }
  & git fetch origin | Out-Null
  & git checkout $Branch | Out-Null
  & git pull --ff-only | Out-Null
  & powershell -ExecutionPolicy Bypass -File (Join-Path $Root "tools\\soak\\run_24h_soak.ps1")
} finally {
  Pop-Location
}

