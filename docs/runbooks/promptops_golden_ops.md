# PromptOps Golden Ops Runbook

## Purpose
Operational checks for the golden PromptOps pipeline with citation-first answers and plugin-path tracing.

## Preconditions
- `.venv` available
- Local data directories writable
- Localhost services only

## Verification Commands
- PromptOps metrics report:
  - `.venv/bin/python tools/promptops_metrics_report.py`
- PromptOps perf gate:
  - `.venv/bin/python tools/gate_promptops_perf.py`
- PromptOps policy gate:
  - `.venv/bin/python tools/gate_promptops_policy.py`
- Screen schema gate:
  - `.venv/bin/python tools/gate_screen_schema.py`
- Q/H plugin validation trace:
  - `.venv/bin/python tools/generate_qh_plugin_validation_report.py --report artifacts/single_image_runs/single_20260216T005126Z/report.json`

## Expected Outputs
- `artifacts/promptops/metrics_report_latest.json`
- `artifacts/perf/gate_promptops_perf.json`
- `artifacts/promptops/gate_promptops_policy.json`
- `artifacts/phaseA/gate_screen_schema.json`
- `artifacts/advanced10/question_validation_plugin_trace_latest.json`
- `docs/reports/question-validation-plugin-trace-2026-02-13.md`

## Rollback
- Revert `config/profiles/golden_full.json` and `config/profiles/golden_full.sha256` to last known-good commit.
- Re-run all gates before re-enabling golden rollout.

