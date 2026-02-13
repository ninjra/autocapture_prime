#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_REPORT="$(find "$ROOT/artifacts/single_image_runs" -maxdepth 2 -type f -name report.json -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)"

if [[ -z "$RUN_REPORT" || ! -f "$RUN_REPORT" ]]; then
  echo "ERROR: No single-image report found under artifacts/single_image_runs." >&2
  exit 2
fi

OUT_PATH="${1:-$(dirname "$RUN_REPORT")/workflow_tree.md}"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$ROOT/.venv/bin/python" "$ROOT/tools/export_run_workflow_tree.py" --input "$RUN_REPORT" --out "$OUT_PATH"
