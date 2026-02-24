#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
OUT="${1:-$ROOT/artifacts/query_acceptance/popup_go_no_go_latest.json}"

"$PY" "$ROOT/tools/popup_go_no_go.py" --strict --out "$OUT"
