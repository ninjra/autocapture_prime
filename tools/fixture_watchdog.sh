#!/usr/bin/env bash
set -euo pipefail

interval="${1:-10}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runs_dir="$repo_root/artifacts/fixture_runs"
venv_python="$repo_root/.venv/bin/python3"
if [[ -x "$venv_python" ]]; then
  python_bin="$venv_python"
else
  python_bin="${PYTHON_BIN:-python3}"
fi

while true; do
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  latest_path="$(ls -1d "$runs_dir"/[0-9]* 2>/dev/null | sort | tail -n 1 || true)"
  latest=""
  if [[ -n "$latest_path" ]]; then
    latest="$(basename "$latest_path")"
  fi
  if [[ -z "$latest" ]]; then
    echo "[$ts] no runs yet"
    sleep "$interval"
    continue
  fi
  run_dir="$runs_dir/$latest"
  report="$run_dir/fixture_report.json"
  running="no"
  if pgrep -f "run_fixture_pipeline.py" >/dev/null 2>&1; then
    running="yes"
  fi
  if [[ -f "$report" ]]; then
    "$python_bin" - <<'PY' "$ts" "$latest" "$running" "$report"
import json
import sys

ts, run_id, running, report = sys.argv[1:]
d = json.load(open(report))
idle = d.get("idle") or {}
stats = idle.get("stats") or {}
queries = d.get("queries") or {}
ocr = d.get("ocr") or {}
print(f"[{ts}] run={run_id} running={running} report=ready")
print(
    "  idle_done={done} steps={steps} sst_tokens={sst_tokens} state_spans={state_spans} "
    "state_edges={state_edges} ocr_ok={ocr_ok} vlm_ok={vlm_ok} errors={errors}".format(
        done=idle.get("done"),
        steps=idle.get("steps"),
        sst_tokens=stats.get("sst_tokens"),
        state_spans=stats.get("state_spans"),
        state_edges=stats.get("state_edges"),
        ocr_ok=stats.get("ocr_ok"),
        vlm_ok=stats.get("vlm_ok"),
        errors=stats.get("errors"),
    )
)
print(
    f"  queries={queries.get('count')} failures={queries.get('failures')} ocr_backend={ocr.get('selected_backend')}"
)
PY
  else
    echo "[$ts] run=$latest running=$running report=missing"
    if [[ -d "$run_dir" ]]; then
      last_item="$(ls -t "$run_dir" 2>/dev/null | head -n 1 || true)"
      if [[ -n "$last_item" ]]; then
        echo "  last_path=$run_dir/$last_item"
      fi
    fi
  fi
  sleep "$interval"
done
