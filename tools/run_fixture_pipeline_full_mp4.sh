#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
manifest="$repo_root/docs/test sample/fixture_manifest.json"
source_frame="$repo_root/docs/test sample/Screenshot 2026-02-02 113519.png"
frames_dir="/tmp/fixture_frames_jepa_jpeg"
python_bin="$repo_root/.venv/bin/python3"
if [[ ! -x "$python_bin" ]]; then
  python_bin="${PYTHON_BIN:-python3}"
fi

export PYTHONPATH="$repo_root"

mkdir -p "$frames_dir"

# Convert the canonical PNG frame to JPEGs so ffmpeg_mp4 can mux them deterministically.
"$python_bin" - <<'PY'
from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image
except Exception as exc:
    raise SystemExit(f"ERROR: pillow required for mp4 fixture frames: {exc}")

repo_root = Path("/mnt/d/projects/autocapture_prime")
src = repo_root / "docs/test sample/Screenshot 2026-02-02 113519.png"
out_dir = Path("/tmp/fixture_frames_jepa_jpeg")
out_dir.mkdir(parents=True, exist_ok=True)

stamps = ["113519", "113529", "113539"]
img = Image.open(src).convert("RGB")
for stamp in stamps:
    dest = out_dir / f"Screenshot 2026-02-02 {stamp}.jpeg"
    if dest.exists():
        continue
    # Fixed quality/subsampling for determinism.
    img.save(dest, format="JPEG", quality=90, optimize=False, progressive=False, subsampling="4:2:0")
print(f"OK: wrote {len(stamps)} jpeg frames to {out_dir}")
PY

exec "$python_bin" "$repo_root/tools/run_fixture_pipeline.py" \
  --manifest "$manifest" \
  --input-dir "$frames_dir" \
  --force-idle \
  --capture-container ffmpeg_mp4 \
  --stub-frame-format jpeg \
  --video-frame-format jpeg

