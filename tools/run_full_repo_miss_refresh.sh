#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PY_BIN="${REPO_ROOT}/.venv/bin/python"

if [[ ! -x "${PY_BIN}" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PY_BIN="python3"
  else
    echo "ERROR: Python not found (.venv/bin/python missing and python3 unavailable)." >&2
    exit 2
  fi
fi

cd "${REPO_ROOT}"
PYTHONPATH="${REPO_ROOT}" "${PY_BIN}" "${REPO_ROOT}/tools/full_repo_miss_inventory.py" >/tmp/full_repo_miss_inventory_last.json
PYTHONPATH="${REPO_ROOT}" "${PY_BIN}" "${REPO_ROOT}/tools/generate_full_remaining_matrix.py"
