#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Keep WSL stable: cap subprocess plugin hosts (each host can be hundreds of MB RSS).
export AUTOCAPTURE_PLUGINS_SUBPROCESS_MAX_HOSTS="${AUTOCAPTURE_PLUGINS_SUBPROCESS_MAX_HOSTS:-2}"
export AUTOCAPTURE_PLUGINS_SUBPROCESS_IDLE_TTL_S="${AUTOCAPTURE_PLUGINS_SUBPROCESS_IDLE_TTL_S:-15}"
export PYTHONHASHSEED="${PYTHONHASHSEED:-0}"

"$repo_root/.venv/bin/python" -m pytest -q \
  "$repo_root/tests/test_citation_span_contract.py" \
  "$repo_root/tests/test_integrity_scan.py" \
  "$repo_root/tests/test_fixture_pipeline_cli.py" \
  "$repo_root/tests/test_metrics_ttfr.py"

mkdir -p /tmp/ac_low_resource_validation

"$repo_root/.venv/bin/python" "$repo_root/tools/run_fixture_pipeline.py" \
  --manifest "$repo_root/docs/test sample/fixture_manifest.json" \
  --output-dir /tmp/ac_low_resource_validation/out \
  --input-dir "$repo_root/docs/test sample" \
  --idle-timeout-s 60 \
  --idle-max-steps 30

# Optional: if ffmpeg is installed locally, exercise the ffmpeg_mp4 container end-to-end
# (capture -> store -> decode first frame -> OCR -> query).
if command -v ffmpeg >/dev/null 2>&1; then
  "$repo_root/.venv/bin/python" "$repo_root/tools/run_fixture_pipeline.py" \
    --manifest "$repo_root/docs/test sample/fixture_manifest.json" \
    --output-dir /tmp/ac_low_resource_validation/out_ffmpeg_mp4 \
    --input-dir "$repo_root/docs/test sample" \
    --capture-container ffmpeg_mp4 \
    --stub-frame-format jpeg \
    --video-frame-format jpeg \
    --idle-timeout-s 120 \
    --idle-max-steps 30

  bash "$repo_root/tools/fixtures/collect_ffmpeg_sample_from_screenshot.sh"
  "$repo_root/.venv/bin/python" -m pytest -q "$repo_root/tests/test_fixture_pipeline_ffmpeg_mp4.py"
fi

echo "OK: low resource validation complete"
