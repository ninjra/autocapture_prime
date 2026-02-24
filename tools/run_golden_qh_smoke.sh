#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

image_path="docs/test sample/Screenshot 2026-02-02 113519.png"
profile_path="config/profiles/golden_full.json"

"$repo_root/.venv/bin/python" "$repo_root/tools/process_single_screenshot.py" --image "$image_path" --profile "$profile_path" --max-idle-steps 20 --output-dir artifacts/single_image_runs

latest_report="$(ls -1dt artifacts/single_image_runs/single_*/report.json | sed -n '1p')"
if [[ -z "${latest_report:-}" ]]; then
  echo "no report.json found under artifacts/single_image_runs/single_*/" >&2
  exit 1
fi
query_timeout_s="${AUTOCAPTURE_QH_QUERY_TIMEOUT_S:-75}"
"$repo_root/.venv/bin/python" "$repo_root/tools/run_advanced10_queries.py" --report "$latest_report" --repro-runs 1 --lock-retries 1 --query-timeout-s "$query_timeout_s" --output artifacts/advanced10/advanced20_post_patch_smoke.json

echo "ok report=$latest_report eval=artifacts/advanced10/advanced20_post_patch_smoke.json"
