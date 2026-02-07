#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

python3 "$REPO_ROOT/tools/traceability/generate_adversarial_redesign_traceability.py"
python3 "$REPO_ROOT/tools/traceability/validate_adversarial_redesign_traceability.py"
python3 "$REPO_ROOT/tools/list_adversarial_redesign_gaps.py"
python3 "$REPO_ROOT/tools/gate_adversarial_redesign_coverage.py"

