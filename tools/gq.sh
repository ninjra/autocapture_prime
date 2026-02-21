#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash "$ROOT/tools/run_golden_qh_cycle.sh" "$ROOT/docs/test sample/Screenshot 2026-02-02 113519.png"
