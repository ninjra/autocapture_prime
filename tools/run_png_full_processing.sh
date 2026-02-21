#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_ARG="${1:-}"
CASES_ARG="${2:-$ROOT/docs/query_eval_cases.json}"

if [[ -z "${IMAGE_ARG}" ]]; then
  # Default to newest PNG in docs/test sample.
  IMAGE_ARG="$(ls -1t "$ROOT/docs/test sample"/*.png 2>/dev/null | head -n 1 || true)"
fi
if [[ -z "${IMAGE_ARG}" || ! -f "${IMAGE_ARG}" ]]; then
  echo "ERROR: PNG not found. Pass image path as arg1." >&2
  exit 2
fi

echo "image=${IMAGE_ARG}"
RUN_JSON="$(
  "$ROOT/.venv/bin/python" "$ROOT/tools/process_single_screenshot.py" --image "${IMAGE_ARG}" --budget-ms 30000 --query "what song is playing"
)"
echo "${RUN_JSON}"
REPORT_PATH="$(
  RUN_JSON_PAYLOAD="${RUN_JSON}" "$ROOT/.venv/bin/python" -c 'import json,os; obj=json.loads(os.environ.get("RUN_JSON_PAYLOAD","{}")); print(str(obj.get("report","")).strip())'
)"
if [[ -n "${REPORT_PATH}" && -f "${REPORT_PATH}" ]]; then
  CFG_DIR="$(
    REPORT_PATH_INPUT="${REPORT_PATH}" "$ROOT/.venv/bin/python" -c 'import json,os; p=os.environ.get("REPORT_PATH_INPUT",""); doc=json.loads(open(p,encoding="utf-8").read()) if p else {}; print(str(doc.get("config_dir","")).strip())'
  )"
  DATA_DIR="$(
    REPORT_PATH_INPUT="${REPORT_PATH}" "$ROOT/.venv/bin/python" -c 'import json,os; p=os.environ.get("REPORT_PATH_INPUT",""); doc=json.loads(open(p,encoding="utf-8").read()) if p else {}; print(str(doc.get("data_dir","")).strip())'
  )"
  AUTOCAPTURE_CONFIG_DIR="${CFG_DIR}" AUTOCAPTURE_DATA_DIR="${DATA_DIR}" "$ROOT/.venv/bin/python" "$ROOT/tools/query_eval_suite.py" --cases "${CASES_ARG}" || true
else
  echo "WARN: report not found; skipping query_eval_suite" >&2
fi
