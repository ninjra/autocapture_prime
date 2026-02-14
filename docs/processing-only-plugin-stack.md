# Processing-Only Plugin Stack (Capture Deprecated)

## Scope
- This repo no longer owns screenshot capture or input ingestion.
- Windows sidecar repo owns capture + ingest and writes into shared DataRoot.
- This repo performs processing, indexing, retrieval, and NL query answering from stored artifacts.

## Data Contract (from sidecar)
- Required at DataRoot:
  - `media/` with frame blobs (`.blob` preferred, `.png` accepted during transition)
  - `metadata.db` with `records` table and at minimum:
    - `evidence.capture.frame`
    - `derived.input.summary`
    - `evidence.window.meta`
  - `journal.ndjson`, `ledger.ndjson`
  - `activity/activity_signal.json`
- Validate:
  - `.venv/bin/python tools/sidecar_contract_validate.py --dataroot /mnt/d/autocapture --max-journal-lines 2000`

## Chronicle Spool Ingestion Mode
- Additional supported input mode for sidecar handoff:
  - `contracts/chronicle/v0/chronicle.proto`
  - `contracts/chronicle/v0/spool_format.md`
- Processing entrypoint:
  - `autocapture-prime ingest --once --config config/autocapture_prime.yaml`
- Chronicle API entrypoint:
  - `autocapture-prime serve --config config/autocapture_prime.yaml`
- Contract drift gate:
  - `.venv/bin/python tools/gate_chronicle_contract_drift.py`

## New Plugins
- Localhost vLLM/OpenAI-compatible:
  - `builtin.vlm.vllm_localhost` (`vision.extractor`)
  - `builtin.embedder.vllm_localhost` (`embedder.text`)
  - `builtin.answer.synth_vllm_localhost` (`answer.synthesizer`)
  - Recommended endpoint split:
    - VLM + answer synth: `http://127.0.0.1:8000`
    - Embedder: `http://127.0.0.1:8001`
- Late interaction (ColBERT path):
  - `builtin.index.colbert_hash` (`index.postprocess`)
  - `builtin.reranker.colbert_hash` (`retrieval.reranker`)
  - `builtin.index.colbert_torch` (`index.postprocess`, optional CUDA)
  - `builtin.reranker.colbert_torch` (`retrieval.reranker`, optional CUDA)
- Nemotron extension points (optional CUDA):
  - `builtin.ocr.nemotron_torch` (`ocr.engine`)
  - `builtin.sst.nemotron_objects` (`processing.stage.hooks`)

## Localhost Network Policy
- Internet egress remains restricted to `builtin.egress.gateway`.
- Localhost-only network plugins are allowlisted separately:
  - `plugins.permissions.localhost_allowed_plugin_ids`
- Plugin runtime enforces:
  - `internet` scope only for internet allowlist
  - `localhost` scope can only connect loopback
  - fail-closed by default

## Metrics and Evaluation
- Per-query append-only metrics:
  - `<DataRoot>/facts/query_eval.ndjson` (`derived.query.eval`)
- Golden suite runs:
  - `tools/query_eval_suite.py` writes `<DataRoot>/facts/query_eval_suite.ndjson`
- Interactive feedback:
  - `tools/query_feedback.py` writes `<DataRoot>/facts/query_feedback.ndjson`

## Capture Plugin Deprecation
- Doctor check: `capture_plugins_deprecated` fails when legacy capture plugins are enabled.
- Keep these disabled:
  - `builtin.capture.audio.windows`
  - `builtin.capture.screenshot.windows`
  - `builtin.capture.basic`
  - `builtin.capture.windows`

## Recommended WSL Pipeline Command
- `bash tools/run_png_full_processing.sh "docs/test sample/Screenshot 2026-02-02 113519.png"`
