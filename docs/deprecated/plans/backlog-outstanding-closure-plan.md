# Plan: Backlog Outstanding Closure

**Generated**: 2026-02-16  
**Estimated Complexity**: High

## Overview
Close all currently detected backlog markers from the repo-wide miss inventory and clear `gate_full_repo_miss_matrix`.

Current outstanding:
- 18 unchecked checklist rows in `docs/plans/promptops-four-pillars-improvement-plan.md`
- 1 `partial` row in `docs/reports/autocapture_prime_codex_implementation_matrix.md`

## Skills To Use For Implementation (and Why)
- `plan-harder`: governs phased execution, dependencies, and closure criteria.
- `golden-answer-harness`: proves answer quality/correctness closure using deterministic Q/H runs.
- `evidence-trace-auditor`: proves citeability closure (claim-to-evidence or explicit indeterminate).
- `deterministic-tests-marshal`: prevents flaky closure and ensures reproducible pass/fail outcomes.
- `perf-regression-gate`: validates p50/p95/perf checklist closure with measurable thresholds.
- `resource-budget-enforcer`: validates active/idle budget behavior for performance pillar.
- `config-matrix-validator`: validates profile/plugin/safe-mode matrix closure items.
- `audit-log-integrity-checker`: validates append-only audit chain requirements in closure items.

## Prerequisites
- `.venv` is available and can run repo tools.
- Write access to `docs/reports/` and `artifacts/`.
- Sidecar + localhost VLM availability for live operational closure (only needed for final operational row).

## Sprint 1: Normalize and Map Remaining Backlog
**Goal**: Create an authoritative map from each miss row to closure evidence and validation command.
**Demo/Validation**:
- `docs/reports/backlog_closure_map_2026-02-16.md` exists with 19/19 row mappings.
- Validation script confirms no unmapped row.

### Task 1.1: Build closure map
- **Location**: `docs/reports/backlog_closure_map_2026-02-16.md`
- **Description**: Map each row from `artifacts/repo_miss_inventory/latest.json` to closure artifact + command.
- **Complexity**: 3
- **Dependencies**: None
- **Acceptance Criteria**:
  - Every row has owner file, closure signal, command, expected artifact path.
  - Includes explicit per-row crosswalk fields:
    - `row_key` (source_path + line + snippet hash)
    - `closure_artifact`
    - `closure_command`
    - `expected_signal`
- **Validation**:
  - New checker script returns pass for 19/19 coverage.

### Task 1.2: Enforce generated-report closure via regeneration
- **Location**: `tools/gate_full_repo_miss_matrix.py`, `tests/test_gate_full_repo_miss_matrix.py`
- **Description**: Ensure derived-report rows are closed only by regeneration, not manual edits.
- **Complexity**: 4
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Derived-report closure path is deterministic and test-backed.
- **Validation**:
  - Unit test for manual-edit rejection and regeneration acceptance.

## Sprint 2: Close PromptOps Checklist Backlog (18 rows)
**Goal**: Close the 18 unchecked checklist items with objective artifacts.
**Demo/Validation**:
- All 18 items changed to checked with evidence links.
- PromptOps policy/perf/schema gates pass.

### Task 2.1: Performance closure evidence
- **Location**: `tools/promptops_metrics_report.py`, `artifacts/promptops/metrics_report_latest.json`, `docs/reports/promptops_perf_closure_2026-02-16.md`
- **Description**: Generate and pin baseline/current metrics for latency, timing, and success path signals.
- **Complexity**: 4
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Metrics demonstrate checklist claims for stage timing and performance measurability.
- **Validation**:
  - `tools/gate_promptops_perf.py` pass + report snapshot.

### Task 2.2: Accuracy/citeability closure evidence
- **Location**: `tools/run_advanced10_queries.py`, `tools/generate_qh_plugin_validation_report.py`, `docs/reports/qh_plugin_validation_latest.md`
- **Description**: Produce deterministic Q/H class-level correctness + citation evidence.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Strategy path explicit; claims are citation-backed or marked indeterminate.
- **Validation**:
  - Golden harness report + evidence trace audit report.

### Task 2.3: Security/policy/audit closure evidence
- **Location**: `tools/gate_promptops_policy.py`, `artifacts/promptops/gate_promptops_policy.json`, `docs/reports/promptops_policy_audit_closure_2026-02-16.md`
- **Description**: Capture fail-closed endpoint policy, egress-only sanitization policy, and audit-chain integrity evidence.
- **Complexity**: 5
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Checklist items for endpoint policy, redaction policy, and audit reconstruction are evidenced.
- **Validation**:
  - Policy gate + audit integrity checker pass artifacts.

### Task 2.4: Screen contract/schema closure evidence
- **Location**: `tools/gate_screen_schema.py`, `docs/schemas/ui_graph.schema.json`, `docs/schemas/provenance.schema.json`, `docs/reports/screen_contract_closure_2026-02-16.md`
- **Description**: Prove parse/index/answer contract coverage and schema CI validation.
- **Complexity**: 5
- **Dependencies**: Task 2.3
- **Acceptance Criteria**:
  - Contract and schema checklist items have direct test/gate evidence.
- **Validation**:
  - Schema gate pass + contract traceability entries.

### Task 2.5: Check off all 18 backlog checkboxes
- **Location**: `docs/plans/promptops-four-pillars-improvement-plan.md`
- **Description**: Flip each checkbox only after corresponding evidence exists; append direct evidence link per item.
- **Complexity**: 2
- **Dependencies**: Tasks 2.1–2.4
- **Acceptance Criteria**:
  - Zero unchecked rows remain in this plan for the tracked backlog set.
  - Each checked row includes its exact `row_key` from Task 1.1 crosswalk and evidence link.
- **Validation**:
  - Miss inventory no longer reports these 18 rows.

## Sprint 3: Close Implementation Matrix Partial Row (1 row)
**Goal**: Resolve `partial` status in codex implementation matrix through operational evidence.
**Demo/Validation**:
- Row 6 status becomes `complete` via regeneration flow.

### Task 3.0: Operational preflight/blocker gate
- **Location**: `tools/preflight_live_stack.py` (new), `artifacts/live_stack/preflight_latest.json`
- **Description**: Verify sidecar stream health + localhost VLM health before Task 3.1 executes.
- **Complexity**: 3
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Emits explicit `ready=true|false` with blocker reasons.
  - If `ready=false`, matrix row remains `partial` and closure is blocked (no status override).
- **Validation**:
  - Preflight artifact is required input for Task 3.1.

### Task 3.1: Operational live-stack validator
- **Location**: `tools/validate_live_chronicle_stack.sh` (new), `docs/runbooks/live_stack_validation.md` (new)
- **Description**: One-command validator for sidecar zstd/protobuf ingest + live localhost VLM latency checks.
- **Complexity**: 6
- **Dependencies**: Task 3.0
- **Acceptance Criteria**:
  - Emits machine-readable pass/fail artifact with thresholds.
- **Validation**:
  - `artifacts/live_stack/validation_latest.json` pass.

### Task 3.2: Regenerate matrix and close partial row
- **Location**: `docs/reports/autocapture_prime_codex_implementation_matrix.md` (via generator path)
- **Description**: Regenerate report from evidence; change row 6 to `complete` only if operational checks pass.
- **Complexity**: 3
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - No manual-only status override; row derived from validation.
- **Validation**:
  - Miss inventory no longer has `doc_table_status` row.

## Sprint 4: Final Backlog Gate Closure
**Goal**: Clear miss matrix gate and lock no-drift closure.
**Demo/Validation**:
- `tools/gate_full_repo_miss_matrix.py --refresh` passes with zero rows.
- Full suite run returns `status=ok`.

### Task 4.1: Add backlog closure guard test
- **Location**: `tests/test_backlog_closure_guard.py` (new)
- **Description**: Assert tracked backlog markers cannot reappear without failing tests, using Task 1.1 crosswalk row keys and latest miss inventory as the source of truth.
- **Complexity**: 4
- **Dependencies**: Sprints 2–3
- **Acceptance Criteria**:
  - Test fails on any reopened tracked marker from the closed row-key set.
  - Test fails if closure map and miss inventory row-key normalization drift.
- **Validation**:
  - Included in `tools/run_all_tests.py` pipeline.

### Task 4.2: Final end-to-end verification
- **Location**: `tools/run_all_tests.py`, `tools/run_all_tests_report.json`, `docs/reports/backlog_closure_final_2026-02-16.md`
- **Description**: Execute full gates/tests and publish final closure summary.
- **Complexity**: 2
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - No miss matrix failures and no backlog rows outstanding.
- **Validation**:
  - Final report shows all closure criteria met.

## Testing Strategy
- Unit: closure map and miss classification logic.
- Integration: promptops perf/policy/schema + Q/H validation reports.
- Operational: live sidecar + localhost VLM closure validator.
- End-to-end: full gate chain via `tools/run_all_tests.py`.

## Potential Risks & Gotchas
- Manual checklist flips without evidence can fake closure.
  - Mitigation: evidence link required and closure guard tests.
- Derived reports may drift from source evidence.
  - Mitigation: regeneration-only closure policy.
- Live VLM instability may block the final partial-row closure.
  - Mitigation: explicit blocked status and retry window; do not mark complete until pass.
- Flaky tests can create false green.
  - Mitigation: deterministic harness and repeated-run verification.

## Rollback Plan
1. Revert doc checkbox/status edits if closure evidence fails.
2. Keep generated evidence artifacts for postmortem.
3. Re-run closure sequence before re-applying status updates.
