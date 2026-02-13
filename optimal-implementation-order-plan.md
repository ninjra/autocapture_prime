# Plan: Optimal Implementation Order (Overwrite-Safe)

**Generated**: 2026-02-12  
**Estimated Complexity**: High

## Overview
Implement remaining work in an overwrite-safe sequence that prevents rework and conflicting changes. The core strategy is:
1) establish an authority map (what is executable source-of-truth vs generated/historical),
2) fix deterministic gates first,
3) implement foundational architecture before advanced VLM/RAG features,
4) close checklist/doc items only after executable evidence exists.

This plan is designed to avoid implementing items that will be overwritten by generators, superseded by architectural choices, or invalidated by later foundational changes.

## Prerequisites
- Canonical miss inputs are fresh:
  - `artifacts/repo_miss_inventory/latest.json`
  - `docs/reports/full_repo_miss_inventory_2026-02-12.md`
  - `docs/reports/implementation_matrix_remaining_2026-02-12.md`
- Full test and gate tooling runs locally:
  - `tools/run_mod021_low_resource.sh`
  - `tools/gate_pillars.py`
- Plugin lock/config lifecycle is stable:
  - `config/default.json`
  - `config/plugin_locks.json`

## Decision Gates (resolve overlap before coding)
- **DG-01 Storage Encryption Path**:
  - Conflict: `I026` (default SQLCipher) vs operational pressure to remove SQLCipher blockers.
  - Resolution rule: implement storage backend abstraction first; allow SQLCipher-capable and SQLite-fallback modes behind one contract; no feature may bind directly to one backend.
- **DG-02 VLM Pipeline Contract**:
  - Conflict: tactical OCR-only wins vs full VLM+reasoning path.
  - Resolution rule: answer acceptance for golden cases requires source-class policy and provenance checks, not provider-specific hacks.
- **DG-03 Generated Docs vs Executable Closure**:
  - Conflict: easy checklist/report edits vs actual implementation.
  - Resolution rule: generated/historical docs cannot close requirements; only executable evidence can.
- **DG-04 Performance vs Correctness Sequencing**:
  - Conflict: early perf tuning can overwrite retrieval/IR contracts.
  - Resolution rule: no A-PERF-01 work before A-CORE/A-GROUND/A-INDEX/A-RAG contracts and tests are green.

## Scope Boundaries (to prevent overwrite/rework)
- **Implement now (authoritative)**:
  - `docs/blueprints/autocapture_nx_blueprint.md` (`I001..I130`)
  - `docs/spec/autocapture_nx_blueprint_2026-01-24.md`
  - `docs/spec/feature_completeness_spec.md`
  - code/plugins/tests/tools that back these requirements.
- **Do not directly hand-edit for closure claims (generated/historical)**:
  - `docs/reports/*gap*.md`
  - `docs/reports/*grep*.txt`
  - old historical report snapshots unless regenerating via tool.
- **Conditional implement**:
  - `docs/AutocapturePrime_4Pillars_Upgrade_Plan.md` tasks (A1..A10, A-*) only when mapped to concrete kernel/plugin contracts and tests.

## Sprint 1: Authority Map and Supersedence Gates
**Goal**: Freeze implementation authority so teams do not implement stale or soon-to-be-overwritten work.
**Demo/Validation**:
- A checked-in authority matrix exists and is referenced by generators.
- Generated-report-only misses are tagged as non-executable debt.

### Task 1.1: Create implementation authority map
- **Location**: `docs/reports/implementation_authority_map.md`
- **Description**: Define file classes: authoritative spec, executable code, generated reports, historical artifacts.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Every high-volume miss source in the matrix is classified.
  - Explicit "do-not-implement-directly" list exists.
- **Validation**:
  - Manual review against `docs/reports/implementation_matrix_remaining_2026-02-12.md`.

### Task 1.2: Encode supersedence rules in tooling
- **Location**: `tools/full_repo_miss_inventory.py`, `tools/generate_full_remaining_matrix.py`
- **Description**: Add formal filters/labels for generated and historical sources, preserving visibility without mixing them with executable debt.
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Matrix renders separate sections for executable vs generated debt.
  - No self-referential inventory recursion.
- **Validation**:
  - Re-run `tools/run_full_repo_miss_refresh.sh` and compare deltas.

### Task 1.3: Add “no direct closure without executable evidence” rule
- **Location**: `tools/traceability/validate_traceability.py`, `tools/gate_acceptance_coverage.py`
- **Description**: Reject checklist closure unless backed by test/gate/plugin evidence.
- **Complexity**: 7
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Validation fails when docs are marked complete without executable proof.
- **Validation**:
  - Negative/positive traceability tests.

## Sprint 2: Deterministic Gates Before Feature Expansion
**Goal**: Restore and lock deterministic gate health so later work does not stack on unstable baseline.
**Demo/Validation**:
- `tools/run_mod021_low_resource.sh` is green repeatedly.

### Task 2.1: Fix failing retrieval/pillars gate path
- **Location**: `tests/test_retrieval_golden.py`, `autocapture_nx/kernel/query.py`, retrieval/rerank modules used by this test
- **Description**: Resolve gate-pillar failure root cause without threshold gaming.
- **Complexity**: 8
- **Dependencies**: Sprint 1 complete
- **Acceptance Criteria**:
  - Gate passes repeatedly (no flaky ties/order drift).
- **Validation**:
  - Run low-resource gate 5x and compare outputs.

### Task 2.2: Add deterministic tie-break and ordering regression tests
- **Location**: `tests/test_retrieval_golden.py` (or adjacent deterministic test file)
- **Description**: Add explicit ordering/tie tests that prevent precision edge regressions.
- **Complexity**: 5
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Pre-fix fails, post-fix passes.
- **Validation**:
  - Targeted pytest runs under low-resource config.

## Sprint 3: Foundation Plugins (Replace Placeholders, Keep Contracts Stable)
**Goal**: Replace placeholder core plugin paths with real deterministic implementations before advanced orchestration.
**Demo/Validation**:
- No production placeholder TODO paths in OCR/object extraction plugins.

### Task 3.1: Implement production Nemotron OCR path
- **Location**: `plugins/builtin/ocr_nemotron_torch/plugin.py`
- **Description**: Replace placeholder output with model-backed inference + strict fail-closed fallback + provenance metadata.
- **Complexity**: 8
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Schema-valid outputs, deterministic ordering, explicit error states.
- **Validation**:
  - Plugin unit/integration tests.

### Task 3.2: Implement production Nemotron object extraction path
- **Location**: `plugins/builtin/sst_nemotron_objects/plugin.py`, `autocapture_nx/processing/sst/stage_plugins.py`
- **Description**: Replace object placeholder fan-out with real structured detections integrated into SST pipeline.
- **Complexity**: 8
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Structured outputs flow into downstream retrieval/indexing records.
- **Validation**:
  - SST integration tests with golden fixtures.

### Task 3.3: Normalize placeholder scanner allowlist to avoid false debt
- **Location**: `tools/full_repo_miss_inventory.py`
- **Description**: Distinguish benign placeholder literals (template/test strings) from implementation placeholders.
- **Complexity**: 5
- **Dependencies**: Task 3.1, Task 3.2
- **Acceptance Criteria**:
  - Inventory code-placeholder counts reflect true implementation debt.
- **Validation**:
  - Snapshot comparison of inventory categories.

## Sprint 4: 4Pillars Core Path (A-CORE/A-GROUND/A-RAG/A-INDEX/A-PERF)
**Goal**: Implement 4Pillars tasks in the correct dependency order to avoid overwrite.
**Demo/Validation**:
- End-to-end screenshot pipeline produces stable IR, grounded candidates, retrieval, and evaluated answers.

### Task 4.1: Implement A-CORE-01 UI-IR contract first
- **Location**: new/updated under `autocapture_nx/processing/` and schema docs in `docs/spec/`
- **Description**: Define canonical `ui_ir.json` and produce it from screenshot pipeline with provenance hashes.
- **Complexity**: 8
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - IR schema deterministic and diff-stable on unchanged image.
- **Validation**:
  - IR schema + determinism tests.

### Task 4.2: Implement A-GROUND-01 on top of IR (not before)
- **Location**: grounding plugin(s) under `plugins/builtin/`, SST stage wiring in `autocapture_nx/processing/sst/`
- **Description**: Produce candidate regions + selected region + verifier score from IR objects.
- **Complexity**: 7
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Grounding output references immutable IR/evidence IDs.
- **Validation**:
  - Golden grounding fixture tests.

### Task 4.3: Implement A-INDEX-01 retrieval abstraction before A-RAG-01
- **Location**: `autocapture_nx/indexing/`, retrieval interfaces and adapters
- **Description**: Freeze retrieval interface (`add`, `search`) with dense + late-interaction adapters.
- **Complexity**: 7
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Callers do not change when backend switches.
- **Validation**:
  - Backend parity tests.

### Task 4.4: Implement A-RAG-01 evaluation harness against abstracted retrieval
- **Location**: `tools/query_eval_suite.py`, `tools/query_effectiveness_report.py`, `docs/query_eval_cases_advanced10.json`
- **Description**: Add deterministic multimodal retrieval/correctness scoring with failure thresholds.
- **Complexity**: 8
- **Dependencies**: Task 4.2, Task 4.3
- **Acceptance Criteria**:
  - Failures are explicit for retrieval vs answer correctness.
- **Validation**:
  - Evaluation suite regression in CI.

### Task 4.5: Implement A-PERF-01 scheduling/budget enforcement last
- **Location**: scheduler/governor modules, relevant config and tests
- **Description**: Introduce bounded batch scheduling only after pipeline contracts are stable.
- **Complexity**: 6
- **Dependencies**: Task 4.1–4.4
- **Acceptance Criteria**:
  - Budgets enforced with deterministic backpressure and preemption.
- **Validation**:
  - Synthetic load tests with fixed thresholds.

## Sprint 5: Blueprint Closure Waves (I001..I130) With Anti-Overwrite Strategy
**Goal**: Close the 130-item blueprint systematically without conflicting implementations.
**Demo/Validation**:
- Closure ledger maps each `Ixxx` to code/test/gate evidence or explicit defer.

### Task 5.1: Build closure ledger by phase, not by file
- **Location**: `docs/reports/requirement_closure_ledger.md`
- **Description**: Track each `Ixxx` status with evidence and “superseded by” links where applicable.
- **Complexity**: 7
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - No `Ixxx` remains unmapped.
- **Validation**:
  - Automated cross-check against inventory ID list.

### Task 5.2: Execute closure waves in strict phase order
- **Location**: implementation modules per phase from `docs/blueprints/autocapture_nx_blueprint.md`
- **Description**: Implement by phase sequence (0→1→2→3→4→5→6→7→8), blocking downstream waves on upstream exit criteria.
- **Complexity**: 9
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Later-phase items are not implemented if prerequisite phase gates fail.
- **Validation**:
  - Gate suite at each wave boundary.

## Sprint 6: Final Reconciliation and Matrix Regeneration
**Goal**: Ensure final matrix reflects executable truth and no stale closure claims.
**Demo/Validation**:
- Full refresh artifacts generated from one command and internally consistent.

### Task 6.1: One-command matrix refresh and publish
- **Location**: `tools/run_full_repo_miss_refresh.sh`
- **Description**: Regenerate inventory and matrix; publish with updated counts and clusters.
- **Complexity**: 3
- **Dependencies**: Sprints 1–5
- **Acceptance Criteria**:
  - Refresh output stable and reproducible.
- **Validation**:
  - Re-run twice; compare summaries.

### Task 6.2: Freeze ship criteria
- **Location**: `docs/reports/implementation_matrix_remaining_2026-02-12.md`, `docs/reports/feature_completeness_tracker.md`
- **Description**: Define “ship/no-ship” criteria tied to executable gates, not narrative docs.
- **Complexity**: 4
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Any gate regression marks release as `DO_NOT_SHIP`.
- **Validation**:
  - Dry-run release checklist.

## Testing Strategy
- Determinism-first: all critical gates run repeatedly (minimum 5 repeats for flaky-risk suites).
- Layered validation:
  - unit (plugin contracts),
  - integration (SST + retrieval),
  - end-to-end (query eval/golden cases),
  - governance (traceability + matrix refresh).
- Every closure claim in docs must reference a passing executable validator.

## Overwrite/Supersedence Rules (Key)
- Do not hand-fix generated report snapshots to “close” requirements.
- Do not implement A-GROUND/A-RAG before A-CORE contract is stable.
- Do not tune performance paths before correctness/determinism gates are green.
- Do not close checklist items until corresponding tests/gates exist and pass.

## Potential Risks & Gotchas
- Historical report noise can dominate counts and hide executable debt.
- Short ID tokens (`A1`, `A2`) can create false references if matching is weak.
- Placeholder scan may flag benign strings unless allowlisted.
- Implementing late-phase features early can force rewrite when core contracts change.

## Rollback Plan
- Keep generator/tooling and matrix updates in isolated commits for easy revert.
- Feature-flag new model paths; fallback to deterministic no-op on instability.
- If closure wave introduces regressions, roll back only that wave and rerun matrix refresh before continuing.
