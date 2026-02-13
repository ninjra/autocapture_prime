#!/usr/bin/env bash
set -euo pipefail

HOST="127.0.0.1"
PORT="${1:-8000}"
BASE_URL="http://${HOST}:${PORT}"

echo "probe_base_url=${BASE_URL}"

if ! curl -fsS --max-time 3 "${BASE_URL}/health" >/dev/null; then
  echo "ok=false error=health_unreachable"
  echo "hint=start_vllm_in_sidecar_repo_on_${HOST}:${PORT}"
  exit 1
fi

models_json="$(curl -fsS --max-time 4 "${BASE_URL}/v1/models")" || {
  echo "ok=false error=models_unreachable"
  exit 1
}

echo "ok=true"
echo "${models_json}"
