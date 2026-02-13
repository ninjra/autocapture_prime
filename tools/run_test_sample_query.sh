#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
IMG="$ROOT/docs/test sample/Screenshot 2026-02-02 113519.png"

QUERY="${1:-How many inboxes do I have open?}"

exec "$PY" "$ROOT/tools/process_single_screenshot.py" --image "$IMG" --query "$QUERY"

