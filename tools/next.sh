#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

MODE="${1:-sample}"
shift || true

case "$MODE" in
  sample)
    exec "$ROOT/tools/run_test_sample_query.sh" "$@"
    ;;
  sidecar)
    exec "$ROOT/tools/run_sidecar_wsl_enrich_once.sh" "$@"
    ;;
  sidecar-batch)
    exec "$ROOT/tools/run_sidecar_wsl_batch.sh" "$@"
    ;;
  png-full)
    exec "$ROOT/tools/run_png_full_processing.sh" "$@"
    ;;
  *)
    echo "usage: $0 [sample|sidecar|sidecar-batch|png-full] [args...]" >&2
    exit 2
    ;;
esac
