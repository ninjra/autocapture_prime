# Autocapture Prime Codex Implementation Matrix

Source: `docs/autocapture_prime_codex_implementation.md`  
Generated: 2026-02-15

| Requirement | Status | Evidence |
| --- | --- | --- |
| 2.1 Chronicle proto contract file | complete | `contracts/chronicle/v0/chronicle.proto` |
| 2.2 Spool format contract file | complete | `contracts/chronicle/v0/spool_format.md` |
| 2.3 Contract drift check + pinned hash | complete | `contracts/chronicle/v0/contract_pins.json`, `tools/gate_chronicle_contract_drift.py`, `tests/test_chronicle_contract_drift_gate.py` |
| 3. Runtime preflight checks | complete | `scripts/preflight.sh`, `tools/preflight_runtime.py`, `tests/test_preflight_runtime_checks.py` |
| 4.1 Autocapture Prime config surface | complete | `config/autocapture_prime.yaml`, `config/example.autocapture_prime.yaml`, `autocapture_prime/config.py`, `tests/test_autocapture_prime_config_schema.py` |
| 4.2 Spool ingestion (scanner/loader/decoder) | complete | `autocapture_prime/ingest/session_scanner.py`, `autocapture_prime/ingest/session_loader.py`, `autocapture_prime/ingest/frame_decoder.py`, `autocapture_prime/ingest/proto_decode.py`, `tests/test_chronicle_session_scanner.py`, `tests/test_chronicle_session_loader.py`, `tests/test_chronicle_proto_binary_loader.py` |
| 4.3 OCR pipeline (primary + fallback + cache) | complete | `autocapture_prime/ocr/paddle_engine.py`, `autocapture_prime/ocr/tesseract_engine.py`, `autocapture_prime/ocr/cache.py`, `autocapture_prime/ingest/pipeline.py` (two-pass full-frame + ROI), `tests/test_chronicle_ingest_pipeline.py` |
| 4.4 Layout parsing adapters | complete | `autocapture_prime/layout/uied_engine.py`, `autocapture_prime/layout/omniparser_engine.py` |
| 4.5 Temporal linking | complete | `autocapture_prime/link/temporal_linker.py`, `autocapture_prime/ingest/pipeline.py` (click-anchor map), `tests/test_temporal_linker.py`, `tests/test_chronicle_ingest_pipeline.py` |
| 4.6 Storage + indexing | complete | `autocapture_prime/store/tables.py`, `autocapture_prime/store/index.py` (deterministic ranking metadata), `autocapture_prime/ingest/pipeline.py`, `tests/test_chronicle_index_determinism.py` |
| 4.7 vLLM service surface | complete | `services/vllm/run_vllm.sh`, `services/vllm/health.sh`, `tests/test_vllm_service_scripts.py` |
| 4.8 Chronicle API talking layer | complete | `services/chronicle_api/app.py`, `tests/test_chronicle_api_chat_completions.py` |
| 4.9 CLI entrypoints | complete | `autocapture_prime/cli.py`, `autocapture_prime/__main__.py`, `tests/test_autocapture_prime_cli.py` |
| 5.1 Unit tests | complete | `tests/test_chronicle_*`, `tests/test_autocapture_prime_*`, `tests/test_preflight_runtime_checks.py` |
| 5.2 Integration tests (fixture spool) | complete | `tests/fixtures/chronicle_spool/*`, `tests/test_chronicle_ingest_pipeline.py`, `tests/test_chronicle_api_chat_completions.py` |
| 5.3 Evaluation/metrics persistence | complete | `autocapture_prime/eval/metrics.py` now persists query hash, plugin path, confidence, feedback state, evidence-order hash; wired from `services/chronicle_api/app.py` and verified in `tests/test_chronicle_api_chat_completions.py`. |
| 6. Definition of done gates | partial | Core surfaces are implemented and test-covered; full end-to-end run with live sidecar zstd+protobuf payloads and live vLLM latency benchmarks remains an operational validation step. |
| autocapture_prime.md safety defaults (localhost + fail-closed risky toggles) | complete | `services/chronicle_api/app.py` localhost enforcement, `config/autocapture_prime.yaml` + `config/example.autocapture_prime.yaml` safe defaults, `tests/test_autocapture_prime_config_schema.py` |
| autocapture_prime.md deterministic evidence chain for QA | complete | `services/chronicle_api/app.py` evidence payload + hash + usage metadata, `autocapture_prime/store/index.py` deterministic tie-breaks |

## Remaining Work
- Live vLLM-backed fidelity benchmark sweep (golden Q/H set) still depends on stable external endpoint and run-time GPU availability.
- Add OCR-token quality ground truth fixture scoring pipeline (CER/WER) for objective extractor drift detection.
- Add explicit CI workflow stanza (external to this repo’s local gate runner) invoking `tools/gate_chronicle_stack.py` in hosted CI.
