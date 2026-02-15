#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

image_path="docs/test sample/Screenshot 2026-02-02 113519.png"
profile_path="config/profiles/golden_full.json"

.venv/bin/python tools/process_single_screenshot.py --image "$image_path" --profile "$profile_path" --max-idle-steps 20 --output-dir artifacts/single_image_runs

latest_report="$(ls -1dt artifacts/single_image_runs/single_*/report.json | head -n 1)"
.venv/bin/python tools/run_advanced10_queries.py --report "$latest_report" --repro-runs 1 --lock-retries 1 --query-timeout-s 25 --output artifacts/advanced10/advanced20_post_patch_smoke.json

echo "ok report=$latest_report eval=artifacts/advanced10/advanced20_post_patch_smoke.json"
