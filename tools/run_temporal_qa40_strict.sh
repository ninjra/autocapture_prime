#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

REPORT="${1:-}"
if [[ -z "$REPORT" ]]; then
  REPORT="$ROOT/artifacts/single_image_runs/latest/report.json"
fi
if [[ ! -f "$REPORT" ]]; then
  echo "{\"ok\":false,\"error\":\"report_not_found\",\"report\":\"$REPORT\"}"
  exit 2
fi

OUT_DIR="$ROOT/artifacts/temporal40"
mkdir -p "$OUT_DIR"

RUN_OUT="$OUT_DIR/temporal40_${STAMP}.json"
GATE_OUT="$OUT_DIR/temporal40_gate_${STAMP}.json"
SEMANTIC_OUT="$OUT_DIR/temporal40_semantic_gate_${STAMP}.json"

"$PY" "$ROOT/tools/run_advanced10_queries.py" \
  --report "$REPORT" \
  --cases "$ROOT/docs/query_eval_cases_temporal_screenshot_qa_40.json" \
  --metadata-only \
  --output "$RUN_OUT"

"$PY" "$ROOT/tools/gate_q40_strict.py" \
  --report "$RUN_OUT" \
  --output "$GATE_OUT" \
  --expected-evaluated 40 \
  --expected-skipped 0 \
  --expected-failed 0

set +e
"$PY" "$ROOT/tools/gate_temporal40_semantic.py" \
  --report "$RUN_OUT" \
  --cases "$ROOT/docs/query_eval_cases_temporal_screenshot_qa_40.json" \
  --output "$SEMANTIC_OUT" \
  --expected-passed 40
SEMANTIC_RC=$?
set -e

cp "$RUN_OUT" "$OUT_DIR/temporal40_latest.json"
cp "$GATE_OUT" "$OUT_DIR/temporal40_gate_latest.json"
cp "$SEMANTIC_OUT" "$OUT_DIR/temporal40_semantic_gate_latest.json"

echo "{\"ok\":true,\"report\":\"$RUN_OUT\",\"gate\":\"$GATE_OUT\",\"semantic_gate\":\"$SEMANTIC_OUT\"}"
exit "$SEMANTIC_RC"
