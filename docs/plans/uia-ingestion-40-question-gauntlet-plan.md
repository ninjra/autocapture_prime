# Plan: UIA Ingestion 40-Question Synthetic Gauntlet

**Generated**: 2026-02-19  
**Estimated Complexity**: High

## Overview
Run a strict 40-question golden gauntlet against the new UIA ingestion path even while the live Hypervisor sidecar service is unavailable.  
Approach: generate synthetic sidecar-contract data (`uia_ref` + `evidence.uia.snapshot` + fallback files), inject it into single-image runs, execute advanced20 + generic20, and enforce strict matrix semantics:

- `matrix_evaluated = 40`
- `matrix_skipped = 0`
- `matrix_failed = 0`
- `ok = true`

## Skills By Section (and Why)
- Planning and decomposition: `plan-harder`  
  Why: enforce phased sprints, atomic tasks, and demoable checkpoints.
- Synthetic contract/test harness: `python-testing-patterns`  
  Why: deterministic fixture builders + integration testability.
- Gauntlet execution and scoring: `golden-answer-harness`  
  Why: canonical 40Q run/eval flow and strict correctness checks.
- Matrix/provenance integrity: `config-matrix-validator`  
  Why: enforce strict matrix and source-report consistency contracts.
- Determinism and drift control: `deterministic-tests-marshal`  
  Why: rerun hashing and flake detection before promotion.
- Evidence quality and strict matching: `evidence-trace-auditor`  
  Why: expected-vs-evidence correctness and citation path validation.
- Performance and budget gates: `perf-regression-gate`, `resource-budget-enforcer`  
  Why: protect throughput/latency and runtime resource policy.
- Command hygiene: `shell-lint-ps-wsl`  
  Why: shell correctness and repeatable operator commands.

## Prerequisites
- Local repo + venv usable at `/mnt/d/projects/autocapture_prime`.
- Existing runners available:
  - `tools/process_single_screenshot.py`
  - `tools/run_advanced10_queries.py`
  - `tools/eval_q40_matrix.py`
  - `tools/q40.sh` (or equivalent orchestration wrapper)
- Existing strict semantics in evaluator already present.
- Test image available (`artifacts/test_input_qh.png` or equivalent).

## Sprint 1: Synthetic UIA Contract Foundation
**Goal**: Build deterministic synthetic sidecar data that exactly matches the runtime contract expected by `builtin.processing.sst.uia_context`.  
**Skills**: `python-testing-patterns`, `config-matrix-validator`  
**Demo/Validation**:
- Generate a synthetic contract pack and validate schema/fields/hashes.
- Validate both metadata path and fallback-file path (`latest.snap.json` + optional `.sha256`).

### Task 1.1: Add synthetic UIA contract pack generator
- **Location**: `tools/synthetic_uia_contract_pack.py` (new)
- **Description**: Emit contract-faithful payloads:
  - frame `record.uia_ref` with `record_id`, `ts_utc`, `content_hash`
  - snapshot `record_type="evidence.uia.snapshot"` with required fields/arrays/node fields
  - fallback files under synthetic dataroot (`uia/latest.snap.json`, optional `latest.snap.sha256`)
- **Complexity**: 5
- **Dependencies**: none
- **Acceptance Criteria**:
  - Generated payload contains all required keys and type-correct structures.
  - Hash modes support both matching and mismatch negative tests.
- **Validation**:
  - New unit tests in `tests/test_synthetic_uia_contract_pack.py`.

### Task 1.2: Add synthetic contract validator
- **Location**: `tools/validate_synthetic_uia_contract.py` (new)
- **Description**: Validate generated pack against strict field and hash invariants.
- **Complexity**: 3
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Non-zero exit on missing required fields or invalid hash wiring.
- **Validation**:
  - Add tests in `tests/test_validate_synthetic_uia_contract.py`.

## Sprint 2: Single-Image Injection and Pipeline Wiring
**Goal**: Ensure single-image processing can run with synthetic UIA sidecar data and persist `obs.uia.*` docs before gauntlet execution.  
**Skills**: `python-testing-patterns`, `golden-answer-harness`  
**Demo/Validation**:
- One single-image run produces persisted `obs.uia.focus/context/operable` records.
- Deterministic doc IDs stable across reruns.

### Task 2.1: Add synthetic UIA injection option to single-image runner
- **Location**: `tools/process_single_screenshot.py`
- **Description**: Add CLI options to inject synthetic `uia_ref` and snapshot metadata into the run before idle processing.
- **Complexity**: 6
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Runner can execute with synthetic pack and no live sidecar.
  - Injection metadata and fallback path are captured in run report.
- **Validation**:
  - Extend tests in `tests/test_process_single_screenshot_profile_gate.py`
  - Add new tests in `tests/test_process_single_screenshot_uia_synthetic.py`.

### Task 2.2: Persist UIA extraction telemetry in report.json
- **Location**: `tools/process_single_screenshot.py`
- **Description**: Add run-report fields for:
  - `uia_injection.enabled`
  - `uia_injection.source` (`metadata`/`fallback`)
  - `uia_docs.count_by_kind`
  - `uia_docs.doc_ids`
- **Complexity**: 4
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Report has machine-readable UIA extraction summary for downstream gating.
- **Validation**:
  - New assertions in `tests/test_process_single_screenshot_uia_synthetic.py`.

## Sprint 3: Strict 40Q Synthetic Gauntlet Runner
**Goal**: Run advanced20 + generic20 on synthetic-UIA-augmented report and enforce strict matrix semantics with fail-closed behavior.  
**Skills**: `golden-answer-harness`, `config-matrix-validator`, `shell-lint-ps-wsl`  
**Demo/Validation**:
- One command produces:
  - `advanced20_strict_*.json`
  - `generic20_*.json`
  - `q40_matrix_strict_*.json`
- Strict gate fails on any `failed>0`, `skipped>0`, or `evaluated!=40`.

### Task 3.1: Add synthetic gauntlet orchestrator
- **Location**: `tools/run_q40_uia_synthetic.sh` (new)
- **Description**: Orchestrate:
  1. synthetic UIA contract generation
  2. single-image run with injection
  3. advanced20 strict run
  4. generic20 run
  5. strict matrix eval (`--strict --expected-total 40`)
- **Complexity**: 6
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Emits explicit failure reason JSON on any strict gate violation.
  - Updates `*_latest.json` only on success.
- **Validation**:
  - Add runner contract tests in `tests/test_q40_uia_synthetic_runner.py`.

### Task 3.2: Add synthetic-mode flags to advanced runner (if required)
- **Location**: `tools/run_advanced10_queries.py`
- **Description**: Ensure advanced runner can annotate synthetic source/provenance and preserve strict scoring behavior.
- **Complexity**: 3
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Rows preserve `source_report`, `source_report_sha256`, `source_report_run_id`.
- **Validation**:
  - Extend `tests/test_run_advanced10_expected_eval.py`.

## Sprint 4: Strict Correctness Loop (Expected vs Evidence)
**Goal**: Close remaining advanced mismatches by enforcing exact expected answers and evidence alignment from pipeline outputs.  
**Skills**: `evidence-trace-auditor`, `ccpm-debugging`, `golden-answer-harness`  
**Demo/Validation**:
- Mismatch report identifies each failing ID with root cause class.
- Re-run shows all advanced expected answers exact-match.

### Task 4.1: Add mismatch taxonomy report
- **Location**: `tools/report_q40_uia_mismatches.py` (new), `docs/reports/q40_uia_mismatch_latest.md`
- **Description**: Classify failures:
  - exact-answer mismatch
  - missing evidence
  - evidence-present-but-nonmatching
  - provider/path inconsistency
- **Complexity**: 4
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Every failed row has actionable category + evidence pointers.
- **Validation**:
  - New tests in `tests/test_report_q40_uia_mismatches.py`.

### Task 4.2: Tighten strict evaluator wiring for advanced-only exactness
- **Location**: `tools/run_advanced10_queries.py`, `tools/eval_q40_matrix.py`
- **Description**: Keep advanced expected-answer exactness fail-closed; keep generic contract checks strict but non-expected-answer-based.
- **Complexity**: 3
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - No partial-credit state can pass strict advanced checks.
- **Validation**:
  - Existing tests + targeted new fixtures.

## Sprint 5: 4-Pillar Hard Gates and Promotion
**Goal**: Promote only if Accuracy, Citeability, Performance, and Security gates all pass for synthetic UIA gauntlet runs.  
**Skills**: `deterministic-tests-marshal`, `perf-regression-gate`, `resource-budget-enforcer`, `evidence-trace-auditor`  
**Demo/Validation**:
- 3 consecutive strict runs produce stable success and no drift.
- Performance and resource thresholds are not regressed.
- Evidence chain quality remains acceptable.

### Task 5.1: Determinism gate (multi-run stability)
- **Location**: `tools/gate_q40_determinism.py` (new)
- **Description**: Execute strict gauntlet N times, compare key hashes/metrics and fail on drift.
- **Complexity**: 5
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - Stable `ok=true`, `40 evaluated`, `0 failed`, `0 skipped` across all reruns.
- **Validation**:
  - New tests in `tests/test_gate_q40_determinism.py`.

### Task 5.2: Throughput/resource gate for synthetic gauntlet
- **Location**: `tools/gate_q40_perf_budget.py` (new)
- **Description**: Check:
  - run completion time bounds
  - idle CPU/RAM policy compliance where applicable
  - no catastrophic latency regressions
- **Complexity**: 4
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Gate fails with explicit threshold deltas.
- **Validation**:
  - New tests in `tests/test_gate_q40_perf_budget.py`.

### Task 5.3: Final matrix/report update and promotion artifact
- **Location**: `docs/reports/implementation_matrix.md`, `docs/reports/q40_questions_expected_vs_pipeline_2026-02-19.md`
- **Description**: Update status only with validated strict outputs from synthetic UIA run.
- **Complexity**: 2
- **Dependencies**: Task 5.2
- **Acceptance Criteria**:
  - Documentation references exact artifact filenames and timestamps.
- **Validation**:
  - Manual review + CI docs checks.

## Testing Strategy
- Per sprint: run focused unit/integration tests for changed components.
- After each sprint: run gauntlet smoke (`advanced20 strict + generic20 + strict matrix`).
- Before promotion: run full synthetic gauntlet 3 times and compare outputs.
- Preserve strict semantics throughout (`40/40`, `0 skipped`, `0 failed`).

## Potential Risks & Gotchas
- Synthetic fixtures too “clean” can hide parser edge cases.
  - Mitigation: include noisy/partial/offscreen/invalid-rect variants in synthetic pack.
- Fallback hash logic can silently degrade if `.sha256` format drifts.
  - Mitigation: explicit parser tests for malformed hash file and mismatch paths.
- Strict latest pointers can be overwritten by non-strict runs.
  - Mitigation: synthetic runner writes `*_strict_*` first, updates `*_latest` only on strict success.
- Existing dirty worktree can contaminate artifact interpretation.
  - Mitigation: include source report sha/run_id provenance checks in every matrix eval.

## Rollback Plan
- Disable synthetic injection flags in runner and revert to baseline gauntlet scripts.
- Keep strict evaluator unchanged; only revert synthetic orchestrator and helper tools.
- Remove `*_latest` updates from failed synthetic runs; retain prior strict latest artifacts as ground truth.

