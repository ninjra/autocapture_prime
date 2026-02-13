#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="$(find "${ROOT_DIR}/artifacts/fixture_runs" -maxdepth 3 -type f -path "*/config/user.json" -printf '%T@ %h\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)"
if [[ -z "${CONFIG_DIR}" ]]; then
  echo "No stepwise fixture runs found."
  exit 1
fi
RUN_DIR="$(cd "${CONFIG_DIR}/.." && pwd)"

QUERY="${*:-}"
if [[ -z "${QUERY}" ]]; then
  echo "Usage: $0 \"your question\""
  exit 2
fi

export AUTOCAPTURE_CONFIG_DIR="${RUN_DIR}/config"
export AUTOCAPTURE_DATA_DIR="${RUN_DIR}/data"
export AUTOCAPTURE_QUERY="${QUERY}"
export PYTHONPATH="${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

venv_python="${ROOT_DIR}/.venv/bin/python3"
if [[ -x "${venv_python}" ]]; then
  python_bin="${venv_python}"
else
  python_bin="${PYTHON_BIN:-python3}"
fi

exec "${python_bin}" -c "import json, os; from autocapture_nx.ux.facade import create_facade; q=os.environ.get('AUTOCAPTURE_QUERY',''); print(json.dumps(create_facade().query(q)))"
