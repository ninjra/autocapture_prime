# Plan: Golden Soak Closure

**Generated**: 2026-02-17  
**Estimated Complexity**: High

## Overview
Drive `autocapture_prime` from current non-admissible state to golden soak readiness with strict fail-closed gates:
- `advanced20` must be `20/20` for 3 consecutive runs.
- release gate must be `ok=true` with no non-pass statuses.
- admission precheck/postcheck must both be `ok=true`.

Current blockers:
- `advanced20` currently `9/20` (`Q1..Q10`, `H8` failing).
- release gate currently fails (`gate_static` type errors).

## Prerequisites
- VLM endpoint healthy at `http://127.0.0.1:8000/v1` serving `internvl3_5_8b`.
- `.venv` available.
- Golden input image/report artifacts present.

## Skill Usage By Section

### Sprint 1 (Failure Baseline + Contract Guardrails)
- `plan-harder`: phased closure sequence and dependency control.
- `shell-lint-ps-wsl`: enforce cross-shell-safe command execution.
- `ccpm-debugging`: root-cause analysis of each failing gate/case.

### Sprint 2 (Advanced Extraction Fidelity)
- `ccpm-debugging`: trace extraction failures to candidate generation/merge/ranking.
- `python-testing-patterns`: add deterministic unit tests for candidate tiling/normalization.
- `deterministic-tests-marshal`: verify repeatability on same image/report.

### Sprint 3 (PromptOps + Reasoning Path Reliability)
- `golden-answer-harness`: verify question-class correctness without tactical shortcuts.
- `evidence-trace-auditor`: ensure answer claims are evidence-backed or indeterminate.
- `python-testing-patterns`: regression tests for display/field synthesis.

### Sprint 4 (Release/Admission Closure)
- `perf-regression-gate`: verify no major latency regression from richer extraction.
- `resource-budget-enforcer`: verify idle/active budget behavior remains compliant.
- `golden-answer-harness`: 3x strict-run closure with drift checks.

## Sprint 1: Gate/Runtime Stabilization
**Goal**: Clear release-gate structural blockers before quality iteration.  
**Demo/Validation**:
- `artifacts/release/release_gate_latest.json` reaches later gates without static-type failure.

### Task 1.1: Fix static type regressions in query hard-VLM path
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Resolve mypy-reported issues in action-grounding quality gate and scored-candidate fallback typing.
- **Complexity**: 2
- **Dependencies**: none
- **Acceptance Criteria**:
  - `gate_static` no longer fails on query.py type errors.
- **Validation**:
  - `tools/gate_static.py`

### Task 1.2: Re-run release gate and capture current first failing step
- **Location**: `artifacts/release/release_gate_latest.json`
- **Description**: Produce updated gate failure source for next sprint triage.
- **Complexity**: 1
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Fresh artifact timestamp.
- **Validation**:
  - Inspect `failed_step` and `steps[].issues`.

## Sprint 2: Advanced Q-Series Extraction Closure
**Goal**: Raise Q1..Q10 from partial to strict-pass using generic extraction improvements.
**Demo/Validation**:
- Q-series pass count increases materially in strict eval.

### Task 2.1: Upgrade grid candidate decomposition to true N-section support
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Replace fixed 4x2 splitter with dynamic section layout (supports 8/12/etc) to improve coverage on 7680x2160.
- **Complexity**: 4
- **Dependencies**: none
- **Acceptance Criteria**:
  - `AUTOCAPTURE_HARD_VLM_GRID_SECTIONS=12` actually yields 12 deterministic boxes.
- **Validation**:
  - new unit test for grid count/ordering.

### Task 2.2: Reduce context-overflow risk for `adv_browser` and enforce smaller multimodal payloads
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Tighten topic prompt/hint budgets and candidate max-side for browser topic.
- **Complexity**: 4
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - No `decoder prompt longer than max model length` in `adv_browser` hard-VLM debug.
- **Validation**:
  - strict advanced run includes successful `adv_browser` structured fields.

### Task 2.3: Expand topic ROI coverage for right-pane/VDI-heavy questions
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Add deterministic ROI slices for window inventory/browser/focus/incident/activity/details/calendar/unread paths.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Candidates include both left/center/right contextual windows and VDI pane slices.
- **Validation**:
  - inspect `_debug_candidates` coverage and improved Q-series pass rate.

### Task 2.4: Remove premature early-exit on `hard_unread_today`
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Evaluate full candidate set and choose best score for unread-count topic.
- **Complexity**: 3
- **Dependencies**: Task 2.3
- **Acceptance Criteria**:
  - `H8` uses best candidate across slices, not first acceptable candidate.
- **Validation**:
  - H8 expected-answer check in advanced20.

## Sprint 3: Display/Answer Normalization Reliability
**Goal**: Ensure answer payloads carry required evidence tokens and structured fields for strict checks.
**Demo/Validation**:
- Missing-token failures on Q-series are eliminated without question-id literal injection.

### Task 3.1: Strengthen adv display normalization and support-snippet integration
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Improve summary/bullet synthesis from structured fields + topic-relevant snippets.
- **Complexity**: 5
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Q-series `expected_contains_all` tokens found in result haystack through evidence-backed text.
- **Validation**:
  - strict advanced20 run.

### Task 3.2: Keep PromptOps mandatory and traceable in advanced path
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture/promptops/*`
- **Description**: Ensure advanced path retains promptops usage and model-interaction traces.
- **Complexity**: 3
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - all Q rows satisfy pipeline-enforcement checks.
- **Validation**:
  - strict advanced20 `expected_eval.checks`.

## Sprint 4: Golden Admission and Soak Readiness
**Goal**: Meet and verify all soak admission gates.
**Demo/Validation**:
- release gate pass.
- advanced20 strict pass x3.
- admission precheck pass.

### Task 4.1: Run strict advanced20 until 3 consecutive `20/20`
- **Location**: `artifacts/advanced10/`
- **Description**: Execute strict runs and verify no drift in required checks.
- **Complexity**: 4
- **Dependencies**: Sprint 2 + Sprint 3
- **Acceptance Criteria**:
  - three most recent runs are `evaluated_passed=20`, `evaluated_failed=0`.
- **Validation**:
  - run artifacts + deterministic signature checks.

### Task 4.2: Clear release gate and admission precheck
- **Location**: `artifacts/release/release_gate_latest.json`, `artifacts/soak/golden_qh/admission_precheck_latest.json`
- **Description**: Resolve remaining gate failures and confirm soak admission.
- **Complexity**: 4
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - both artifacts report `ok=true`.
- **Validation**:
  - runbooks under `docs/runbooks/release_gate_ops.md`.

## Testing Strategy
- Unit tests for grid decomposition, hard-VLM topic normalization, and candidate selection.
- Deterministic strict `advanced20` eval loops.
- Release gate + admission precheck artifacts as final acceptance.

## Potential Risks & Gotchas
- VLM instability or model restarts can produce transient extraction regressions.
  - Mitigation: bounded retries, deterministic config, multi-run closure.
- Over-aggressive hint text can pollute VLM outputs.
  - Mitigation: topic-specific hint caps and prompt budgeting.
- Context overflow on multimodal requests for ultra-wide captures.
  - Mitigation: dynamic tiling and smaller candidate max-side.

## Rollback Plan
1. Revert query-path changes in `autocapture_nx/kernel/query.py`.
2. Restore previous candidate-generation limits and prompt budgets.
3. Re-run strict advanced20 and release gate to confirm baseline behavior.
