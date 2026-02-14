#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_PATH="${1:-$ROOT/artifacts/test_input_qh.png}"
CASES_PATH="${2:-$ROOT/docs/query_eval_cases_advanced20.json}"
TRACE_OUT="${3:-$ROOT/docs/reports/question-validation-plugin-trace-2026-02-13.md}"

health_json="$(curl -sS --max-time 3 http://127.0.0.1:8000/v1/models || true)"
if [[ -z "${health_json}" ]]; then
  echo "{\"ok\":false,\"error\":\"vllm_unreachable\",\"base_url\":\"http://127.0.0.1:8000\"}"
  exit 2
fi

before_latest="$(ls -1t "$ROOT/artifacts/single_image_runs" 2>/dev/null | head -n 1 || true)"

set +e
process_out="$("$ROOT/tools/run_single_image_golden.sh" "$IMAGE_PATH" 2>&1)"
process_rc=$?
set -e

if [[ $process_rc -ne 0 ]]; then
  after_latest="$(ls -1t "$ROOT/artifacts/single_image_runs" 2>/dev/null | head -n 1 || true)"
  report_path=""
  if [[ -n "${after_latest}" ]]; then
    report_path="$ROOT/artifacts/single_image_runs/${after_latest}/report.json"
  fi
  err_detail=""
  if [[ -n "${report_path}" && -f "${report_path}" ]]; then
    err_detail="$("$ROOT/.venv/bin/python" -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('error',''))" "$report_path" 2>/dev/null || true)"
  fi
  echo "{\"ok\":false,\"error\":\"single_image_failed\",\"report\":\"${report_path}\",\"detail\":\"${err_detail}\"}"
  exit 1
fi

latest_run="$(ls -1t "$ROOT/artifacts/single_image_runs" | head -n 1)"
report_path="$ROOT/artifacts/single_image_runs/${latest_run}/report.json"

set +e
adv_out="$("$ROOT/.venv/bin/python" "$ROOT/tools/run_advanced10_queries.py" --report "$report_path" --cases "$CASES_PATH" --strict-all --query-timeout-s 25 --lock-retries 4 2>&1)"
adv_rc=$?
set -e

adv_json_path="$("$ROOT/.venv/bin/python" -c "import json,sys; txt=sys.argv[1].strip();\
import re;\
m=re.search(r'\\{.*\\}$', txt, re.S);\
print((json.loads(m.group(0)).get('output','') if m else ''))" "$adv_out" 2>/dev/null || true)"

if [[ -n "$adv_json_path" && -f "$adv_json_path" ]]; then
  "$ROOT/.venv/bin/python" "$ROOT/tools/generate_qh_plugin_validation_report.py" \
    --advanced-json "$adv_json_path" \
    --run-report "$report_path" \
    --out "$TRACE_OUT" >/dev/null
fi

summary_json="$("$ROOT/.venv/bin/python" - <<'PY' "$adv_json_path"
import json, pathlib, sys
p = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else pathlib.Path("")
if not p.exists():
    print(json.dumps({"evaluated_total": 0, "evaluated_passed": 0, "evaluated_failed": 0}))
    raise SystemExit(0)
d = json.loads(p.read_text(encoding="utf-8"))
print(json.dumps({
    "evaluated_total": int(d.get("evaluated_total", 0) or 0),
    "evaluated_passed": int(d.get("evaluated_passed", 0) or 0),
    "evaluated_failed": int(d.get("evaluated_failed", 0) or 0),
}))
PY
)"

echo "{\"ok\":true,\"report\":\"$report_path\",\"advanced\":\"$adv_json_path\",\"advanced_rc\":$adv_rc,\"summary\":$summary_json,\"trace\":\"$TRACE_OUT\"}"
exit "$adv_rc"
