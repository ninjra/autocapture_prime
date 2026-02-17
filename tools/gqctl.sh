#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCKFILE="${AUTOCAPTURE_GOLDEN_LOCKFILE:-/tmp/autocapture_prime_golden_qh.lock}"
PIDFILE="${LOCKFILE}.pid"
STATUSFILE="${AUTOCAPTURE_GOLDEN_STATUSFILE:-/tmp/autocapture_prime_golden_qh.status.json}"
CMD="${1:-status}"

case "$CMD" in
status)
  if [[ -f "$PIDFILE" ]]; then
    pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      if [[ -f "$STATUSFILE" ]]; then
        cat "$STATUSFILE"
      else
        echo "{\"ok\":true,\"running\":true,\"pid\":$pid}"
      fi
      exit 0
    fi
  fi
  echo '{"ok":true,"running":false}'
  ;;
stop)
  if [[ -f "$PIDFILE" ]]; then
    pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" || true
      sleep 1
      if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" || true
      fi
    fi
  fi
  rm -f "$PIDFILE" 2>/dev/null || true
  echo '{"ok":true,"stopped":true}'
  ;;
start)
  exec "$ROOT/tools/gq.sh"
  ;;
*)
  echo '{"ok":false,"error":"usage: gqctl.sh [status|stop|start]"}'
  exit 2
  ;;
esac
