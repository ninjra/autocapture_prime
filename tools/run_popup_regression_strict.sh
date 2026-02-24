#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
OUT="${1:-$ROOT/artifacts/query_acceptance/popup_regression_latest.json}"
MISSES="${2:-$ROOT/artifacts/query_acceptance/popup_regression_misses_latest.json}"
CASES="${POPUP_REGRESSION_CASES_PATH:-$ROOT/docs/query_eval_cases_popup_regression.json}"
TIMEOUT_S="${AUTOCAPTURE_POPUP_ACCEPT_TIMEOUT_S:-45}"

"$PY" "$ROOT/tools/run_popup_blind_acceptance.py" \
  --cases "$CASES" \
  --all-cases \
  --timeout-s "$TIMEOUT_S" \
  --out "$OUT" \
  --misses-out "$MISSES" \
  --strict
