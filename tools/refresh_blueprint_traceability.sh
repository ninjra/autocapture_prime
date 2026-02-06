#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

python3 tools/traceability/generate_traceability.py
python3 tools/gate_acceptance_coverage.py
python3 tools/update_blueprint_coverage_map.py
python3 tools/list_blueprint_gaps.py
python3 -m unittest tests/test_blueprint_spec_validation.py -q
