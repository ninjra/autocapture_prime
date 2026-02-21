#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

DATAROOT="${1:-/mnt/d/autocapture}"
VLLM_BASE="${2:-http://127.0.0.1:8000}"

"$PY" "$ROOT/tools/preflight_live_stack.py" \
  --dataroot "$DATAROOT" \
  --vllm-base-url "$VLLM_BASE" \
  --output "$ROOT/artifacts/live_stack/preflight_latest.json" >/tmp/autocapture_prime_baseline_preflight.out || true

"$PY" "$ROOT/tools/validate_live_chronicle_stack.py" \
  --dataroot "$DATAROOT" \
  --vllm-base-url "$VLLM_BASE" \
  --output "$ROOT/artifacts/live_stack/validation_latest.json" >/tmp/autocapture_prime_baseline_validation.out || true

"$PY" "$ROOT/tools/generate_baseline_snapshot.py" \
  --output "artifacts/baseline/baseline_snapshot_latest.json"

