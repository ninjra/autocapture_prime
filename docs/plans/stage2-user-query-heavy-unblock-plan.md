# Plan: Stage2 User Query Heavy Unblock

**Generated**: 2026-02-20  
**Estimated Complexity**: High

## Overview
Unblock Stage2+ extraction in `USER_QUERY` mode by fixing runtime governor gating so forced query/enrich paths can acquire heavy leases and avoid immediate mode-based preemption. Keep existing budget and safety controls intact, prove behavior with deterministic tests, and add operational diagnostics so sidecar+WSL deployments can verify the fix quickly.

Approach:
- Patch the narrow deterministic root cause in `autocapture/runtime/governor.py`.
- Add/expand unit and integration tests around lease/preemption behavior.
- Verify end-to-end behavior through `RuntimeConductor.run_once(force=True)` and scheduler admission.
- Add operator-facing diagnostics and rollout guardrails.

## Prerequisites
- Resolve current local contract-lock blocker (`contracts/config_schema.json` hash mismatch) or run validation in an environment where kernel boot is not blocked.
- Test environment with `.venv` and `pytest` available.
- Access to the same runtime config path used by production (`/mnt/d/autocapture/config` and `/mnt/d/autocapture`).
- Baseline artifact from current behavior (before patch) for comparison.

## Assumptions
- `query_intent=True` is set only by explicit operator-forced flows (for example `run_once(force=True)`/`autocapture enrich`) and not by normal interactive query calls.
- Budget settings remain the authoritative safeguard; this plan does not loosen budget caps, only mode gating.
- Hypervisor/sidecar runtime will run the same governor code path as this repo once merged.

## Skills by Section (with rationale)
- Research & Contract Freeze: `plan-harder`, `shell-lint-ps-wsl`
  - Why: structure phased plan and keep command execution consistent across WSL/PowerShell environments.
- Governor/Scheduler Core Patch: `ccpm-debugging`, `python-testing-patterns`
  - Why: root-cause-first patching and deterministic unit tests for regression safety.
- Integration & Runtime Verification: `testing`, `resource-budget-enforcer`
  - Why: validate behavior under realistic runtime signals and confirm budget/pause semantics still hold.
- Evidence/Citeability Validation: `evidence-trace-auditor`, `golden-answer-harness`
  - Why: ensure Stage2 output is not only running but usable for evidence-backed query responses.
- Rollout Safety & Recovery: `state-recovery-simulator`, `audit-log-integrity-checker`
  - Why: protect long-running runtime behavior and verify append-only operational evidence.

## Sprint 1: Freeze Runtime Contract and Reproduction
**Goal**: Establish exact expected behavior for `USER_QUERY` leases/preemption and capture a deterministic failing baseline.  
**Demo/Validation**:
- Single baseline report showing current fail mode.
- Explicit acceptance matrix for `ACTIVE_CAPTURE_ONLY`, `IDLE_DRAIN`, `USER_QUERY`.

### Task 1.0: Contract-Lock Unblock Spike
- **Location**: `tools/contract_lock_repair.md`, `docs/reports/contract_lock_repair_result.json`
- **Description**:
  - Create a small reproducible procedure to clear/refresh contract lock mismatch (`contracts/config_schema.json`) so local boot verification is unblocked.
  - Capture exact before/after status and checksum evidence.
- **Complexity**: 3/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - Kernel boot gate no longer fails due to contract lock in the validation environment.
- **Validation**:
  - Run boot/gate check before and after; report shows mismatch resolved.

### Task 1.1: Define USER_QUERY Heavy-Admission Contract
- **Location**: `docs/contracts/runtime-user-query-heavy-contract.md`
- **Description**:
  - Specify expected behavior when `query_intent=True`:
    - heavy lease allowed when budgets permit,
    - no mode-only preemption in `USER_QUERY`,
    - existing budget exhaustion preemption still enforced.
  - Include truth table by mode and reason.
- **Complexity**: 3/10
- **Dependencies**: Task 1.0
- **Acceptance Criteria**:
  - Contract explicitly separates mode gating from budget gating.
  - Contract includes backward-compatibility notes.
- **Validation**:
  - Peer review against `RuntimeConductor.run_once(force=True)` flow.

### Task 1.2: Capture Deterministic Baseline Failure
- **Location**: `docs/reports/runtime_user_query_heavy_baseline.json`
- **Description**:
  - Run targeted tests and/or runtime harness to demonstrate:
    - lease denied in `USER_QUERY`,
    - mode-based preemption triggers after grace.
- **Complexity**: 4/10
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Baseline report contains reproducible inputs/signals and observed outcomes.
- **Validation**:
  - Re-run baseline check twice; results match.

## Sprint 2: Governor Logic Patch (Core Fix)
**Goal**: Implement the minimal deterministic fix in governor lease and preemption logic.  
**Demo/Validation**:
- Targeted unit tests show heavy jobs admitted in `USER_QUERY`.
- No regressions in active-mode heavy denial when no query intent.

### Task 2.1: Patch Lease Gate for USER_QUERY
- **Location**: `autocapture/runtime/governor.py`
- **Description**:
  - Update heavy lease admission condition from `mode == IDLE_DRAIN` to `mode in {IDLE_DRAIN, USER_QUERY}` while still requiring `heavy_allowed`.
- **Complexity**: 3/10
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Heavy lease allowed in `USER_QUERY` when budget permits.
  - Lease still denied in `ACTIVE_CAPTURE_ONLY`.
- **Validation**:
  - New/updated unit tests in `tests/test_governor_gating.py`.

### Task 2.2: Patch Mode-Based Preemption Logic
- **Location**: `autocapture/runtime/governor.py`
- **Description**:
  - Exclude `USER_QUERY` from mode-only preemption checks tied to grace/suspend deadline.
  - Preserve preemption on fullscreen and budget exhaustion paths.
- **Complexity**: 4/10
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - `USER_QUERY` does not preempt solely due to non-idle mode.
  - Existing non-`USER_QUERY` preemption behavior unchanged.
- **Validation**:
  - Unit tests for elapsed grace behavior with `query_intent=True/False`.

### Task 2.3: Add Precise Unit Tests for New Behavior
- **Location**: `tests/test_governor_gating.py`
- **Description**:
  - Add tests equivalent to:
    - heavy admitted in `USER_QUERY` while active,
    - no mode-only preemption in `USER_QUERY`,
    - existing immediate preemption behavior still valid for active non-query mode.
- **Complexity**: 4/10
- **Dependencies**: Task 2.1, Task 2.2
- **Acceptance Criteria**:
  - Tests fail on pre-patch logic and pass post-patch.
- **Validation**:
  - `pytest tests/test_governor_gating.py -q` green.

## Sprint 3: Conductor/Scheduler Integration and Safety
**Goal**: Prove force-query orchestration actually executes heavy jobs and remains budget-safe.  
**Demo/Validation**:
- `run_once(force=True)` path leads to admitted heavy lease and non-deferred heavy execution.
- Runtime stats expose mode/admission/preemption diagnostics.

### Task 3.1: Verify Force Path Signal Propagation
- **Location**: `autocapture/runtime/conductor.py`, `tests/test_runtime_conductor.py`
- **Description**:
  - Confirm `force=True` always sets `query_intent=True`.
  - Add assertions that resulting governor mode is `USER_QUERY`.
- **Complexity**: 3/10
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - No ambiguity in signal translation from force to query mode.
- **Validation**:
  - Conductor unit tests around signal payload and mode result.

### Task 3.2: Scheduler Admission/Deferral Regression Coverage
- **Location**: `autocapture/runtime/scheduler.py`, `tests/test_runtime_budgets.py`, `tests/test_governor_gating.py`
- **Description**:
  - Ensure scheduler behavior with heavy jobs in `USER_QUERY`:
    - admitted when lease allowed,
    - deferred when budget exhausted,
    - non-heavy/light behavior unchanged.
- **Complexity**: 5/10
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Budget and concurrency controls still enforce ceilings.
- **Validation**:
  - Runtime budget tests and scheduler-focused assertions pass.
  - Mixed-workload deterministic test: alternating forced `USER_QUERY` heavy jobs with active non-query jobs still respects global heavy concurrency and fairness constraints.

### Task 3.3: Runtime Diagnostics for USER_QUERY Heavy Runs
- **Location**: `autocapture/runtime/scheduler.py`, `autocapture/runtime/conductor.py`, `docs/reports/runtime_user_query_heavy_after.json`
- **Description**:
  - Add/confirm structured stats fields for:
    - mode, heavy admission, deferred count, preempted count, reason.
  - Emit sample post-fix report.
- **Complexity**: 4/10
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Operators can distinguish “not admitted” vs “preempted” vs “completed”.
- **Validation**:
  - Deterministic snapshot tests and sample report generation.

## Sprint 4: End-to-End Stage2 Query Unblock Proof
**Goal**: Demonstrate that forced Stage2 runs now produce queryable evidence artifacts.  
**Demo/Validation**:
- Stage2 run produces derived artifacts from Stage1 data.
- Query path returns evidence-backed result using those artifacts.

### Task 4.1: Build Repro Harness for Sidecar+WSL Topology
- **Location**: `tools/wsl/verify_user_query_heavy_unblock.sh`, `docs/runbooks/user-query-heavy-unblock.md`
- **Description**:
  - Script checks:
    - data-dir consistency,
    - provider availability,
    - forced run completion with nonzero processed records.
- **Complexity**: 5/10
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Single script provides pass/fail + root-cause hints.
- **Validation**:
  - Run harness on synthetic + live-compatible environments.

### Task 4.2: Stage2 Evidence Production Gate
- **Location**: `tools/gate_stage2_user_query_unblock.py`, `tests/test_gate_stage2_user_query_unblock.py`
- **Description**:
  - Add gate to assert that forced mode produces at least one of:
    - `derived.text.*`, `derived.sst.*`, or state-layer query artifacts.
  - Gate is fail-open for missing runtime services but fail-closed for logical gating regressions.
- **Complexity**: 6/10
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Regression caught if USER_QUERY heavy path silently stops executing.
- **Validation**:
  - Gate test fixtures for pass/fail scenarios.

### Task 4.3: Golden/Answerability Validation for Unblocked Path
- **Location**: `tools/query_eval_suite.py`, `tests/test_query_eval_suite_exact.py`, `docs/reports/stage2_user_query_heavy_unblock_eval.json`
- **Description**:
  - Run small curated query set against newly produced Stage2 artifacts.
  - Verify answer contains citations or explicit indeterminate state.
- **Complexity**: 6/10
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Evidence-backed answers improve from pre-fix baseline.
- **Validation**:
  - Deterministic eval report committed.

## Sprint 5: Rollout, Recovery, and Drift Prevention
**Goal**: Make the fix durable and operationally safe.  
**Demo/Validation**:
- Rollout checklist and rollback script validated.
- Drift checks prevent accidental reintroduction.

### Task 5.1: Rollout Checklist and Feature Guard
- **Location**: `docs/runbooks/runtime-governor-rollout.md`, `config/default.json`
- **Description**:
  - Add rollout checklist for prod-like environments.
  - Optional guard flag for emergency disable of USER_QUERY heavy admission if needed.
- **Complexity**: 4/10
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - Operators can enable/disable behavior safely.
- **Validation**:
  - Config schema + default compatibility check.
  - Automated toggle verification confirms enabling/disabling guard flips lease/preemption behavior and telemetry as expected.

### Task 5.2: Recovery Simulation and Audit Trail
- **Location**: `tools/soak/`, `docs/reports/runtime_user_query_heavy_soak.json`
- **Description**:
  - Run bounded soak with intermittent activity transitions and forced queries.
  - Verify no crash-loop and audit entries remain append-only and coherent.
- **Complexity**: 5/10
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - No deadlock/defer-forever behavior under repeated force runs.
- **Validation**:
  - Soak report with preemption/admission trends.

### Task 5.3: Scope-Drift Cleanup (Optional but Recommended)
- **Location**: `docs/ARCHITECTURE.md`, legacy CLI entrypoints
- **Description**:
  - Add canonical-runtime declaration (`autocapture_nx/` path).
  - Add deprecation notice for legacy `autocapture_prime` entrypoints where appropriate.
- **Complexity**: 3/10
- **Dependencies**: Task 5.2
- **Acceptance Criteria**:
  - Reduced operator confusion about which orchestrator path is authoritative.
- **Validation**:
  - Docs review and CLI help output spot-check.

## Testing Strategy
- Unit:
  - `tests/test_governor_gating.py` for lease/preemption mode logic.
  - `tests/test_runtime_budgets.py` for budget interactions.
- Integration:
  - `tests/test_runtime_conductor.py` + scheduler flow tests for `force=True`.
  - Sidecar/WSL harness for production-like behavior.
- Regression:
  - Query/evidence eval subset to confirm Stage2 unblock improves answerability.
- Determinism:
  - Repeat core tests with fixed signals to avoid flaky mode transitions.

## Potential Risks & Gotchas
- Risk: Allowing heavy work in `USER_QUERY` may increase active-session load.
  - Mitigation: Keep existing budget windows, concurrency limits, and per-job caps unchanged.
- Risk: `query_intent` overuse could starve non-query background jobs.
  - Mitigation: preserve fair scheduling and add admission/defer telemetry.
- Risk: External/runtime-specific data-path mismatch (`AUTOCAPTURE_DATA_DIR`) masks true behavior.
  - Mitigation: add explicit preflight/harness checks for data-dir and provider availability.
- Risk: Existing contract-lock mismatch blocks local boot validation.
  - Mitigation: treat lock mismatch resolution as prerequisite and validate in canonical runtime environment.

## Rollback Plan
- Revert governor lease/preemption changes in `autocapture/runtime/governor.py`.
- Disable optional USER_QUERY-heavy feature flag (if introduced).
- Re-run baseline report (`runtime_user_query_heavy_baseline.json`) to confirm prior behavior restored.
- Keep test additions; mark expected behavior under rollback profile if needed.
