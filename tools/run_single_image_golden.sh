#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_PATH="$ROOT/artifacts/test_input_qh.png"
PROFILE_PATH="$ROOT/config/profiles/golden_full.json"
BUDGET_MS="${AUTOCAPTURE_GOLDEN_BUDGET_MS:-90000}"
MAX_IDLE_STEPS="${AUTOCAPTURE_GOLDEN_MAX_IDLE_STEPS:-4}"
if [[ $# -ge 1 ]]; then
  IMAGE_PATH="$1"
  shift
fi
if [[ $# -ge 1 && "${1:-}" != --* ]]; then
  PROFILE_PATH="$1"
  shift
fi

vlm_flag=""
for arg in "$@"; do
  if [[ "$arg" == "--skip-vllm-unstable" || "$arg" == "--fail-on-vllm-unstable" ]]; then
    vlm_flag="$arg"
    break
  fi
done
if [[ -z "$vlm_flag" ]]; then
  skip_vlm_unstable="${AUTOCAPTURE_SKIP_VLM_UNSTABLE:-1}"
  case "${skip_vlm_unstable,,}" in
    1|true|yes|on) vlm_flag="--skip-vllm-unstable" ;;
    *) vlm_flag="--fail-on-vllm-unstable" ;;
  esac
fi

exec "$ROOT/.venv/bin/python" "$ROOT/tools/process_single_screenshot.py" \
  --image "$IMAGE_PATH" \
  --profile "$PROFILE_PATH" \
  --force-idle \
  --budget-ms "$BUDGET_MS" \
  --max-idle-steps "$MAX_IDLE_STEPS" \
  "$vlm_flag" \
  "$@"
