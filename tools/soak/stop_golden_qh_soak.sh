#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
pid_file="$ROOT/artifacts/soak/golden_qh/runner.pid"

if [[ ! -f "$pid_file" ]]; then
  fallback_pid="$(pgrep -f "autocapture_soak_runner|tools/soak/run_golden_qh_soak.sh" | head -n 1 || true)"
  if [[ -n "$fallback_pid" ]]; then
    kill "$fallback_pid" >/dev/null 2>&1 || true
    sleep 1
    if kill -0 "$fallback_pid" >/dev/null 2>&1; then
      kill -9 "$fallback_pid" >/dev/null 2>&1 || true
    fi
    echo "{\"ok\":true,\"stopped\":true,\"pid\":$fallback_pid,\"reason\":\"fallback_process\"}"
    exit 0
  fi
  echo "{\"ok\":true,\"stopped\":false,\"reason\":\"pid_file_missing\"}"
  exit 0
fi

pid="$(cat "$pid_file" 2>/dev/null || true)"
if [[ -z "$pid" ]]; then
  rm -f "$pid_file"
  echo "{\"ok\":true,\"stopped\":false,\"reason\":\"empty_pid\"}"
  exit 0
fi

if kill -0 "$pid" >/dev/null 2>&1; then
  kill "$pid" >/dev/null 2>&1 || true
  sleep 1
  if kill -0 "$pid" >/dev/null 2>&1; then
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$pid_file"
  echo "{\"ok\":true,\"stopped\":true,\"pid\":$pid}"
  exit 0
fi

rm -f "$pid_file"
echo "{\"ok\":true,\"stopped\":false,\"reason\":\"not_running\",\"pid\":$pid}"
