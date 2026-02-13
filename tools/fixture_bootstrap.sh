#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log_file="$repo_root/artifacts/fixture_runs/fixture_autoloop.log"
mkdir -p "$(dirname "$log_file")"

sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng libgl1 libglib2.0-0 libgomp1

nohup bash "$repo_root/tools/run_fixture_autoloop.sh" 60 >>"$log_file" 2>&1 &
