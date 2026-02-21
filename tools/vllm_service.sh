#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-status}"
HOST="127.0.0.1"
PORT="8000"
BASE_URL="http://${HOST}:${PORT}"

deprecated_launch() {
  echo "deprecated: local vLLM lifecycle is owned by the sidecar repo."
  echo "this repo only consumes external vLLM at ${BASE_URL}."
  echo "start/stop/restart/log actions are disabled here."
  exit 3
}

health_ok() {
  curl -fsS --max-time 2 "${BASE_URL}/v1/models" >/dev/null 2>&1
}

case "${ACTION}" in
  start|stop|restart|logs)
    deprecated_launch
    ;;
  status)
    if health_ok; then
      echo "running_unmanaged host=${HOST} port=${PORT} health=ok"
    else
      echo "stopped_unmanaged host=${HOST} port=${PORT} health=down"
      exit 1
    fi
    ;;
  health)
    if health_ok; then
      echo "ok"
    else
      echo "down"
      exit 1
    fi
    ;;
  models)
    curl -fsS --max-time 4 "${BASE_URL}/v1/models"
    ;;
  *)
    echo "usage: $0 {status|health|models|start|stop|restart|logs}" >&2
    exit 2
    ;;
esac
