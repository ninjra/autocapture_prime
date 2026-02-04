# Fixture Pipeline Workflow

This workflow runs a single screenshot through the full Autocapture pipeline (OCR, VLM, SST stages, indexing, state layer, JEPA training) and makes it queryable via PromptOps with citations.

## Preconditions
- Run from the repo root.
- Use the repo virtual environment: `.venv/bin/python3`.
- Use the fixture manifest: `docs/test sample/fixture_manifest.json`.
- Use the multi-frame input dir: `/tmp/fixture_frames_jepa` (3 frames with timestamped filenames).
- Ensure RapidOCR deps are installed in the venv: `rapidocr-onnxruntime`, `pillow`, `numpy`.

## Input Preparation
- The screenshot is the only PNG in `docs/test sample/`.
- Create 3 frames so JEPA training sees multiple time steps:
  - `Screenshot 2026-02-02 113519.png`
  - `Screenshot 2026-02-02 113529.png`
  - `Screenshot 2026-02-02 113539.png`
- Copy those into `/tmp/fixture_frames_jepa`.

## Step 1 (OCR-only smoke, optional)
- Use `/tmp/fixture_config_ocr_only.json` to validate OCR + SST OCR tokens before full run.
- Run with `--force-idle` to bypass idle gating during overnight runs.

Command:
- `PYTHONPATH=. .venv/bin/python3 tools/run_fixture_pipeline.py --config-template /tmp/fixture_config_ocr_only.json --manifest 'docs/test sample/fixture_manifest.json' --input-dir /tmp/fixture_frames_jepa --force-idle`

Expected outputs:
- `artifacts/fixture_runs/<run_id>/fixture_report.json`
- `artifacts/fixture_runs/<run_id>/data/lexical.db`
- `artifacts/fixture_runs/<run_id>/data/vector.db`
- `artifacts/fixture_runs/<run_id>/data/state/` (present but state-layer disabled in OCR-only)

## Step 2 (Full pipeline)
- Use `tools/fixture_config_template.json` which enables:
  - All SST stages and extractors
  - OCR + VLM extractors
  - Indexing (lexical + vector)
  - State layer + JEPA training
  - PromptOps with citations

Command:
- `PYTHONPATH=. .venv/bin/python3 tools/run_fixture_pipeline.py --config-template tools/fixture_config_template.json --manifest 'docs/test sample/fixture_manifest.json' --input-dir /tmp/fixture_frames_jepa --force-idle`

Expected outputs:
- `artifacts/fixture_runs/<run_id>/fixture_report.json`
- `artifacts/fixture_runs/<run_id>/data/lexical.db`
- `artifacts/fixture_runs/<run_id>/data/vector.db`
- `artifacts/fixture_runs/<run_id>/data/state/` (JEPA artifacts and state vectors)
- `artifacts/fixture_runs/<run_id>/data/promptops/` (query history + traces)

## Querying
- The fixture manifest uses `queries.mode: auto` and `require_state: ok`.
- Queries should return evidence-backed answers with citations once the full run completes.
- Example query (from UI or PromptOps): "what song was playing"

## Troubleshooting
- If queries return `no_evidence`, check:
  - `derived.sst.*` records include `ts_utc`
  - `lexical.db` has indexed docs
  - State layer enabled in config (`processing.state_layer.enabled: true`)
- If OCR is missing:
  - Confirm `rapidocr-onnxruntime` is installed in `.venv`
  - Check `fixture_report.json` for `ocr.selected_backend`
- If idle processing is blocked:
  - Use `--force-idle` and ensure no other heavy processes are running
