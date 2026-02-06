#!/usr/bin/env bash
set -euo pipefail

# Keep WSL stable: clamp thread fanout for common numeric libs, reduce priority.
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export BLIS_NUM_THREADS="${BLIS_NUM_THREADS:-1}"
export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-1}"
export VECLIB_MAXIMUM_THREADS="${VECLIB_MAXIMUM_THREADS:-1}"
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
# Avoid CUDA probing overhead/noise in environments without CUDA.
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-}"
# Avoid spawning subprocess plugin hosts during plugin enumeration (WSL stability).
export AUTOCAPTURE_PLUGINS_LAZY_START="${AUTOCAPTURE_PLUGINS_LAZY_START:-1}"

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

# Prefer single-core execution if taskset exists (stability over speed).
RUN=("$ROOT/.venv/bin/python3" "$ROOT/tools/run_all_tests.py")
if command -v taskset >/dev/null 2>&1; then
  RUN=(taskset -c 0 "${RUN[@]}")
fi
# Prefer idle I/O scheduling if available.
if command -v ionice >/dev/null 2>&1; then
  RUN=(ionice -c3 "${RUN[@]}")
fi

exec nice -n 10 "${RUN[@]}"
