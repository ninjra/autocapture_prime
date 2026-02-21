#!/usr/bin/env bash
set -euo pipefail

echo "DEPRECATED: local vLLM lifecycle is owned by the sidecar/hypervisor."
echo "This repo only consumes an external localhost endpoint at 127.0.0.1:8000."
echo "Use services/vllm/health.sh to verify readiness."
exit 2
