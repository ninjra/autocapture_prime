#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="${ROOT}/config/autocapture_prime.yaml"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CFG="$2"
      shift 2
      ;;
    *)
      echo "unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "${PY}" ]]; then
  PY="python3"
fi

cd "${ROOT}"
PYTHONPATH="${ROOT}" "${PY}" -m autocapture_prime --config "${CFG}" ingest --once
PYTHONPATH="${ROOT}" "${PY}" -m autocapture_prime --config "${CFG}" build-index --all
