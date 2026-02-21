#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

tools/refresh_blueprint_traceability.sh
tools/run_adversarial_redesign_coverage.sh
tools/run_mod021_low_resource.sh
