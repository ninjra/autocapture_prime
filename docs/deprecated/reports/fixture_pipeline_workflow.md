# Fixture Pipeline Workflow (Stepwise)

This document captures the end-to-end path used by the fixture stepwise pipeline so runs are reproducible and auditable.

## Entry Points

The stepwise run is driven by:

- `tools/run_fixture_stepwise.py`
- `tools/fixture_config_template.json`
- `docs/test sample/fixture_manifest.json`

## High-Level Flow

1. **Manifest + frames**
   - Load fixture manifest and resolve screenshot paths.
   - Copy the screenshot into a fixture frames directory.
2. **Config + kernel**
   - Build a run-scoped config (data dir, run_id, plugin allowlist).
   - Boot kernel with the run config and data directory.
3. **Capture**
   - Start `capture.source` to ingest the fixture frames.
   - Emit evidence records (for example `evidence.capture.segment`).
4. **Idle processing (batched)**
   - Gather all pending capture evidence into a batch (frame extraction + frame evidence).
   - Run OCR providers across the batch, store `derived.text.ocr` records, and index all text payloads.
   - Run VLM providers across the batch, store `derived.text.vlm` records, and index all text payloads.
   - Run the SST pipeline per frame for layout/state extraction and persist derived state/text/table/code/chart artifacts.
5. **State layer**
   - Build state spans and evidence links.
   - Run JEPA-like state builder (and training where enabled).
6. **Retrieval + evidence compilation**
   - Execute retrieval over the unified text indexes (OCR, VLM, SST-derived text).
   - Compile evidence snippets from derived state/text and screen tokens.
7. **Query + citations**
   - Build claims from snippets with citations.
   - Validate ledger + anchor references for citeability.

## Full Accounting

Each stepwise run writes a complete audit and plugin accounting:

- `artifacts/fixture_runs/<run_id>/stepwise_report.json`
- `plugins.load_report` (which plugins loaded)
- `plugin_trace` (calls per capability)
- `plugin_probe` (capability probes and errors)

Use the latest stepwise report as the authoritative source for the exact plugin list and per-step timings.

## Query Helper

Use `tools/query_latest_fixture.sh` to run a query against the latest stepwise fixture run without reprocessing media.
