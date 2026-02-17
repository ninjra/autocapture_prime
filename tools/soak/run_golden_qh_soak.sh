#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"

duration_s="${1:-86400}"
interval_s="${2:-60}"
image_path="${3:-$ROOT/docs/test sample/Screenshot 2026-02-02 113519.png}"
cases_path="${4:-$ROOT/docs/query_eval_cases_advanced20.json}"

if [[ ! "$duration_s" =~ ^[0-9]+$ ]] || [[ ! "$interval_s" =~ ^[0-9]+$ ]]; then
  echo "usage: $0 [duration_s] [interval_s] [image_path] [cases_path]" >&2
  exit 2
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
run_dir="$ROOT/artifacts/soak/golden_qh/$stamp"
mkdir -p "$run_dir"

jsonl="$run_dir/attempts.ndjson"
summary_json="$run_dir/summary.json"
latest_link="$ROOT/artifacts/soak/golden_qh/latest"
rm -f "$latest_link"
ln -s "$run_dir" "$latest_link"

start_epoch="$(date +%s)"
attempt=0
pass_count=0
fail_count=0
blocked_vllm_count=0
live_json="$run_dir/live.json"

while true; do
  now_epoch="$(date +%s)"
  elapsed="$((now_epoch - start_epoch))"
  if [[ "$elapsed" -ge "$duration_s" ]]; then
    break
  fi

  attempt="$((attempt + 1))"
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  trace_out="$run_dir/question-validation-plugin-trace-attempt-${attempt}.md"

  set +e
  cycle_out="$("$ROOT/tools/run_golden_qh_cycle.sh" "$image_path" "$cases_path" "$trace_out" 2>&1)"
  cycle_rc=$?
  set -e

  parsed="$("$ROOT/.venv/bin/python" - <<'PY' "$cycle_out" "$cycle_rc"
import json
import re
import sys

raw = str(sys.argv[1] or "")
rc = int(sys.argv[2] or 1)
m = re.search(r"\{.*\}\s*$", raw, re.S)
payload = {}
if m:
    try:
        payload = json.loads(m.group(0))
    except Exception:
        payload = {}
summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
failed = int(summary.get("evaluated_failed", 0) or 0)
passed = bool(rc == 0 and failed == 0 and bool(payload.get("ok", False)))
print(json.dumps({
    "passed": passed,
    "cycle_rc": rc,
    "payload": payload,
    "raw_tail": raw[-2000:],
}, sort_keys=True))
PY
)"

  did_pass="$("$ROOT/.venv/bin/python" - <<'PY' "$parsed"
import json
import sys
obj = json.loads(sys.argv[1])
print("1" if bool(obj.get("passed", False)) else "0")
PY
)"
  blocked_vllm="$("$ROOT/.venv/bin/python" - <<'PY' "$parsed"
import json
import sys
obj = json.loads(sys.argv[1])
payload = obj.get("payload", {}) if isinstance(obj, dict) else {}
err = str(payload.get("error") or "")
print("1" if err == "vllm_preflight_failed" else "0")
PY
)"

  if [[ "$did_pass" == "1" ]]; then
    pass_count="$((pass_count + 1))"
  else
    fail_count="$((fail_count + 1))"
  fi
  if [[ "$blocked_vllm" == "1" ]]; then
    blocked_vllm_count="$((blocked_vllm_count + 1))"
  fi

  "$ROOT/.venv/bin/python" - <<'PY' "$jsonl" "$attempt" "$ts" "$elapsed" "$parsed"
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
attempt = int(sys.argv[2])
ts = str(sys.argv[3])
elapsed = int(sys.argv[4])
parsed = json.loads(sys.argv[5])
row = {
    "attempt": attempt,
    "ts_utc": ts,
    "elapsed_s": elapsed,
    "passed": bool(parsed.get("passed", False)),
    "cycle_rc": int(parsed.get("cycle_rc", 1)),
    "payload": parsed.get("payload"),
    "raw_tail": parsed.get("raw_tail", ""),
}
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("a", encoding="utf-8") as f:
    f.write(json.dumps(row, sort_keys=True) + "\n")
PY

  "$ROOT/.venv/bin/python" - <<'PY' "$live_json" "$stamp" "$attempt" "$elapsed" "$pass_count" "$fail_count" "$blocked_vllm_count" "$jsonl"
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
payload = {
    "run_id": str(sys.argv[2]),
    "attempt": int(sys.argv[3]),
    "elapsed_s": int(sys.argv[4]),
    "passed": int(sys.argv[5]),
    "failed": int(sys.argv[6]),
    "blocked_vllm": int(sys.argv[7]),
    "attempts_ndjson": str(sys.argv[8]),
}
path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
PY

  echo "[$ts] attempt=$attempt passed=$did_pass pass_count=$pass_count fail_count=$fail_count elapsed_s=$elapsed"
  sleep "$interval_s"
done

end_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
end_epoch="$(date +%s)"
total_elapsed="$((end_epoch - start_epoch))"

"$ROOT/.venv/bin/python" - <<'PY' "$summary_json" "$stamp" "$start_epoch" "$end_ts" "$total_elapsed" "$attempt" "$pass_count" "$fail_count" "$jsonl" "$blocked_vllm_count"
import json
import pathlib
import sys

summary_path = pathlib.Path(sys.argv[1])
stamp = str(sys.argv[2])
start_epoch = int(sys.argv[3])
end_ts = str(sys.argv[4])
elapsed = int(sys.argv[5])
attempts = int(sys.argv[6])
passed = int(sys.argv[7])
failed = int(sys.argv[8])
jsonl = str(sys.argv[9])
payload = {
    "ok": bool(failed == 0 and attempts > 0),
    "run_id": stamp,
    "started_epoch": start_epoch,
    "ended_utc": end_ts,
    "elapsed_s": elapsed,
    "attempts": attempts,
    "passed": passed,
    "failed": failed,
    "blocked_vllm": int(sys.argv[10] if len(sys.argv) > 10 else 0),
    "pass_rate_pct": round((passed / attempts) * 100.0, 2) if attempts else 0.0,
    "attempts_ndjson": jsonl,
}
summary_path.parent.mkdir(parents=True, exist_ok=True)
summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
print(json.dumps(payload, sort_keys=True))
PY

postcheck_json="$run_dir/admission_postcheck.json"
set +e
"$ROOT/.venv/bin/python3" "$ROOT/tools/soak/admission_check.py" \
  --mode post \
  --soak-summary "${summary_json#$ROOT/}" \
  --min-elapsed-s "$duration_s" \
  --max-failed-attempts 0 \
  --max-blocked-vllm 0 \
  --output "${postcheck_json#$ROOT/}" >/dev/null 2>&1
set -e
