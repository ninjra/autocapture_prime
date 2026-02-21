#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATAROOT="${1:-/mnt/d/autocapture}"
TIMEOUT_S="${2:-3}"
OUT="${3:-artifacts/live_stack/preflight_latest.json}"
INNER="cd ${ROOT} && .venv/bin/python tools/preflight_live_stack.py --dataroot ${DATAROOT} --timeout-s ${TIMEOUT_S} --output ${OUT}"

if [[ -x "${ROOT}/tools/run_linted_bash.sh" ]]; then
  exec "${ROOT}/tools/run_linted_bash.sh" "${INNER}"
fi

cd "${ROOT}"
exec .venv/bin/python tools/preflight_live_stack.py --dataroot "${DATAROOT}" --timeout-s "${TIMEOUT_S}" --output "${OUT}"

