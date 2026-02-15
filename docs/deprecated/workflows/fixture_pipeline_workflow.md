# Fixture Pipeline Workflow

This workflow runs a single screenshot through the Autocapture pipeline (OCR + SST stages + indexing) and validates query answers with citations. It is designed to be deterministic and WSL-stable.

## Preconditions
- Prefer running from the repo root (scripts use absolute paths but logs/caches are easier to find).
- Use the repo virtual environment when available: `.venv/bin/python3`.
- Use the fixture manifest: `docs/test sample/fixture_manifest.json`.
- Use the multi-frame input dir: `/tmp/fixture_frames_jepa` (3 frames with timestamped filenames).
- Ensure RapidOCR deps are installed in the venv: `rapidocr-onnxruntime`, `pillow`, `numpy`.
- Keep WSL stable: avoid setting `AUTOCAPTURE_PLUGINS_HOSTING_MODE=subprocess` unless you have a reason.

## Input Preparation
- The screenshot is the only PNG in `docs/test sample/`.
- Create 3 frames so temporal SST stages see multiple time steps:
  - `Screenshot 2026-02-02 113519.png`
  - `Screenshot 2026-02-02 113529.png`
  - `Screenshot 2026-02-02 113539.png`
- Copy those into `/tmp/fixture_frames_jepa`.
  - The helper script `tools/run_fixture_pipeline_full.sh` will create these if missing.

## Step 1 (OCR-only smoke, optional)
- Use `/tmp/fixture_config_ocr_only.json` to validate OCR + SST OCR tokens before the full run (if you have one).
- Run with `--force-idle` to bypass idle gating during deterministic harness runs.

Command:
- `PYTHONPATH=. .venv/bin/python3 tools/run_fixture_pipeline.py --config-template /tmp/fixture_config_ocr_only.json --manifest 'docs/test sample/fixture_manifest.json' --input-dir /tmp/fixture_frames_jepa --force-idle`

Expected outputs:
- `artifacts/fixture_runs/<run_id>/fixture_report.json`
- `artifacts/fixture_runs/<run_id>/data/lexical.db`
- `artifacts/fixture_runs/<run_id>/data/vector.db`

## Step 2 (Full pipeline)
- Use `tools/fixture_config_template.json` (the default) which enables:
  - OCR extraction
  - SST stages (preprocess/temporal/layout/persist/index)
  - Indexing (lexical + vector)
  - Query path that uses metadata only (no on-query media decoding)
  - Citation-required answers

Command:
- `bash /mnt/d/projects/autocapture_prime/tools/run_fixture_pipeline_full.sh`

Expected outputs:
- `artifacts/fixture_runs/<run_id>/fixture_report.json`
- `artifacts/fixture_runs/<run_id>/data/lexical.db`
- `artifacts/fixture_runs/<run_id>/data/vector.db`
- `artifacts/fixture_runs/<run_id>/data/promptops/` (query history + traces)

## Step 3 (Autoloop + Watchdog)
- Autoloop re-runs the full pipeline until queries pass, applying fixes between attempts.
- Watchdog prints live progress from the latest run report.

Commands:
- `bash /mnt/d/projects/autocapture_prime/tools/run_fixture_autoloop.sh 60`
- `bash /mnt/d/projects/autocapture_prime/tools/fixture_watchdog.sh 10`

## Querying
- The fixture manifest defaults to `queries.mode: explicit` and `require_state: ok`.
- Queries should return evidence-backed answers with citations once the full run completes.
- Example query (from CLI runner): "what time is it on the vdi"

## Optional: FFmpeg Segment Decode Validation
- The system can capture segments in `ffmpeg_mp4` container when `ffmpeg` is available.
- Idle processing now supports extracting the first frame from `ffmpeg_mp4` segments (to feed OCR/SST).
- To validate end-to-end, ensure `ffmpeg` is installed and run a fixture with:
  - `capture.video.container=ffmpeg_mp4`
  - `capture.stub.frame_format=jpeg` (required for `ffmpeg_mp4`)

## Troubleshooting
- If queries return `no_evidence`, check:
  - `derived.sst.*` records include `ts_utc`
  - `lexical.db` has indexed docs
- If OCR is missing:
  - Confirm `rapidocr-onnxruntime` is installed in `.venv`
  - Check `fixture_report.json` for `ocr.selected_backend`
- If idle processing is blocked:
  - Use `--force-idle` and ensure no other heavy processes are running
