#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"

# If the user didn't specify a persistent config/data dir, create a run-scoped one
# under .data/ (gitignored). This avoids accidental reuse of corrupted dev DBs.
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
export AUTOCAPTURE_CONFIG_DIR="${AUTOCAPTURE_CONFIG_DIR:-$ROOT/.data/soak/config_$stamp}"
export AUTOCAPTURE_DATA_DIR="${AUTOCAPTURE_DATA_DIR:-$ROOT/.data/soak/data_$stamp}"
mkdir -p "$AUTOCAPTURE_CONFIG_DIR" "$AUTOCAPTURE_DATA_DIR"

# Refuse to start if the repo is dirty; soak results must be attributable.
if command -v git >/dev/null 2>&1; then
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "ERROR: git worktree is dirty; commit/stash first" >&2
    git status -sb >&2 || true
    exit 2
  fi
fi

# Keep WSL stable: clamp native thread fanout for common numeric libs.
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export BLIS_NUM_THREADS="${BLIS_NUM_THREADS:-1}"
export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-1}"
export VECLIB_MAXIMUM_THREADS="${VECLIB_MAXIMUM_THREADS:-1}"
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"

# Reduce host_runner fanout (still runs in subprocess mode by default for sandboxing).
export AUTOCAPTURE_PLUGINS_LAZY_START="${AUTOCAPTURE_PLUGINS_LAZY_START:-1}"
export AUTOCAPTURE_PLUGINS_SUBPROCESS_SPAWN_CONCURRENCY="${AUTOCAPTURE_PLUGINS_SUBPROCESS_SPAWN_CONCURRENCY:-1}"
export AUTOCAPTURE_PLUGINS_SUBPROCESS_MAX_HOSTS="${AUTOCAPTURE_PLUGINS_SUBPROCESS_MAX_HOSTS:-2}"
# WSL stability: force in-proc plugin hosting for the soak run. This avoids
# long-lived host_runner subprocesses for capture/tracking plugins.
export AUTOCAPTURE_PLUGINS_HOSTING_MODE="${AUTOCAPTURE_PLUGINS_HOSTING_MODE:-inproc}"

# Preflight (offline): fail fast before starting the 24h run.
"$ROOT/.venv/bin/python" -m autocapture_nx doctor --self-test >/dev/null

# 24h soak.
exec "$ROOT/.venv/bin/python" -m autocapture_nx run --duration-s 86400 --status-interval-s 60
