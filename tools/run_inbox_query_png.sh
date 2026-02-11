#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMG="${1:-$ROOT/docs/test sample/Screenshot 2026-02-02 113519.png}"

"$ROOT/.venv/bin/python" "$ROOT/tools/process_single_screenshot.py" --image "$IMG" --query "how many inboxes do i have open" --force-idle --budget-ms 30000
