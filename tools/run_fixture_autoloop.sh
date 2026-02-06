#!/usr/bin/env bash
set -euo pipefail

interval="${1:-60}"
max_attempts="${2:-0}"
health_interval=30
pipeline_timeout_s="${PIPELINE_TIMEOUT_S:-3600}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log_file="$repo_root/artifacts/fixture_runs/fixture_autoloop.log"
report_file=""
venv_python="$repo_root/.venv/bin/python3"
if [[ -x "$venv_python" ]]; then
  python_bin="$venv_python"
else
  python_bin="${PYTHON_BIN:-python3}"
fi

trap 'echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] autoloop exit code=$? " >>"$log_file"' EXIT

latest_run_path() {
  find "$repo_root/artifacts/fixture_runs" -maxdepth 1 -type d -name '[0-9]*' 2>/dev/null | sort | tail -n 1
}

ensure_rapidocr() {
  if "$python_bin" - <<'PY' >/dev/null 2>&1; then
import rapidocr_onnxruntime  # noqa: F401
PY
    return 0
  fi
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] rapidocr missing; attempting venv install" | tee -a "$log_file"
  "$python_bin" -m pip install rapidocr-onnxruntime >>"$log_file" 2>&1 || true
}

ensure_tesseract() {
  if command -v tesseract >/dev/null 2>&1; then
    return 0
  fi
  if sudo -n true >/dev/null 2>&1; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] installing tesseract + deps" | tee -a "$log_file"
    sudo -n apt-get update >>"$log_file" 2>&1 || true
    sudo -n apt-get install -y tesseract-ocr tesseract-ocr-eng libgl1 libglib2.0-0 libgomp1 >>"$log_file" 2>&1 || true
  else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] sudo non-interactive unavailable; cannot apt-get tesseract yet" | tee -a "$log_file"
  fi
}

analyze_report() {
  "$python_bin" "$repo_root/tools/fixture_analyze.py" "$report_file"
}

attempt=0
while true; do
  attempt=$((attempt + 1))
  if [[ "$max_attempts" -gt 0 && "$attempt" -gt "$max_attempts" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] reached max attempts ($max_attempts), stopping" | tee -a "$log_file"
    exit 1
  fi

  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] attempt=$attempt starting full pipeline" | tee -a "$log_file"
  bash "$repo_root/tools/run_fixture_pipeline_full.sh" >>"$log_file" 2>&1 &
  pipeline_pid=$!
  start_epoch="$(date +%s)"
  current_run=""
  while kill -0 "$pipeline_pid" >/dev/null 2>&1; do
    sleep "$health_interval"
    now_epoch="$(date +%s)"
    runtime_s="$((now_epoch - start_epoch))"
    latest_path="$(latest_run_path || true)"
    latest=""
    if [[ -n "$latest_path" ]]; then
      latest="$(basename "$latest_path")"
    fi
    if [[ -n "$latest" ]]; then
      current_run="$latest"
    fi
    report_path=""
    if [[ -n "$current_run" ]]; then
      report_path="$repo_root/artifacts/fixture_runs/$current_run/fixture_report.json"
    fi
    report_state="missing"
    if [[ -n "$report_path" && -f "$report_path" ]]; then
      report_state="ready"
    fi
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] attempt=$attempt running pid=$pipeline_pid runtime_s=$runtime_s run=${current_run:-unknown} report=$report_state" | tee -a "$log_file"
    if [[ "$runtime_s" -ge "$pipeline_timeout_s" ]]; then
      echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] attempt=$attempt timeout after ${runtime_s}s, stopping pipeline" | tee -a "$log_file"
      kill "$pipeline_pid" >/dev/null 2>&1 || true
      sleep 2
      kill -9 "$pipeline_pid" >/dev/null 2>&1 || true
      break
    fi
  done
  wait "$pipeline_pid" >/dev/null 2>&1 || true

  latest_path="$(latest_run_path || true)"
  latest=""
  if [[ -n "$latest_path" ]]; then
    latest="$(basename "$latest_path")"
  fi
  if [[ -z "$latest" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] no run directories found" | tee -a "$log_file"
    sleep "$interval"
    continue
  fi
  report_file="$repo_root/artifacts/fixture_runs/$latest/fixture_report.json"
  if [[ ! -f "$report_file" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] report missing for run=$latest" | tee -a "$log_file"
    sleep "$interval"
    continue
  fi

  summary_json="$(analyze_report)"
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] summary $summary_json" | tee -a "$log_file"
  status="$("$python_bin" - <<'PY' "$summary_json"
import json, sys
print(json.loads(sys.argv[1]).get("status","unknown"))
PY
)"

  if [[ "$status" == "ok" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] success: queries ready" | tee -a "$log_file"
    exit 0
  fi

  if [[ "$status" == "ocr_missing" ]]; then
    ensure_rapidocr
    ensure_tesseract
  fi

  if [[ "$status" == "state_empty" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] state empty; rerun after cooldown" | tee -a "$log_file"
  fi

  if [[ "$status" == "no_evidence" || "$status" == "no_queries" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] no evidence; rerun after cooldown" | tee -a "$log_file"
  fi

  sleep "$interval"
done
