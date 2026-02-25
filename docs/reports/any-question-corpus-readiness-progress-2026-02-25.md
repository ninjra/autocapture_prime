# Any-Question Corpus Readiness Progress (2026-02-25)

## Scope
Progress update for `docs/plans/any-question-corpus-readiness-plan.md`, focused on Sprint 1 and Sprint 2 deliverables.

## Sprint Status
- Sprint 1 (Baseline truth/observability): complete
- Sprint 2 (Stage1 contract + reap safety + audit integrity gate): complete for tooling/gates; live corpus still failing Stage1 contract gate

## Implemented This Pass
- Added Stage1 minimum contract spec:
  - `docs/contracts/stage1_minimum_contract.md`
- Added Stage1 contract gate:
  - `tools/gate_stage1_contract.py`
  - `tests/test_gate_stage1_contract.py`
- Added audit log integrity gate:
  - `tools/gate_audit_log_integrity.py`
  - `tests/test_gate_audit_log_integrity.py`
- Wired both gates into readiness runner:
  - `tools/run_non_vlm_readiness.py`
  - readiness report now includes:
    - `plugin_enablement`
    - `stage1_contract`
    - `audit_integrity`
    - normalized `failure_class_counts`

## Validation (Deterministic)
- Targeted test suites:
  - `tests/test_gate_plugin_enablement.py`
  - `tests/test_gate_stage1_contract.py`
  - `tests/test_gate_audit_log_integrity.py`
  - `tests/test_run_non_vlm_readiness_tool.py`
- Result:
  - `24 passed`, `0 failed`

## Live Gate Snapshot
- Plugin enablement gate:
  - output: `/tmp/gate_plugin_enablement_sprint2.json`
  - `ok=true`, `required_count=33`, `failed_count=0`
- Stage1 contract gate:
  - output: `/tmp/gate_stage1_contract_sprint2.json`
  - `ok=false`
  - counts:
    - `frames_total=8791`
    - `frames_queryable=661`
    - `frames_blocked=8130`
  - top blockers:
    - `retention_eligible_missing_or_invalid=8130`
    - `obs_uia_focus_missing_or_invalid=8130`
    - `obs_uia_context_missing_or_invalid=8130`
    - `obs_uia_operable_missing_or_invalid=8130`
- Audit integrity gate:
  - output: `/tmp/gate_audit_log_integrity_sprint2.json`
  - `ok=true`
  - warnings:
    - `timestamp_regression=849` (reported as warning-only telemetry)

## Operational Meaning
- Tooling now deterministically proves whether Stage1 is reap-safe.
- Current corpus is not yet fully Stage1-contract compliant; retention/query safety remains blocked for affected frames until remediation/backfill closes the 8130-frame gap.

## Next Step (Sprint 3)
- Enforce full Stage2+ plugin stack completion proof and persist deterministic per-frame plugin completion records suitable for query diagnostics.

## Sprint 3 Start (Implemented)
- Added deterministic per-frame plugin completion records:
  - record type: `derived.ingest.plugin.completion`
  - record id: deterministic from source frame id
  - writes occur in handoff ingest success and failure paths
- Files:
  - `autocapture/storage/stage1.py`
  - `autocapture_nx/ingest/handoff_ingest.py`
  - `tests/test_stage1_retention_markers.py`
  - `tests/test_handoff_ingest.py`
- New counter surfaced in handoff stats:
  - `stage1_plugin_completion_records`

Validation:
- `tests/test_stage1_retention_markers.py`
- `tests/test_handoff_ingest.py`
- combined regression subset:
  - `41 passed`, `0 failed`
