#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_REPORT="$(find "$ROOT/artifacts/single_image_runs" -maxdepth 2 -type f -name report.json -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)"
OUT_DIR="${1:-$ROOT/artifacts/query_metrics/latest}"

if [[ -z "$RUN_REPORT" || ! -f "$RUN_REPORT" ]]; then
  echo "ERROR: No single-image report found under artifacts/single_image_runs." >&2
  exit 2
fi

DATA_DIR="$("$ROOT/.venv/bin/python" - <<'PY' "$RUN_REPORT"
import json,sys
p=str(sys.argv[1])
doc=json.load(open(p,encoding='utf-8'))
print(str(doc.get('data_dir','')).strip())
PY
)"
if [[ -z "$DATA_DIR" || ! -d "$DATA_DIR" ]]; then
  echo "ERROR: Data dir missing in report: $RUN_REPORT" >&2
  exit 2
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$ROOT/.venv/bin/python" "$ROOT/tools/query_effectiveness_report.py" --data-dir "$DATA_DIR" --out-dir "$OUT_DIR"
