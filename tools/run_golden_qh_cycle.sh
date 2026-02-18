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

emit_progress() {
  local phase="$1"
  local detail="${2:-}"
  printf '{"event":"golden_qh.progress","pid":%s,"phase":"%s","detail":"%s","ts_utc":"%s"}\n' \
    "$$" "$phase" "$detail" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}

cleanup_job() {
  local child="${GOLDEN_CHILD_PID:-}"
  if [[ -n "${child}" ]]; then
    kill -TERM -- "-${child}" 2>/dev/null || true
    pkill -TERM -s "${child}" 2>/dev/null || true
    sleep 1
    kill -KILL -- "-${child}" 2>/dev/null || true
    pkill -KILL -s "${child}" 2>/dev/null || true
  fi
  rm -f "$PIDFILE" 2>/dev/null || true
}
trap cleanup_job EXIT INT TERM
write_status "start" "lock_acquired"
emit_progress "start" "lock_acquired"

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
export AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S="${AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S:-120}"
export AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_MAX_S="${AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_MAX_S:-120}"
export AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_SCALE="${AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_SCALE:-1.5}"
export AUTOCAPTURE_VLM_PREFLIGHT_RETRIES="${AUTOCAPTURE_VLM_PREFLIGHT_RETRIES:-2}"
export AUTOCAPTURE_VLM_PREFLIGHT_TOTAL_TIMEOUT_S="${AUTOCAPTURE_VLM_PREFLIGHT_TOTAL_TIMEOUT_S:-240}"
export AUTOCAPTURE_VLM_PREFLIGHT_PROGRESS="${AUTOCAPTURE_VLM_PREFLIGHT_PROGRESS:-1}"
export AUTOCAPTURE_VLM_MAX_INFLIGHT="${AUTOCAPTURE_VLM_MAX_INFLIGHT:-1}"
export AUTOCAPTURE_VLM_ORCHESTRATOR_CMD="${AUTOCAPTURE_VLM_ORCHESTRATOR_CMD:-bash /mnt/d/projects/hypervisor/tools/wsl/start_internvl35_8b_with_watch.sh}"

write_status "preflight" "checking_vllm"
emit_progress "preflight" "checking_vllm"
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
    timeout_completion_s=_f("AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S", 45.0),
    retries=_i("AUTOCAPTURE_VLM_PREFLIGHT_RETRIES", 6),
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
  emit_progress "preflight_failed" "vllm_not_ready"
  echo "{\"ok\":false,\"error\":\"vllm_preflight_failed\",\"base_url\":\"${AUTOCAPTURE_VLM_BASE_URL}\",\"preflight\":${preflight_json}}"
  exit 2
fi

before_latest="$(ls -1t "$ROOT/artifacts/single_image_runs" 2>/dev/null | head -n 1 || true)"
ingest_timeout_s="${AUTOCAPTURE_GOLDEN_INGEST_TIMEOUT_S:-900}"
mkdir -p "$ROOT/artifacts/logs"
log_ts="$(date -u +%Y%m%dT%H%M%SZ)"
ingest_log_path="$ROOT/artifacts/logs/golden_qh_ingest_${log_ts}.log"
eval_log_path="$ROOT/artifacts/logs/golden_qh_eval_${log_ts}.log"

write_status "ingest" "running_single_image_golden"
emit_progress "ingest" "running_single_image_golden"
set +e
setsid bash -lc '
ingest_timeout_s="$1"
runner="$2"
image="$3"
log_path="$4"
env PYTHONUNBUFFERED=1 timeout "${ingest_timeout_s}s" "$runner" "$image" > >(tee "$log_path") 2>&1
' _ "$ingest_timeout_s" "$ROOT/tools/run_single_image_golden.sh" "$IMAGE_PATH" "$ingest_log_path" &
ingest_pid=$!
GOLDEN_CHILD_PID="$ingest_pid"
ingest_started_s="$(date +%s)"
while kill -0 "$ingest_pid" 2>/dev/null; do
  now_s="$(date +%s)"
  elapsed_s="$((now_s - ingest_started_s))"
  emit_progress "ingest_heartbeat" "elapsed_s=${elapsed_s}"
  sleep 10
done
wait "$ingest_pid"
process_rc=$?
GOLDEN_CHILD_PID=""
set -e
process_out="$(tail -n 400 "$ingest_log_path" 2>/dev/null || true)"

if [[ $process_rc -ne 0 ]]; then
  after_latest="$(ls -1t "$ROOT/artifacts/single_image_runs" 2>/dev/null | head -n 1 || true)"
  run_dir=""
  if [[ -n "${after_latest}" ]]; then
    run_dir="$ROOT/artifacts/single_image_runs/${after_latest}"
  fi
  report_path=""
  if [[ -n "${run_dir}" ]]; then
    report_path="${run_dir}/report.json"
  fi
  if [[ -n "${run_dir}" ]]; then
    "$ROOT/.venv/bin/python" - <<'PY' "$run_dir" "$process_rc" "$ingest_timeout_s" >/dev/null 2>&1 || true
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

run_dir = Path(sys.argv[1])
rc = int(sys.argv[2])
timeout_s = int(float(sys.argv[3]))
report_path = run_dir / "report.json"
run_state_path = run_dir / "data" / "run_state.json"
now = datetime.now(timezone.utc).isoformat()

run_id = ""
if run_state_path.exists():
    try:
        state = json.loads(run_state_path.read_text(encoding="utf-8"))
        if isinstance(state, dict):
            run_id = str(state.get("run_id") or "")
            state["state"] = "stopped"
            state["stopped_at"] = now
            state["ts_utc"] = now
            state["last_error"] = "single_image_timeout" if rc == 124 else f"single_image_failed_rc_{rc}"
            run_state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    except Exception:
        pass

if not report_path.exists():
    payload = {
        "run_dir": str(run_dir),
        "config_dir": str(run_dir / "config"),
        "data_dir": str(run_dir / "data"),
        "run_id": run_id,
        "finished_utc": now,
        "error": "single_image_timeout" if rc == 124 else f"single_image_failed_rc_{rc}",
        "ingest_timeout_s": timeout_s,
        "ingest_ok": False,
        "boot_ok": False,
    }
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
PY
  fi
  err_detail=""
  if [[ -n "${report_path}" && -f "${report_path}" ]]; then
    err_detail="$("$ROOT/.venv/bin/python" -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('error',''))" "$report_path" 2>/dev/null || true)"
  fi
  if [[ $process_rc -eq 124 ]]; then
    write_status "ingest_timeout" "single_image_timeout"
    emit_progress "ingest_timeout" "single_image_timeout"
    echo "{\"ok\":false,\"error\":\"single_image_timeout\",\"timeout_s\":${ingest_timeout_s},\"report\":\"${report_path}\",\"detail\":\"${err_detail}\"}"
    exit 1
  fi
  emit_progress "ingest_failed" "single_image_failed"
  echo "{\"ok\":false,\"error\":\"single_image_failed\",\"report\":\"${report_path}\",\"detail\":\"${err_detail}\"}"
  exit 1
fi

latest_run="$(ls -1t "$ROOT/artifacts/single_image_runs" | head -n 1)"
report_path="$ROOT/artifacts/single_image_runs/${latest_run}/report.json"

query_timeout_s="${AUTOCAPTURE_ADV_QUERY_TIMEOUT_S:-180}"
repro_runs="${AUTOCAPTURE_ADV_REPRO_RUNS:-1}"
lock_retries="${AUTOCAPTURE_ADV_LOCK_RETRIES:-2}"
eval_preflight_completion_s="${AUTOCAPTURE_EVAL_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S:-120}"
eval_preflight_retries="${AUTOCAPTURE_EVAL_VLM_PREFLIGHT_RETRIES:-1}"
eval_preflight_total_s="${AUTOCAPTURE_EVAL_VLM_PREFLIGHT_TOTAL_TIMEOUT_S:-180}"

write_status "eval" "running_advanced20"
emit_progress "eval" "running_advanced20"
set +e
setsid bash -lc '
py="$1"
runner="$2"
report="$3"
cases="$4"
repro_runs="$5"
query_timeout_s="$6"
lock_retries="$7"
log_path="$8"
pref_completion="$9"
pref_retries="${10}"
pref_total="${11}"
AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S="$pref_completion" AUTOCAPTURE_VLM_PREFLIGHT_RETRIES="$pref_retries" AUTOCAPTURE_VLM_PREFLIGHT_TOTAL_TIMEOUT_S="$pref_total" env PYTHONUNBUFFERED=1 "$py" "$runner" --report "$report" --cases "$cases" --strict-all --metadata-only --repro-runs "$repro_runs" --confidence-drift-tolerance-pct 1.0 --query-timeout-s "$query_timeout_s" --lock-retries "$lock_retries" > >(tee "$log_path") 2>&1
' _ "$ROOT/.venv/bin/python" "$ROOT/tools/run_advanced10_queries.py" "$report_path" "$CASES_PATH" "$repro_runs" "$query_timeout_s" "$lock_retries" "$eval_log_path" "$eval_preflight_completion_s" "$eval_preflight_retries" "$eval_preflight_total_s" &
eval_pid=$!
GOLDEN_CHILD_PID="$eval_pid"
eval_started_s="$(date +%s)"
while kill -0 "$eval_pid" 2>/dev/null; do
  now_s="$(date +%s)"
  elapsed_s="$((now_s - eval_started_s))"
  emit_progress "eval_heartbeat" "elapsed_s=${elapsed_s}"
  sleep 10
done
wait "$eval_pid"
adv_rc=$?
GOLDEN_CHILD_PID=""
set -e
adv_out="$(tail -n 400 "$eval_log_path" 2>/dev/null || true)"

adv_json_path="$("$ROOT/.venv/bin/python" - <<'PY' "$adv_out" 2>/dev/null || true
import json
import sys

txt = str(sys.argv[1] if len(sys.argv) > 1 else "")
output_path = ""
for raw_line in txt.splitlines():
    line = raw_line.strip()
    if not line or not line.startswith("{") or not line.endswith("}"):
        continue
    try:
        obj = json.loads(line)
    except Exception:
        continue
    maybe = str(obj.get("output") or "").strip()
    if maybe:
        output_path = maybe
print(output_path)
PY
)"

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
emit_progress "done" "completed"
echo "{\"ok\":true,\"report\":\"$report_path\",\"advanced\":\"$adv_json_path\",\"advanced_rc\":$adv_rc,\"summary\":$summary_json,\"trace\":\"$TRACE_OUT\",\"ingest_log\":\"$ingest_log_path\",\"eval_log\":\"$eval_log_path\"}"
exit "$adv_rc"
