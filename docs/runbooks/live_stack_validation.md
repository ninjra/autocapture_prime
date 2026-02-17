# Live Stack Validation

## Purpose
Validate live sidecar data availability and localhost VLM reachability for operational closure.

## Command
- `bash tools/validate_live_chronicle_stack.sh --dataroot /mnt/d/autocapture --vllm-base-url http://127.0.0.1:8000`

## Outputs
- `artifacts/live_stack/preflight_latest.json`
- `artifacts/live_stack/validation_latest.json`

## Pass Criteria
- Preflight reports `ready=true`
- Sidecar minimum checks pass:
  - `activity_signal_present=true`
  - `media_files_count_sampled>0`
  - Either `journal_ok && ledger_present` OR `metadata_mode_ok`
- Validation JSON has `"ok": true`

## Notes
- Localhost-only policy remains enforced.
- If blocked, do not flip implementation matrix status to complete; resolve blockers first.
