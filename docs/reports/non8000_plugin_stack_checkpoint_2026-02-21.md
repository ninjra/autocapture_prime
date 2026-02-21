# Non-8000 Plugin Stack Checkpoint (2026-02-21)

## Scope Completed
- Added non-`8000` processing-only plugin contract:
  - `docs/contracts/plugin-stack-non8000-contract.md`
- Enforced contract in config matrix gate:
  - `tools/gate_config_matrix.py`
  - `artifacts/config/gate_config_matrix.json`
- Added strict Q40 gate:
  - `tools/gate_q40_strict.py`
  - `tests/test_gate_q40_strict.py`
- Added capture deprecation doctor enforcement tests:
  - `tests/test_capture_deprecation_enforced.py`
- Updated default config for non-`8000` mode:
  - capture plugins stay disabled
  - `builtin.processing.sst.ui_vlm=false`
  - `builtin.vlm.vllm_localhost=false`
  - idle VLM extraction disabled
  - non-`8000` SST/runtime/state contributors enabled by default

## Validation Executed
- `python -m pytest tests/test_gate_config_matrix.py tests/test_gate_q40_strict.py tests/test_capture_deprecation_enforced.py -q`
  - Result: pass (`9 passed`)
- `python tools/gate_config_matrix.py`
  - Result: pass (`ok=true`)
- `python -m pytest tests/test_release_gate.py tests/test_stage1_no_vlm_profile.py tests/test_query_eval_suite_exact.py -q`
  - Result: pass (`12 passed`)
- `python -m pytest tests/test_gate_promptops_policy.py tests/test_release_gate.py tests/test_gate_config_matrix.py tests/test_gate_q40_strict.py tests/test_capture_deprecation_enforced.py tests/test_validate_stage1_lineage_tool.py tests/test_stage1_completeness_audit_tool.py -q`
  - Result: pass (`25 passed`)

## Non-VLM Readiness Sweep
- Command:
  - `python tools/run_non_vlm_readiness.py --no-run-query-eval --output docs/reports/non_vlm_readiness_latest.json`
- Result:
  - `ok=true`
  - `failed_steps=[]`
  - `optional_failed_steps=["synthetic_gauntlet_80_metadata_only"]`
- Key strict Stage1 metrics (latest):
  - `lineage_complete=1524`
  - `lineage_incomplete=0`
  - `invalid_obs_payload=0`
  - `frames_queryable=1524/1524`
- Key artifacts:
  - `docs/reports/non_vlm_readiness_latest.json`
  - `artifacts/non_vlm_readiness/run_20260221T192757Z/lineage.json`
  - `artifacts/non_vlm_readiness/run_20260221T192757Z/stage1_completeness_audit.json`

## Known Pre-existing Blocker
- `python -m pytest tests/test_golden_full_profile_lock.py -q`
  - Fails due `config/profiles/golden_full.sha256` mismatch against current `config/profiles/golden_full.json`.
  - This checkpoint did not modify `config/profiles/golden_full.json` or its lock file.

## Known Optional Failure (Current Run)
- `synthetic_gauntlet_80_metadata_only` failed with:
  - `kernel_boot_failed:ConfigError:instance_lock_held`
- This did not fail readiness (`optional_failed_steps`) and indicates runtime lock contention during synthetic safe-mode boot.

## Next Required Step
- Run strict Q40 gate end-to-end with a fresh non-`8000` report:
  - produce report via `tools/query_eval_suite.py`/`tools/q40.sh`
  - validate with `tools/gate_q40_strict.py`

## Delta Update (2026-02-21 Late)
- Added fast stack preflight to readiness runner (`tools/run_non_vlm_readiness.py`):
  - checks `7411` sidecar health, `8000` health, and metadata DB readability
  - fails fast with `error=preflight_failed` when required preconditions are not met
  - supports explicit bypass via `--no-require-preflight`
- Added tests for new readiness preflight behavior:
  - `tests/test_run_non_vlm_readiness_tool.py`
- Refreshed plugin lock hashes to resolve `builtin.storage.sqlcipher artifact hash mismatch`:
  - `config/plugin_locks.json` regenerated via `tools/hypervisor/scripts/update_plugin_locks.py`

### Quick Verification
- Preflight-only run fails fast when sidecar is down (expected):
  - `python tools/run_non_vlm_readiness.py --no-run-pytest --no-run-gates --no-run-query-eval --no-run-synthetic-gauntlet --no-revalidate-markers`
  - Result: `error=preflight_failed` with `sidecar_7411.ok=false`
- Query harness boot from isolated readiness config now exposes metadata capability:
  - `safe_mode=True,fast_boot=True -> has_meta=true`
  - `safe_mode=False,fast_boot=True -> has_meta=true`
- Minimal query eval smoke passes:
  - `tools/query_eval_suite.py` with a one-case metadata-only fixture
  - Result: `cases_total=1, cases_passed=1, ok=true`
