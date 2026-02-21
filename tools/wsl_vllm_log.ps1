param()

$msg = @(
    "DEPRECATED: local WSL vLLM log tail removed from this repo.",
    "vLLM lifecycle/logging is owned by sidecar/hypervisor repo.",
    "Only external endpoint http://127.0.0.1:8000 is consumed here."
)
$msg | ForEach-Object { Write-Host $_ }
exit 3
