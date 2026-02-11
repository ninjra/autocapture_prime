#!/usr/bin/env bash
set -euo pipefail

# Processing-only WSL workflow for a Windows sidecar DataRoot (Mode B).
# This script does NOT perform screen capture. It only reads sidecar artifacts
# and runs the WSL processing pipeline (OCR/VLM/SST/state) when permitted.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
AUTOCAPTURE="$ROOT/.venv/bin/autocapture"

DATAROOT="${1:-/mnt/d/autocapture}"
QUERY="${2:-}"

CONFIG_DIR="$DATAROOT/config_wsl"

mkdir -p "$CONFIG_DIR"

# Write/refresh a minimal user.json override under the sidecar DataRoot.
DATAROOT="$DATAROOT" CONFIG_DIR="$CONFIG_DIR" "$PY" -c "import json, os, pathlib; dataroot=pathlib.Path(os.environ['DATAROOT']); cfg_dir=pathlib.Path(os.environ['CONFIG_DIR']); cfg_dir.mkdir(parents=True, exist_ok=True); user_path=cfg_dir/'user.json'; overrides={'storage': {'data_dir': str(dataroot), 'metadata_path': str(dataroot/'metadata.db'), 'media_dir': str(dataroot/'media'), 'lexical_path': str(dataroot/'lexical.db'), 'vector_path': str(dataroot/'vector.db'), 'no_deletion_mode': True, 'raw_first_local': True, 'encryption_enabled': False, 'encryption_required': False, 'anchor': {'sign': False, 'use_dpapi': False, 'path': str(dataroot/'anchor'/'anchors.ndjson')}}, 'runtime': {'activity': {'sidecar_signal_path': str(dataroot/'activity'/'activity_signal.json'), 'assume_idle_when_missing': False}, 'capture_controls': {'enabled': False}}, 'capture': {'video': {'enabled': False}, 'screenshot': {'enabled': False}, 'audio': {'enabled': False}, 'input_tracking': {'mode': 'off'}, 'window_metadata': {'enabled': False}, 'cursor': {'enabled': False}, 'clipboard': {'enabled': False}, 'file_activity': {'enabled': False}}}; user_path.write_text(json.dumps(overrides, indent=2, sort_keys=True), encoding='utf-8')"

AUTOCAPTURE_DATA_DIR="$DATAROOT" AUTOCAPTURE_CONFIG_DIR="$CONFIG_DIR" "$AUTOCAPTURE" enrich

if [[ -n "$QUERY" ]]; then
  AUTOCAPTURE_DATA_DIR="$DATAROOT" AUTOCAPTURE_CONFIG_DIR="$CONFIG_DIR" "$AUTOCAPTURE" query "$QUERY"
fi
