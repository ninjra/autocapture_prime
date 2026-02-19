# Golden Pipeline Core Remediation Validation (2026-02-18)

Plan source: `docs/plans/golden-pipeline-core-remediation-plan.md`

## Sprint execution summary

| Sprint | Scope | Validation result | Evidence |
| --- | --- | --- | --- |
| Sprint 0 | Foundational hardening (archive/plugin reload/validator timeout/spool/research/rrf) | pass | `tests/test_verify_archive_cli.py`, `tests/test_plugin_hotswap.py`, `tests/test_codex_validators.py`, `tests/test_capture_spool_idempotent.py`, `tests/test_research_runner.py`, `tests/test_rrf_fusion_determinism.py` |
| Sprint 1 | Truthful gate + matrix strict semantics | pass | `tools/eval_q40_matrix.py`, `tools/q40.sh`, `tools/run_golden_qh_cycle.sh`, `tools/release_gate.py`, `tests/test_eval_q40_matrix.py`, `tests/test_release_gate.py` |
| Sprint 2 | PromptOps enforcement + attribution | pass | `tests/test_promptops_required_path.py`, `tests/test_promptops_service.py`, `tests/test_promptops_api.py`, `tests/test_promptops_examples.py`, `tests/test_promptops_optimizer.py`, `tests/test_promptops_metrics_report.py`, `tests/test_promptops_eval_harness.py`, `tests/test_query_trace_fields.py`, `tests/test_gate_promptops_policy.py`, `tests/test_gate_promptops_perf.py` |
| Sprint 3 | Metadata-only query + VLM failure taxonomy | pass | `tests/test_process_single_screenshot_profile_gate.py`, `tests/test_cli_query_metadata_only.py`, `tests/test_http_localhost.py`, `tests/test_derived_records.py`, `tests/test_external_vllm_endpoint_policy.py` |
| Sprint 4 | Throughput/SLA + active/idle policy + observability | pass | `tests/test_runtime_conductor.py`, `tests/test_runtime_budgets.py`, `tests/test_resource_budget_enforcement.py`, `tests/test_resource_budgets.py`, `tests/test_concurrency_budget_enforced.py`, `tests/test_gate_slo_budget.py`, `tests/test_slo_budget_regression_gate.py`, `tests/test_gate_telemetry_schema.py`, `tests/test_telemetry_schema.py`, `tests/test_wsl2_routing_integration.py` |
| Sprint 5 | Soak admission + strict matrix closure wiring | pass (gate wiring), live matrix currently blocked | `tests/test_soak_admission_check.py`, `tests/test_run_advanced10_expected_eval.py`, strict matrix artifacts below |

## Sprint 3 Option A addendum (2026-02-19)

Applied additional metadata-first enforcement and retention policy hardening:

- metadata-only query harness now strips query-time `image_path` and forces `AUTOCAPTURE_ADV_HARD_VLM_MODE=off`;
- metadata-only harness sets `AUTOCAPTURE_QUERY_METADATA_ONLY_ALLOW_HARD_VLM=0` fail-closed;
- golden profiles (`golden_full`, `golden_qh`) now set:
  - `processing.on_query.allow_decode_extract=false`,
  - `processing.on_query.extractors.ocr=false`,
  - `processing.on_query.extractors.vlm=false`,
  - `processing.on_query.adv_hard_vlm_mode=off`,
  - `query.enable_synthesizer=false`,
  - `storage.no_deletion_mode=false`,
  - `storage.retention.evidence=6d`,
  - `storage.retention.processed_only=true`,
  - `storage.retention.images_only=true`,
  - `storage.retention.interval_s=86400`.

Validation evidence:

- `tests/test_run_advanced10_expected_eval.py`
- `tests/test_golden_full_profile_lock.py`
- strict golden profile hash lock refreshed (`config/profiles/golden_full.sha256`).

## Strict matrix semantics validation

### Real latest artifacts (fail-closed expected)

Command:

`./shell-lint-ps-wsl .venv/bin/python tools/eval_q40_matrix.py --advanced-json artifacts/advanced10/advanced20_latest.json --generic-json artifacts/advanced10/generic20_latest.json --strict --expected-total 40 --out artifacts/advanced10/q40_matrix_strict_latest.json`

Observed outcome:

- return code: `1`
- `ok=false`
- `matrix_total=40`
- `matrix_evaluated=0`
- `matrix_failed=0`
- `matrix_skipped=40`
- `failure_reasons=["matrix_evaluated_zero","strict_matrix_skipped_nonzero","strict_matrix_evaluated_mismatch"]`

### Synthetic strict-green fixture (pass expected)

Synthetic 20+20 fixture run with strict flags returned:

- return code: `0`
- `ok=true`
- `matrix_evaluated=40`
- `matrix_failed=0`
- `matrix_skipped=0`
- `failure_reasons=[]`

This verifies strict enforcement and positive path behavior.

## Consolidated regression run

Executed consolidated cross-sprint regression suite:

- `133 passed, 1 warning` in `66.47s`
- includes Sprint 0 through Sprint 5 task coverage and gates

## Current live closure status

- strict gate wiring is complete and fail-closed.
- current latest live artifacts do **not** satisfy 40/40 (`0 evaluated, 40 skipped`) and are now correctly blocked by strict mode.
- live `tools/q40.sh` execution reached `run_golden_qh_cycle.sh` phase `eval/running_advanced20`; completion is bounded by per-query timeouts and may take extended runtime under unstable VLM conditions.

## Validation snapshot (2026-02-19 Option A follow-up)

- targeted Option A regressions:
  - `tests/test_run_advanced10_expected_eval.py`: `18 passed`
  - `tests/test_golden_full_profile_lock.py`: `3 passed`
  - `tests/test_cli_query_metadata_only.py`: `1 passed`
  - `tests/test_process_single_screenshot_profile_gate.py`: `20 passed`
- schema/contract alignment:
  - added `storage.retention.processed_only`, `storage.retention.images_only`, and `storage.retention.image_only` to `contracts/config_schema.json`
  - refreshed contract lock via `tools/hypervisor/scripts/update_contract_lock.py`
- single-image strict ingest validation:
  - `bash tools/run_single_image_golden.sh artifacts/test_input_qh.png --skip-vllm-unstable`
  - result: `ok=true` report at `artifacts/single_image_runs/single_20260219T031428Z/report.json`
  - metadata includes retention eligibility marker:
    - `124f656ce81645e0a92bb6575ff08633/retention.eligible/rid_MTI0ZjY1NmNlODE2NDVlMGE5MmJiNjU3NWZmMDg2MzMvZXZpZGVuY2UuY2FwdHVyZS5mcmFtZS8w`
- implementation matrix verification:
  - `bash tools/ivm.sh`: `ok=true` and `gate_failures_total=0`
- full suite run (repo-wide):
  - `PYTHONPATH=. .venv/bin/pytest -q`
  - result: `7 failed, 933 passed, 8 skipped`
  - failing areas are outside Option A scope (`backlog_closure_guard`, `capture_consent`, `chronicle_contract_pin`, `ingest_dedupe`, `tray_launcher_script`)
- strict matrix check on current `*_latest.json` artifacts:
  - `matrix_total=40`
  - `matrix_evaluated=20`
  - `matrix_passed=4`
  - `matrix_failed=16`
  - `matrix_skipped=20`
  - strict failure reasons: `matrix_failed_nonzero`, `strict_matrix_skipped_nonzero`, `strict_matrix_evaluated_mismatch`

## Validation snapshot (2026-02-19 strict closure)

Strict closure rerun completed using one shared source report snapshot and strict fail-closed semantics.

- shared source report:
  - `artifacts/single_image_runs/single_20260219T042145Z/report.json`
  - `source_report_sha256=cd23ccf53536d49e3432789082f7e5e0fea94cd3d9dc0964b8b12d90cfbdaacd`
  - `source_report_run_id=23cb5476c21a4c38ae64792395efa1cf`
- advanced20 strict:
  - artifact: `artifacts/advanced10/advanced20_strict_latest.json`
  - `evaluated_total=20`, `evaluated_passed=20`, `evaluated_failed=0`, `rows_skipped=0`, `ok=true`
- generic20 strict:
  - artifact: `artifacts/advanced10/generic20_latest.json`
  - `evaluated_total=20`, `evaluated_passed=20`, `evaluated_failed=0`, `rows_skipped=0`, `ok=true`
- q40 strict matrix:
  - artifact: `artifacts/advanced10/q40_matrix_strict_latest.json`
  - `matrix_total=40`, `matrix_evaluated=40`, `matrix_passed=40`, `matrix_failed=0`, `matrix_skipped=0`
  - `failure_reasons=[]`, `ok=true`

Commands executed:

- `./shell-lint-ps-wsl .venv/bin/python tools/run_advanced10_queries.py --report artifacts/single_image_runs/single_20260219T042145Z/report.json --cases docs/query_eval_cases_advanced20.json --metadata-only --strict-all --repro-runs 1 --output artifacts/advanced10/advanced20_strict_latest.json`
- `./shell-lint-ps-wsl .venv/bin/python tools/run_advanced10_queries.py --report artifacts/single_image_runs/single_20260219T042145Z/report.json --cases docs/query_eval_cases_generic20.json --metadata-only --strict-all --repro-runs 1 --output artifacts/advanced10/generic20_latest.json`
- `./shell-lint-ps-wsl .venv/bin/python tools/eval_q40_matrix.py --advanced-json artifacts/advanced10/advanced20_strict_latest.json --generic-json artifacts/advanced10/generic20_latest.json --strict --expected-total 40 --out artifacts/advanced10/q40_matrix_strict_latest.json`
