#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required but not found on PATH." >&2
  exit 2
fi

cd "${REPO_ROOT}"
python3 "${REPO_ROOT}/tools/refresh_verify_impl_matrix.py" --allow-misses >/tmp/full_repo_miss_inventory_last.json
