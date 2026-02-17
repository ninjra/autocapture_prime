#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_PATH="${1:-$ROOT/artifacts/test_input_qh.png}"
CASES_PATH="${2:-$ROOT/docs/query_eval_cases_advanced20.json}"
TRACE_OUT="${3:-$ROOT/docs/reports/question-validation-plugin-trace-2026-02-13.md}"
LOCKFILE="${AUTOCAPTURE_GOLDEN_LOCKFILE:-/tmp/autocapture_prime_golden_qh.lock}"
PIDFILE="${LOCKFILE}.pid"
STATUSFILE="${AUTOCAPTURE_GOLDEN_STATUSFILE:-/tmp/autocapture_prime_golden_qh.status.json}"

mkdir -p "$(dirname "$LOCKFILE")" "$(dirname "$STATUSFILE")"
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  holder_pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -z "${holder_pid}" ]]; then
    holder_pid="unknown"
  fi
  echo "{\"ok\":false,\"error\":\"job_already_running\",\"pid\":\"${holder_pid}\",\"lockfile\":\"${LOCKFILE}\"}"
  exit 3
fi
echo "$$" > "$PIDFILE"

write_status() {
  local phase="$1"
  local detail="${2:-}"
  printf '{"ok":false,"pid":%s,"phase":"%s","detail":"%s","image":"%s","cases":"%s"}\n' \
    "$$" "$phase" "$detail" "$IMAGE_PATH" "$CASES_PATH" > "$STATUSFILE"
}

cleanup_job() {
  rm -f "$PIDFILE" 2>/dev/null || true
}
trap cleanup_job EXIT
write_status "start" "lock_acquired"

if [[ -z "${AUTOCAPTURE_VLM_API_KEY:-}" ]]; then
  maybe_key="$("$ROOT/.venv/bin/python" - <<'PY'
import json, pathlib
path = pathlib.Path("config/user.json")
if not path.exists():
    print("")
    raise SystemExit(0)
try:
    raw = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print("")
    raise SystemExit(0)
plugins = raw.get("plugins", {}) if isinstance(raw, dict) else {}
settings = plugins.get("settings", {}) if isinstance(plugins, dict) else {}
vlm = settings.get("builtin.vlm.vllm_localhost", {}) if isinstance(settings, dict) else {}
print(str(vlm.get("api_key") or "").strip())
PY
)"
  if [[ -n "${maybe_key}" ]]; then
    export AUTOCAPTURE_VLM_API_KEY="${maybe_key}"
  fi
fi

export AUTOCAPTURE_VLM_BASE_URL="${AUTOCAPTURE_VLM_BASE_URL:-http://127.0.0.1:8000/v1}"
export AUTOCAPTURE_VLM_MODEL="${AUTOCAPTURE_VLM_MODEL:-internvl3_5_8b}"
export AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S="${AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S:-12}"
export AUTOCAPTURE_VLM_PREFLIGHT_RETRIES="${AUTOCAPTURE_VLM_PREFLIGHT_RETRIES:-3}"
export AUTOCAPTURE_VLM_MAX_INFLIGHT="${AUTOCAPTURE_VLM_MAX_INFLIGHT:-1}"
export AUTOCAPTURE_VLM_ORCHESTRATOR_CMD="${AUTOCAPTURE_VLM_ORCHESTRATOR_CMD:-bash /mnt/d/projects/hypervisor/tools/wsl/start_internvl35_8b_with_watch.sh}"

write_status "preflight" "checking_vllm"
preflight_json="$("$ROOT/.venv/bin/python" - <<'PY'
import json
import os
from autocapture_nx.inference.vllm_endpoint import check_external_vllm_ready

def _f(name: str, default: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    try:
        return float(raw) if raw else float(default)
    except Exception:
        return float(default)

def _i(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    try:
        return int(raw) if raw else int(default)
    except Exception:
        return int(default)

payload = check_external_vllm_ready(
    require_completion=True,
    timeout_models_s=_f("AUTOCAPTURE_VLM_PREFLIGHT_MODELS_TIMEOUT_S", 4.0),
    timeout_completion_s=_f("AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S", 12.0),
    retries=_i("AUTOCAPTURE_VLM_PREFLIGHT_RETRIES", 3),
    auto_recover=True,
)
print(json.dumps(payload, sort_keys=True))
PY
)"
if [[ -z "${preflight_json}" ]]; then
  echo "{\"ok\":false,\"error\":\"vllm_preflight_failed\",\"base_url\":\"${AUTOCAPTURE_VLM_BASE_URL}\"}"
  exit 2
fi
preflight_ok="$("$ROOT/.venv/bin/python" - <<'PY' "$preflight_json"
import json,sys
try:
    payload = json.loads(sys.argv[1])
except Exception:
    print("0")
    raise SystemExit(0)
print("1" if bool(payload.get("ok", False)) else "0")
PY
)"
if [[ "$preflight_ok" != "1" ]]; then
  write_status "preflight_failed" "vllm_not_ready"
  echo "{\"ok\":false,\"error\":\"vllm_preflight_failed\",\"base_url\":\"${AUTOCAPTURE_VLM_BASE_URL}\",\"preflight\":${preflight_json}}"
  exit 2
fi

before_latest="$(ls -1t "$ROOT/artifacts/single_image_runs" 2>/dev/null | head -n 1 || true)"
ingest_timeout_s="${AUTOCAPTURE_GOLDEN_INGEST_TIMEOUT_S:-900}"

write_status "ingest" "running_single_image_golden"
set +e
process_out="$(timeout "${ingest_timeout_s}s" "$ROOT/tools/run_single_image_golden.sh" "$IMAGE_PATH" 2>&1)"
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
  if [[ $process_rc -eq 124 ]]; then
    write_status "ingest_timeout" "single_image_timeout"
    echo "{\"ok\":false,\"error\":\"single_image_timeout\",\"timeout_s\":${ingest_timeout_s},\"report\":\"${report_path}\",\"detail\":\"${err_detail}\"}"
    exit 1
  fi
  echo "{\"ok\":false,\"error\":\"single_image_failed\",\"report\":\"${report_path}\",\"detail\":\"${err_detail}\"}"
  exit 1
fi

latest_run="$(ls -1t "$ROOT/artifacts/single_image_runs" | head -n 1)"
report_path="$ROOT/artifacts/single_image_runs/${latest_run}/report.json"

query_timeout_s="${AUTOCAPTURE_ADV_QUERY_TIMEOUT_S:-180}"
repro_runs="${AUTOCAPTURE_ADV_REPRO_RUNS:-1}"
lock_retries="${AUTOCAPTURE_ADV_LOCK_RETRIES:-2}"

write_status "eval" "running_advanced20"
set +e
adv_out="$("$ROOT/.venv/bin/python" "$ROOT/tools/run_advanced10_queries.py" --report "$report_path" --cases "$CASES_PATH" --strict-all --metadata-only --repro-runs "$repro_runs" --confidence-drift-tolerance-pct 1.0 --query-timeout-s "$query_timeout_s" --lock-retries "$lock_retries" 2>&1)"
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

write_status "done" "completed"
echo "{\"ok\":true,\"report\":\"$report_path\",\"advanced\":\"$adv_json_path\",\"advanced_rc\":$adv_rc,\"summary\":$summary_json,\"trace\":\"$TRACE_OUT\"}"
exit "$adv_rc"
