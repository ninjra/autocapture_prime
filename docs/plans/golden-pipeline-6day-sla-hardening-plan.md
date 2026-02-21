# Plan: Golden Pipeline 6-Day SLA Hardening

**Generated**: 2026-02-18  
**Estimated Complexity**: High

## Overview
This plan closes all remaining blockers for `autocapture_prime` golden-pipeline readiness:

- Metadata-only query path (no query-time VLM inference)
- Full extraction + indexing + retrieval completed within a strict 6-day retention window
- 40-question matrix (`Q1..Q10` + `H1..H10` + generic 20) evaluated deterministically and promoted only on stable correctness
- Release and soak gates fail closed on throughput, correctness, determinism, or durability regressions

Primary strategy:
1. Lock architecture policy and contracts first.
2. Add hard throughput/SLA instrumentation and burn-down scheduler behavior.
3. Improve extraction quality in batch processing only.
4. Enforce deterministic, citation-first evaluation gates.
5. Prove with soak and operational runbooks.

## Skills Plan (Planning vs Implementation)

### Planning Skills (this plan)
- `plan-harder`: primary planning workflow and sprint decomposition.
- `config-matrix-validator`: map/validate endpoint and profile contract assumptions.
- `golden-answer-harness`: structure acceptance criteria for Q/H matrix and drift checks.
- `resource-budget-enforcer`: shape idle/active resource and backlog-SLA policies.
- `perf-regression-gate`: define throughput/cost regression gates.

### Implementation Skills (execution phase)
- `golden-answer-harness`: evaluate and gate Q/H correctness and drift.
- `resource-budget-enforcer`: validate idle burn-down scheduler and 6-day catch-up projections.
- `perf-regression-gate`: enforce processing throughput regressions.
- `deterministic-tests-marshal`: confirm repeatability and flake-free gates.
- `python-observability` + `logging-observability`: expose pipeline internals, queue progress, and failure causes.
- `evidence-trace-auditor`: verify claim->evidence trace completeness and fail closed on uncitable outputs.
- `state-recovery-simulator`: validate crash/restart idempotency and no-loss processing state.
- `config-matrix-validator`: keep canonical endpoint/profile matrix correct and drift-free.

## Prerequisites
- Hypervisor services reachable in same WSL namespace:
  - `8000 /v1/models` (VLM)
  - `8001 /v1/models` (embeddings)
  - `8011 /health` (grounding)
  - `34221 /statusz` + `/v1/chat/completions` (non-popup query owner)
  - `8787 /health` (popup-only)
- Sidecar writing to `/mnt/d/autocapture` with usable media + metadata/journal/ledger.
- Existing golden profile and matrix artifacts present.

## Scope Clarifications
- In scope:
  - Batch extraction, indexing, ledger state durability, queryability from derived data only.
  - 40-question correctness + determinism gates.
  - 6-day processing SLA and burn-down control.
- Out of scope:
  - Capture plugin reintroduction (deprecated).
  - Query-time raw screenshot reasoning for golden path.

## Sprint 1: Contract Lock and Query Policy Freeze
**Goal**: Make architecture non-negotiable and machine-enforced.
**Demo/Validation**:
- Metadata-only query path proven to never invoke hard-VLM.
- Endpoint contract checks pass with exact per-port probe paths.

### Task 1.1: Finalize Query-Time Policy Guard
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/cli.py`, `tools/run_advanced10_queries.py`
- **Description**: enforce metadata-only query path as default in golden eval/CLI; batch processing remains only VLM reasoning path.
- **Complexity**: 6
- **Dependencies**: none
- **Acceptance Criteria**:
  - Query path never calls hard-VLM when metadata-only flag is set.
  - Eval harness does not require query-time VLM preflight in metadata-only mode.
- **Validation**:
  - `tests/test_query_advanced_display.py`
  - `tests/test_run_advanced10_expected_eval.py`
  - `tests/test_cli_query_metadata_only.py`

### Task 1.2: Endpoint Contract Freeze
- **Location**: `autocapture_nx/runtime/service_ports.py`, `tools/preflight_live_stack.py`, `docs/runbooks/live_stack_validation.md`
- **Description**: keep canonical endpoint/probe contract and fail codes stable.
- **Complexity**: 4
- **Dependencies**: none
- **Acceptance Criteria**:
  - Probes use exact paths for all services.
  - Failure output is per-service and machine-readable.
- **Validation**:
  - `tests/test_service_ports.py`
  - `tests/test_preflight_live_stack.py`

## Sprint 2: 6-Day SLA Metrics and Backlog Controller
**Goal**: Make SLA measurable and enforceable, not inferred.
**Demo/Validation**:
- Dashboard/JSON artifact shows ingest rate, process rate, backlog age, projected catch-up hours.
- Gate fails when projected catch-up exceeds 6 days.

### Task 2.1: Add Backlog SLA Metrics
- **Location**: `autocapture_nx/processing/idle.py`, `autocapture/runtime/scheduler.py`, `autocapture_nx/kernel/telemetry.py`
- **Description**: emit deterministic metrics:
  - `oldest_unprocessed_age_hours`
  - `processed_items_per_hour`
  - `ingested_items_per_hour`
  - `projected_catchup_hours`
- **Complexity**: 8
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Metrics are persisted and queryable from run artifacts.
  - Projection formula is deterministic and documented.
- **Validation**:
  - new tests `tests/test_backlog_sla_metrics.py` (add)
  - telemetry schema gate update

### Task 2.2: Burn-Down Scheduler Mode
- **Location**: `autocapture/runtime/scheduler.py`, `autocapture/runtime/conductor.py`, `autocapture_nx/processing/idle.py`
- **Description**: add oldest-first burn-down mode when backlog age threshold exceeded; cap by idle CPU/RAM budgets.
- **Complexity**: 8
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Mode enters/exits deterministically with hysteresis.
  - No foreground budget violations.
- **Validation**:
  - new tests `tests/test_scheduler_burndown_mode.py` (add)
  - `resource-budget-enforcer` checks

### Task 2.3: SLA Gate
- **Location**: `tools/release_gate.py`, `tools/soak/admission_check.py`, `docs/runbooks/release_gate_ops.md`
- **Description**: block release/soak when projected catch-up > 144h (6 days).
- **Complexity**: 5
- **Dependencies**: Tasks 2.1, 2.2
- **Acceptance Criteria**:
  - explicit gate failure code and actionable diagnostics.
- **Validation**:
  - new tests `tests/test_sla_gate.py` (add)

## Sprint 3: Durable Processing Ledger (No Partial Loss)
**Goal**: Ensure every capture reaches queryable derived state idempotently.
**Demo/Validation**:
- Restart/crash simulation preserves progress and resumes safely.

### Task 3.1: Normalize Processing State Machine
- **Location**: `autocapture/storage/archive.py`, `autocapture/capture/spool.py`, `autocapture/capture/pipelines.py`, `autocapture_nx/kernel/derived_records.py`
- **Description**: explicit immutable state transitions:
  - `captured -> extracted -> embedded -> indexed -> queryable`
  - idempotent writes and collision detection.
- **Complexity**: 8
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - no silent `False` write outcomes;
  - duplicate processing is idempotent.
- **Validation**:
  - `tests/test_capture_spool_idempotent.py`
  - new tests `tests/test_processing_state_machine.py` (add)

### Task 3.2: Crash Recovery Proof
- **Location**: `autocapture/runtime/*`, `tools/soak/*`, `tests/*recovery*`
- **Description**: run crash-fuzz and verify no record loss/corruption on resume.
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - recovery report shows no gaps and consistent ledger chain.
- **Validation**:
  - `state-recovery-simulator`
  - new tests `tests/test_query_recovery_no_gap.py` (add)

## Sprint 4: Batch Extractor Accuracy Uplift for Q40
**Goal**: Improve derived-data quality so metadata-only queries answer correctly.
**Demo/Validation**:
- Q/H matrix improves via batch outputs only (no query-time hard-VLM).

### Task 4.1: Extraction Attribution and Error Taxonomy
- **Location**: `tools/run_advanced10_queries.py`, `autocapture_nx/kernel/query.py`, `docs/reports/question-validation-plugin-trace-2026-02-13.md`
- **Description**: emit per-case failure taxonomy (missing fields, bad pairing, ordering, confidence drift).
- **Complexity**: 6
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - each failed case has actionable extraction stage attribution.
- **Validation**:
  - `tests/test_query_trace_fields.py`
  - new `tests/test_q40_failure_taxonomy.py` (add)

### Task 4.2: Structured Extractor Improvements (Generic Classes)
- **Location**: `autocapture_nx/processing/sst/*`, `autocapture_nx/kernel/query.py`
- **Description**: improve generic class extractors:
  - window inventory, focus evidence, timeline row grouping, details KV pairing,
  - calendar row parsing, chat tuple parsing, console color-line grouping, browser chrome parsing.
- **Complexity**: 9
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - improvements generalize across variant screenshots (no tactical shortcuts).
- **Validation**:
  - `tests/test_query_advanced_display.py`
  - `tools/q40.sh` + `tools/eval_q40_matrix.py`

### Task 4.3: Confidence Calibration + Indeterminate Discipline
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture/memory/answer_orchestrator.py`
- **Description**: tighten confidence gating to avoid false “ok”; prefer explicit indeterminate when evidence is insufficient.
- **Complexity**: 7
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - no “passed but wrong” marker states.
- **Validation**:
  - golden harness checks with reviewer feedback loop.

## Sprint 5: PromptOps Background Optimization Loop
**Goal**: PromptOps continuously improves templates and routing metrics in background.
**Demo/Validation**:
- promptops emits optimization events and template updates with rollback safety.

### Task 5.1: PromptOps Self-Review Job
- **Location**: `autocapture/promptops/optimizer.py`, `autocapture/promptops/engine.py`, `tools/promptops_optimize_once.py`
- **Description**: nightly/idle review of failed queries, suggest split/merge/update templates, write candidate prompts with metrics.
- **Complexity**: 7
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - change proposals include measured delta and canary gate.
- **Validation**:
  - `tests/test_promptops_optimizer.py`

### Task 5.2: PromptOps Gate Integration
- **Location**: `tools/release_gate.py`, `tools/gate_promptops_policy.py`, `docs/runbooks/promptops_golden_ops.md`
- **Description**: require promptops policy checks in golden release flow.
- **Complexity**: 5
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - release fails closed on promptops policy regressions.
- **Validation**:
  - `tests/test_gate_promptops_policy.py`

## Sprint 6: Golden + Soak Release Closure
**Goal**: Final proof: Q40 correctness, SLA guarantee, and 24h stability.
**Demo/Validation**:
- All gates pass, soak artifacts clean, matrix updated to complete.

### Task 6.1: Golden Matrix Gate
- **Location**: `tools/q40.sh`, `tools/eval_q40_matrix.py`, `docs/reports/implementation_matrix.md`
- **Description**: enforce `40/40` pass for promotion profile (or explicit fail and hold).
- **Complexity**: 6
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - matrix reports no skipped cases in metadata-only mode.
- **Validation**:
  - `artifacts/advanced10/q40_matrix_latest.json`

### Task 6.2: 24h Soak Admission + Completion
- **Location**: `tools/soak/admission_check.py`, `tools/soak/run_golden_qh_soak.sh`, `docs/runbooks/release_gate_ops.md`
- **Description**: require pre/post soak admission checks including SLA metrics.
- **Complexity**: 6
- **Dependencies**: Sprints 2, 3, 4
- **Acceptance Criteria**:
  - no crash loops, no persistent backlog growth, no corrupted ledgers.
- **Validation**:
  - soak summary + admission artifacts.

### Task 6.3: Matrix + Doc Finalization
- **Location**: `docs/reports/implementation_matrix.md`, `docs/reports/autocapture_prime_4pillars_optimization_matrix.md`, `docs/reports/implementation_matrix_remaining_2026-02-12.md`
- **Description**: mark only truly completed items, preserve unresolved rows as blockers.
- **Complexity**: 4
- **Dependencies**: all prior sprints
- **Acceptance Criteria**:
  - no false “complete” statuses.
- **Validation**:
  - `tools/refresh_verify_impl_matrix.py`

## Testing Strategy
- Unit:
  - state-machine, scheduler mode transitions, parser/extractor units.
- Integration:
  - single-image golden cycle and advanced eval.
- Determinism:
  - repeated run signatures and confidence drift checks.
- Performance:
  - throughput/budget gates under controlled synthetic load.
- Soak:
  - 24h run with admission pre/post checks and artifact diffing.

## Hard Release Criteria (Do Not Ship If Any Fail)
- Q40 matrix evaluated and passing target profile.
- No skipped cases due metadata-only preflight behavior.
- Projected catch-up time <= 144h at gate time.
- Oldest unprocessed age within SLA threshold.
- No uncitable claims in golden answers.
- No processing-state corruption/recovery gaps.

## Potential Risks & Gotchas
- VLM service instability may still affect batch extraction completeness.
  - Mitigation: isolate batch windows + retry/journaled extractor tasks + no query-time dependency.
- Backlog estimates can be noisy during bursty capture.
  - Mitigation: rolling-window estimator + conservative confidence bounds.
- Over-tight gates can block progress in early tuning.
  - Mitigation: staged thresholds with explicit `beta` vs `release` modes.
- Hidden tactical logic can re-enter through hotfixes.
  - Mitigation: enforce taxonomy-based extractor class tests and no hardcoded query text heuristics.

## Rollback Plan
- Keep current golden profile lockfile and release gate behavior as fallback.
- Feature-flag burn-down controller and new SLA gate independently.
- Revert to last known-good `config/profiles/golden_full.json` + matrix lock if regressions found.

