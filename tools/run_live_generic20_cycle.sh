#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
CAPTURE_DIR="$ROOT/artifacts/live_captures"
RUN_DIR="$ROOT/artifacts/advanced10"
mkdir -p "$CAPTURE_DIR" "$RUN_DIR"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
IMAGE_PATH="$CAPTURE_DIR/live_${STAMP}.png"
WINDOWS_IMAGE_PATH="$(wslpath -w "$IMAGE_PATH")"
SCREENSHOT_PS1=""
for candidate in \
  "$ROOT/.codex/skills/screenshot/scripts/take_screenshot.ps1" \
  "$HOME/.codex/skills/screenshot/scripts/take_screenshot.ps1"
do
  if [[ -f "$candidate" ]]; then
    SCREENSHOT_PS1="$candidate"
    break
  fi
done
if [[ -z "$SCREENSHOT_PS1" ]]; then
  echo "{\"ok\":false,\"error\":\"screenshot_skill_missing\"}"
  exit 1
fi
SCREENSHOT_PS1_WIN="$(wslpath -w "$SCREENSHOT_PS1")"

# Screenshot skill (Windows helper) for full virtual desktop capture.
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe \
  -NoProfile \
  -ExecutionPolicy Bypass \
  -File "$SCREENSHOT_PS1_WIN" \
  -Path "$WINDOWS_IMAGE_PATH" >/tmp/autocapture_prime_live_capture.out

IDLE_STEPS="${AUTOCAPTURE_LIVE_IDLE_STEPS:-8}"
IDLE_BUDGET_MS="${AUTOCAPTURE_LIVE_IDLE_BUDGET_MS:-60000}"
PROCESS_JSON="$($PY "$ROOT/tools/process_single_screenshot.py" --image "$IMAGE_PATH" --synthetic-hid rich --max-idle-steps "$IDLE_STEPS" --budget-ms "$IDLE_BUDGET_MS")"
REPORT_PATH="$($PY -c 'import json,sys; print(json.loads(sys.argv[1]).get("report",""))' "$PROCESS_JSON")"
if [[ -z "$REPORT_PATH" || ! -f "$REPORT_PATH" ]]; then
  echo "{\"ok\":false,\"error\":\"missing_report\",\"process\":$PROCESS_JSON}"
  exit 1
fi

ADV_OUT="$RUN_DIR/generic20_${STAMP}.json"
CASES_PATH="${AUTOCAPTURE_GENERIC20_CASES_PATH:-$ROOT/docs/query_eval_cases_generic20.json}"
QUERY_TIMEOUT_S="${AUTOCAPTURE_GENERIC20_QUERY_TIMEOUT_S:-45}"
REPRO_RUNS="${AUTOCAPTURE_GENERIC20_REPRO_RUNS:-1}"
SKIP_EVAL="${AUTOCAPTURE_GENERIC20_SKIP_EVAL:-0}"
if [[ "$SKIP_EVAL" != "1" ]]; then
  $PY "$ROOT/tools/run_advanced10_queries.py" --report "$REPORT_PATH" --cases "$CASES_PATH" --metadata-only --query-timeout-s "$QUERY_TIMEOUT_S" --repro-runs "$REPRO_RUNS" --output "$ADV_OUT" >/tmp/autocapture_prime_generic20_eval.out
else
  ADV_OUT=""
fi

echo "{\"ok\":true,\"image\":\"$IMAGE_PATH\",\"report\":\"$REPORT_PATH\",\"generic20\":\"$ADV_OUT\"}"
