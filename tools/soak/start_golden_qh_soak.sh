#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"

duration_s="${1:-86400}"
interval_s="${2:-60}"
image_path="${3:-$ROOT/docs/test sample/Screenshot 2026-02-02 113519.png}"
cases_path="${4:-$ROOT/docs/query_eval_cases_advanced20.json}"
parallel_workers="${5:-${AUTOCAPTURE_SOAK_PARALLEL_WORKERS:-1}}"
skip_admission="${AUTOCAPTURE_SOAK_SKIP_ADMISSION:-0}"

mkdir -p "$ROOT/artifacts/soak/golden_qh"
pid_file="$ROOT/artifacts/soak/golden_qh/runner.pid"
log_file="$ROOT/artifacts/soak/golden_qh/runner.log"
admission_json="$ROOT/artifacts/soak/golden_qh/admission_precheck_latest.json"

if [[ -f "$pid_file" ]]; then
  old_pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" >/dev/null 2>&1; then
    echo "{\"ok\":false,\"error\":\"already_running\",\"pid\":$old_pid,\"log\":\"$log_file\"}"
    exit 1
  fi
fi

if [[ "$skip_admission" != "1" ]]; then
  set +e
  precheck_out="$("$ROOT/.venv/bin/python3" "$ROOT/tools/soak/admission_check.py" --mode pre --output "artifacts/soak/golden_qh/admission_precheck_latest.json" 2>&1)"
  precheck_rc=$?
  set -e
  if [[ $precheck_rc -ne 0 ]]; then
    echo "{\"ok\":false,\"error\":\"admission_precheck_failed\",\"report\":\"$admission_json\",\"detail\":$(python3 - <<'PY' "$precheck_out"
import json,sys
print(json.dumps(str(sys.argv[1] or "")[-1600:]))
PY
)}"
    exit 2
  fi
fi

AUTOCAPTURE_SOAK_PARALLEL_WORKERS="$parallel_workers" \
nohup "$ROOT/tools/soak/run_golden_qh_soak.sh" "$duration_s" "$interval_s" "$image_path" "$cases_path" >>"$log_file" 2>&1 &
pid="$!"
echo "$pid" >"$pid_file"
sleep 1
if kill -0 "$pid" >/dev/null 2>&1; then
  echo "{\"ok\":true,\"pid\":$pid,\"log\":\"$log_file\",\"pid_file\":\"$pid_file\"}"
else
  echo "{\"ok\":false,\"error\":\"failed_to_start\",\"log\":\"$log_file\"}"
  exit 1
fi
