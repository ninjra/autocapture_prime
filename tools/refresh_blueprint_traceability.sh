#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Be resilient to odd invocation contexts (e.g., from a different CWD or via
# wrappers) by verifying the computed repo root.
if [[ ! -f "$REPO_ROOT/pyproject.toml" || ! -f "$REPO_ROOT/config/default.json" ]]; then
  if command -v git >/dev/null 2>&1; then
    git_root="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
    if [[ -n "${git_root:-}" && -f "$git_root/pyproject.toml" ]]; then
      REPO_ROOT="$git_root"
    fi
  fi
fi

if [[ ! -f "$REPO_ROOT/pyproject.toml" || ! -f "$REPO_ROOT/config/default.json" ]]; then
  echo "ERROR: failed to resolve repo root (got: $REPO_ROOT)" >&2
  exit 2
fi

python3 "$REPO_ROOT/tools/traceability/generate_traceability.py"
python3 "$REPO_ROOT/tools/gate_acceptance_coverage.py"
python3 "$REPO_ROOT/tools/update_blueprint_coverage_map.py"
python3 "$REPO_ROOT/tools/list_blueprint_gaps.py"
PYTHONPATH="$REPO_ROOT" python3 -m unittest -q tests.test_blueprint_spec_validation
