# Autocapture Prime Codex Implementation Matrix

Source: `docs/autocapture_prime_codex_implementation.md`  
Generated: 2026-02-14

| Requirement | Status | Evidence |
| --- | --- | --- |
| 2.1 Chronicle proto contract file | complete | `contracts/chronicle/v0/chronicle.proto` |
| 2.2 Spool format contract file | complete | `contracts/chronicle/v0/spool_format.md` |
| 2.3 Contract drift check + pinned hash | complete | `contracts/chronicle/v0/contract_pins.json`, `tools/gate_chronicle_contract_drift.py`, `tests/test_chronicle_contract_drift_gate.py` |
| 3. Runtime preflight checks | complete | `scripts/preflight.sh`, `tools/preflight_runtime.py`, `tests/test_preflight_runtime_checks.py` |
| 4.1 Autocapture Prime config surface | complete | `config/autocapture_prime.yaml`, `config/example.autocapture_prime.yaml`, `autocapture_prime/config.py`, `tests/test_autocapture_prime_config_schema.py` |
| 4.2 Spool ingestion (scanner/loader/decoder) | complete | `autocapture_prime/ingest/session_scanner.py`, `autocapture_prime/ingest/session_loader.py`, `autocapture_prime/ingest/frame_decoder.py`, `autocapture_prime/ingest/proto_decode.py`, `tests/test_chronicle_session_scanner.py`, `tests/test_chronicle_session_loader.py`, `tests/test_chronicle_proto_binary_loader.py` |
| 4.3 OCR pipeline (primary + fallback + cache) | complete | `autocapture_prime/ocr/paddle_engine.py`, `autocapture_prime/ocr/tesseract_engine.py`, `autocapture_prime/ocr/cache.py`, `tests/test_chronicle_ingest_pipeline.py` |
| 4.4 Layout parsing adapters | complete | `autocapture_prime/layout/uied_engine.py`, `autocapture_prime/layout/omniparser_engine.py` |
| 4.5 Temporal linking | complete | `autocapture_prime/link/temporal_linker.py`, `tests/test_chronicle_time_normalization.py`, `tests/test_chronicle_ingest_pipeline.py` |
| 4.6 Storage + indexing | complete | `autocapture_prime/store/tables.py`, `autocapture_prime/store/index.py`, `autocapture_prime/ingest/pipeline.py` |
| 4.7 vLLM service surface | complete | `services/vllm/run_vllm.sh`, `services/vllm/health.sh`, `tests/test_vllm_service_scripts.py` |
| 4.8 Chronicle API talking layer | complete | `services/chronicle_api/app.py`, `tests/test_chronicle_api_chat_completions.py` |
| 4.9 CLI entrypoints | complete | `autocapture_prime/cli.py`, `autocapture_prime/__main__.py`, `tests/test_autocapture_prime_cli.py` |
| 5.1 Unit tests | complete | `tests/test_chronicle_*`, `tests/test_autocapture_prime_*`, `tests/test_preflight_runtime_checks.py` |
| 5.2 Integration tests (fixture spool) | complete | `tests/fixtures/chronicle_spool/*`, `tests/test_chronicle_ingest_pipeline.py`, `tests/test_chronicle_api_chat_completions.py` |
| 5.3 Evaluation/metrics persistence | partial | `autocapture_prime/eval/metrics.py`, `autocapture_prime/ingest/pipeline.py`, `services/chronicle_api/app.py` now persist ingest metrics + QA latency rows; p50/p95 rollup and OCR-token accuracy scoring over fixture ground truth still needs explicit aggregator stage. |
| 6. Definition of done gates | partial | Core surfaces are implemented and test-covered; full end-to-end run with live sidecar zstd+protobuf payloads and live vLLM latency benchmarks remains an operational validation step. |

## Remaining Work
- Wire chronicle metrics (`ocr proxy accuracy`, `id_switches`, `qa latency p50/p95`) into the existing query eval ledger stream for unified dashboards.
- Add protobuf decode path validation against real sidecar `*.pb.zst` fixtures once sidecar fixture export is available in-repo.
- Add explicit CI workflow stanza (external to this repo’s local gate runner) invoking `tools/gate_chronicle_stack.py` in hosted CI.
