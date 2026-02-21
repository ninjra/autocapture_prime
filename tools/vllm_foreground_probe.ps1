param()

$msg = @(
    "DEPRECATED: foreground local vLLM probe removed.",
    "This repo only probes external vLLM at http://127.0.0.1:8000.",
    "Run sidecar repo diagnostics for local vLLM process issues."
)
$msg | ForEach-Object { Write-Host $_ }
exit 3
