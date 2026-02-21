param()

$msg = @(
    "DEPRECATED: this repo no longer installs or launches local vLLM.",
    "vLLM is now an external dependency served at http://127.0.0.1:8000.",
    "Use the sidecar/hypervisor repo for vLLM installation and lifecycle."
)
$msg | ForEach-Object { Write-Host $_ }
exit 3
