# Live Stack Validation

## Purpose
Validate live sidecar data availability and localhost VLM reachability for operational closure.

## Canonical Localhost Endpoints
- `127.0.0.1:8000` — vLLM OpenAI-compatible VLM (`/v1/models`, `/v1/chat/completions`), model `internvl3_5_8b`.
- `127.0.0.1:8001` — embedding service (`/v1/models`, `/v1/embeddings`), model `BAAI/bge-small-en-v1.5`.
- `127.0.0.1:8011` — grounding sidecar (`/health`, `/v1/grounding`).
- `127.0.0.1:34221` — thermal brain gateway/orchestrator (`/statusz`, route/proxy state).
- `127.0.0.1:8787` — popup-query API for hypervisor popup-query flow.
- `127.0.0.1:7411` — hypervisor devtools API (diffusion contract).

## Route Ownership
- Non-popup query forwarding uses `http://127.0.0.1:34221/v1/chat/completions`.
- `127.0.0.1:8787` is popup flow only.

## Probe Contract
- `8000` -> `GET /v1/models`
- `8001` -> `GET /v1/models`
- `8011` -> `GET /health`
- `34221` -> `GET /statusz`
- `8787` -> `GET /health`

## Command
- `bash tools/validate_live_chronicle_stack.sh --dataroot /mnt/d/autocapture --vllm-base-url http://127.0.0.1:8000`
- Deterministic baseline snapshot: `bash tools/baseline.sh /mnt/d/autocapture http://127.0.0.1:8000`
- Popup strict regression gate: `bash tools/run_popup_regression_strict.sh`

## Outputs
- `artifacts/live_stack/preflight_latest.json`
- `artifacts/live_stack/validation_latest.json`
- `artifacts/baseline/baseline_snapshot_latest.json`
- `artifacts/query_acceptance/popup_regression_latest.json`
- `artifacts/query_acceptance/popup_regression_misses_latest.json`

## Pass Criteria
- Preflight reports `ready=true`
- Preflight output includes `failure_codes=[]`
- Sidecar minimum checks pass:
  - `activity_signal_present=true`
  - `media_files_count_sampled>0`
  - Either `journal_ok && ledger_present` OR `metadata_mode_ok`
- Validation JSON has `"ok": true`
- Baseline snapshot has:
  - `summary.present_count>0`
  - stable `summary.normalized_sha256` when rerun with unchanged inputs
- Popup regression gate returns zero misses:
  - `sample_count==accepted_count`
  - `failed_count==0`

## Notes
- Localhost-only policy remains enforced.
- If blocked, do not flip implementation matrix status to complete; resolve blockers first.
