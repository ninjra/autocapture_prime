#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
manifest="$repo_root/docs/test sample/fixture_manifest.json"
source_frame="$repo_root/docs/test sample/Screenshot 2026-02-02 113519.png"
frames_dir="/tmp/fixture_frames_jepa"
venv_python="$repo_root/.venv/bin/python3"
if [[ -x "$venv_python" ]]; then
  python_bin="$venv_python"
else
  python_bin="${PYTHON_BIN:-python3}"
fi

export PYTHONPATH="$repo_root"
mkdir -p "$frames_dir"
for stamp in 113519 113529 113539; do
  dest="$frames_dir/Screenshot 2026-02-02 ${stamp}.png"
  if [[ ! -f "$dest" ]]; then
    cp "$source_frame" "$dest"
  fi
done
exec "$python_bin" "$repo_root/tools/run_fixture_pipeline.py" \
  --manifest "$manifest" \
  --input-dir "$frames_dir" \
  --force-idle
