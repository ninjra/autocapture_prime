#!/usr/bin/env bash
set -euo pipefail

# Processing-only WSL batch workflow for a Windows sidecar DataRoot (Mode B).
# This script does NOT perform screen capture. It only reads sidecar artifacts
# and drains the processing pipeline while permitted by foreground gating.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
AUTOCAPTURE="$ROOT/.venv/bin/autocapture"

DATAROOT="${1:-/mnt/d/autocapture}"
QUERY="${2:-}"

CONFIG_DIR="$DATAROOT/config_wsl"

mkdir -p "$CONFIG_DIR"

# Write/refresh a minimal user.json override under the sidecar DataRoot.
DATAROOT="$DATAROOT" CONFIG_DIR="$CONFIG_DIR" "$PY" -c "import json, os, pathlib; dataroot=pathlib.Path(os.environ['DATAROOT']); cfg_dir=pathlib.Path(os.environ['CONFIG_DIR']); cfg_dir.mkdir(parents=True, exist_ok=True); user_path=cfg_dir/'user.json'; overrides={'storage': {'data_dir': str(dataroot), 'metadata_path': str(dataroot/'metadata.live.db'), 'media_dir': str(dataroot/'media'), 'blob_dir': str(dataroot/'blobs'), 'lexical_path': str(dataroot/'lexical.db'), 'vector_path': str(dataroot/'vector.db'), 'no_deletion_mode': True, 'raw_first_local': True, 'encryption_enabled': False, 'encryption_required': False, 'anchor': {'sign': False, 'use_dpapi': False, 'path': str(dataroot/'anchor'/'anchors.ndjson')}}, 'runtime': {'activity': {'sidecar_signal_path': str(dataroot/'activity'/'activity_signal.json'), 'assume_idle_when_missing': False}, 'capture_controls': {'enabled': False}}, 'capture': {'video': {'enabled': False}, 'screenshot': {'enabled': False}, 'audio': {'enabled': False}, 'input_tracking': {'mode': 'off'}, 'window_metadata': {'enabled': False}, 'cursor': {'enabled': False}, 'clipboard': {'enabled': False}, 'file_activity': {'enabled': False}}}; user_path.write_text(json.dumps(overrides, indent=2, sort_keys=True), encoding='utf-8')"

BATCH_REQUIRE_IDLE_FLAG="--require-idle"
if [[ "${AUTOCAPTURE_BATCH_NO_REQUIRE_IDLE:-0}" == "1" ]]; then
  BATCH_REQUIRE_IDLE_FLAG="--no-require-idle"
fi

# Mirror metadata.db -> metadata.live.db using Windows Python (local I/O,
# no 9P bridge). This runs once before batch and as a background daemon during
# batch so the live replica stays fresh. The mirror uses sqlite3.backup() which
# is safe during active WAL writes.
MIRROR_SCRIPT="$ROOT/tools/mirror_metadata_live.py"
WIN_DATAROOT="$(echo "$DATAROOT" | sed 's|^/mnt/\(.\)/|\U\1:\\|' | sed 's|/|\\|g')"
WIN_PY=""
for candidate in "$ROOT/.venv_win311/Scripts/python.exe" "$ROOT/.venv_win/Scripts/python.exe"; do
  if [[ -x "$candidate" ]]; then
    WIN_PY="$candidate"
    break
  fi
done
MIRROR_PID=""
if [[ -n "$WIN_PY" && -f "$MIRROR_SCRIPT" ]]; then
  WIN_MIRROR="$(echo "$MIRROR_SCRIPT" | sed 's|^/mnt/\(.\)/|\U\1:\\|' | sed 's|/|\\|g')"
  # Single mirror before batch to ensure live DB is fresh at start.
  "$WIN_PY" "$WIN_MIRROR" --data-dir "$WIN_DATAROOT" --once 2>&1 || true
  # Background daemon mirrors every 30s while batch runs.
  "$WIN_PY" "$WIN_MIRROR" --data-dir "$WIN_DATAROOT" --interval 30 2>&1 &
  MIRROR_PID=$!
  echo "mirror=started pid=$MIRROR_PID interval=30s"
else
  echo "mirror=skipped reason=no_windows_python_or_script" >&2
fi

cleanup_mirror() {
  if [[ -n "${MIRROR_PID:-}" ]]; then
    kill "$MIRROR_PID" 2>/dev/null || true
    wait "$MIRROR_PID" 2>/dev/null || true
  fi
}
trap cleanup_mirror EXIT

AUTOCAPTURE_DATA_DIR="$DATAROOT" AUTOCAPTURE_CONFIG_DIR="$CONFIG_DIR" "$AUTOCAPTURE" batch run "$BATCH_REQUIRE_IDLE_FLAG"

if [[ -n "$QUERY" ]]; then
  AUTOCAPTURE_DATA_DIR="$DATAROOT" AUTOCAPTURE_CONFIG_DIR="$CONFIG_DIR" AUTOCAPTURE_STORAGE_METADATA_PATH="$DATAROOT/metadata.live.db" "$AUTOCAPTURE" query "$QUERY"
fi
