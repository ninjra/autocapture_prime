#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
PY="$ROOT/.venv/bin/python3"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi
exec "$PY" "$ROOT/tools/release_gate.py" "$@"
