param()

$msg = @(
    "DEPRECATED: local vLLM startup was removed from this repo.",
    "This repo consumes external vLLM only at http://127.0.0.1:8000.",
    "Start/manage vLLM from the sidecar/hypervisor repo."
)
$msg | ForEach-Object { Write-Host $_ }
exit 3
