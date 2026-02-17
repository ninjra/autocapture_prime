#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_PATH="${1:-$ROOT/artifacts/test_input_qh.png}"
PROFILE_PATH="${2:-$ROOT/config/profiles/golden_full.json}"
BUDGET_MS="${AUTOCAPTURE_GOLDEN_BUDGET_MS:-90000}"
MAX_IDLE_STEPS="${AUTOCAPTURE_GOLDEN_MAX_IDLE_STEPS:-4}"
SHIFTED=0
if [[ $# -ge 1 ]]; then
  SHIFTED=1
fi
if [[ $# -ge 2 ]]; then
  SHIFTED=2
fi
if [[ $SHIFTED -gt 0 ]]; then
  shift "$SHIFTED"
fi

exec "$ROOT/.venv/bin/python" "$ROOT/tools/process_single_screenshot.py" \
  --image "$IMAGE_PATH" \
  --profile "$PROFILE_PATH" \
  --force-idle \
  --budget-ms "$BUDGET_MS" \
  --max-idle-steps "$MAX_IDLE_STEPS" \
  "$@"
