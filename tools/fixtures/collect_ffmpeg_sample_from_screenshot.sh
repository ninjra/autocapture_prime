#!/usr/bin/env bash
set -euo pipefail

# Deterministic MP4 fixture generator for exercising ffmpeg_mp4 decode paths.
# Input defaults to the checked-in screenshot fixture; output is a tiny MP4.

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
src="${1:-$repo_root/docs/test sample/Screenshot 2026-02-02 113519.png}"
out="${2:-$repo_root/docs/test sample/sample_ffmpeg_mp4.mp4}"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ERROR: ffmpeg not found in PATH" >&2
  exit 2
fi
if [[ ! -f "$src" ]]; then
  echo "ERROR: input not found: $src" >&2
  exit 2
fi

mkdir -p "$(dirname "$out")"

ffmpeg -hide_banner -loglevel error -y \
  -loop 1 -i "$src" -t 2 \
  -vf "fps=1,format=yuv420p" \
  -c:v libx264 -pix_fmt yuv420p \
  "$out"

echo "OK: wrote $out"

