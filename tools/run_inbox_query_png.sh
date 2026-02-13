#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMG="${1:-$ROOT/docs/test sample/Screenshot 2026-02-02 113519.png}"
CASES="${2:-$ROOT/docs/query_eval_cases.json}"

RUN_JSON="$("$ROOT/.venv/bin/python" "$ROOT/tools/process_single_screenshot.py" --image "$IMG" --query "how many inboxes do i have open" --force-idle --budget-ms 30000)"
echo "$RUN_JSON"

REPORT_PATH="$(RUN_JSON_PAYLOAD="$RUN_JSON" "$ROOT/.venv/bin/python" -c 'import json,os; obj=json.loads(os.environ.get("RUN_JSON_PAYLOAD","{}")); print(str(obj.get("report","")).strip())')"
if [[ -z "$REPORT_PATH" || ! -f "$REPORT_PATH" ]]; then
  echo "ERROR: missing report path from process_single_screenshot output" >&2
  exit 2
fi

CFG_DIR="$(REPORT_PATH_INPUT="$REPORT_PATH" "$ROOT/.venv/bin/python" -c 'import json,os; p=os.environ.get("REPORT_PATH_INPUT",""); doc=json.loads(open(p,encoding="utf-8").read()) if p else {}; print(str(doc.get("config_dir","")).strip())')"
DATA_DIR="$(REPORT_PATH_INPUT="$REPORT_PATH" "$ROOT/.venv/bin/python" -c 'import json,os; p=os.environ.get("REPORT_PATH_INPUT",""); doc=json.loads(open(p,encoding="utf-8").read()) if p else {}; print(str(doc.get("data_dir","")).strip())')"

if [[ -z "$CFG_DIR" || -z "$DATA_DIR" ]]; then
  echo "ERROR: report missing config_dir/data_dir" >&2
  exit 2
fi

AUTOCAPTURE_CONFIG_DIR="$CFG_DIR" AUTOCAPTURE_DATA_DIR="$DATA_DIR" "$ROOT/.venv/bin/python" "$ROOT/tools/query_eval_suite.py" --cases "$CASES"
