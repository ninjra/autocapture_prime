#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
pid_file="$ROOT/artifacts/soak/golden_qh/runner.pid"
log_file="$ROOT/artifacts/soak/golden_qh/runner.log"
latest_link="$ROOT/artifacts/soak/golden_qh/latest"

pid=""
running=false
if [[ -f "$pid_file" ]]; then
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
    running=true
  else
    rm -f "$pid_file"
    pid=""
  fi
fi

if [[ "$running" == "false" ]]; then
  fallback_pid="$(pgrep -f "autocapture_soak_runner|tools/soak/run_golden_qh_soak.sh" | head -n 1 || true)"
  if [[ -n "$fallback_pid" ]]; then
    pid="$fallback_pid"
    running=true
    echo "$pid" >"$pid_file"
  fi
fi

latest_dir=""
if [[ -L "$latest_link" ]]; then
  latest_dir="$(readlink -f "$latest_link" 2>/dev/null || true)"
fi

summary_path=""
if [[ -n "$latest_dir" && -f "$latest_dir/summary.json" ]]; then
  summary_path="$latest_dir/summary.json"
fi

live_path=""
if [[ -n "$latest_dir" && -f "$latest_dir/live.json" ]]; then
  live_path="$latest_dir/live.json"
fi
attempts_path=""
if [[ -n "$latest_dir" && -f "$latest_dir/attempts.ndjson" ]]; then
  attempts_path="$latest_dir/attempts.ndjson"
fi
live_payload="{}"
if [[ -n "$live_path" ]]; then
  live_payload="$(cat "$live_path" 2>/dev/null || echo '{}')"
elif [[ -n "$attempts_path" ]]; then
  live_payload="$("$ROOT/.venv/bin/python" - <<'PY' "$attempts_path"
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
rows = []
if path.exists():
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
blocked = 0
for row in rows:
    payload = row.get("payload", {}) if isinstance(row, dict) else {}
    if isinstance(payload, dict) and str(payload.get("error") or "") == "vllm_preflight_failed":
        blocked += 1
print(json.dumps({
    "attempt": int(len(rows)),
    "passed": int(sum(1 for r in rows if bool(r.get("passed", False)))),
    "failed": int(sum(1 for r in rows if not bool(r.get("passed", False)))),
    "blocked_vllm": int(blocked),
    "latest_ts_utc": str(rows[-1].get("ts_utc") if rows else ""),
    "attempts_ndjson": str(path),
}, sort_keys=True))
PY
)"
fi

echo "{\"ok\":true,\"running\":$running,\"pid\":\"$pid\",\"pid_file\":\"$pid_file\",\"log\":\"$log_file\",\"latest_dir\":\"$latest_dir\",\"summary\":\"$summary_path\",\"live\":$live_payload}"
