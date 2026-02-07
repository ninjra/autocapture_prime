#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

python3 "$REPO_ROOT/tools/traceability/generate_traceability.py"
python3 "$REPO_ROOT/tools/gate_acceptance_coverage.py"
python3 "$REPO_ROOT/tools/update_blueprint_coverage_map.py"
python3 "$REPO_ROOT/tools/list_blueprint_gaps.py"
PYTHONPATH="$REPO_ROOT" python3 -m unittest -q tests.test_blueprint_spec_validation
