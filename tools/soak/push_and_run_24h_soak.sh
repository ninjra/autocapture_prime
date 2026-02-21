#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"

"$ROOT/tools/wsl/fix_dns_and_push_soak_branch.sh"
exec "$ROOT/tools/soak/run_24h_soak.sh"

