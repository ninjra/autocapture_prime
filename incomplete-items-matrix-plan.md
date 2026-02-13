# Plan: Full Repo Miss Matrix Closure

**Generated**: 2026-02-12  
**Estimated Complexity**: High

## Overview
Close every actionable miss from the exhaustive matrix in `docs/reports/implementation_matrix_remaining_2026-02-12.md`, prioritizing deterministic gates, production-grade model plugins, and traceable closure of authoritative blueprint/spec requirements.

## Prerequisites
- `artifacts/repo_miss_inventory/latest.json` is fresh and reproducible.
- `docs/reports/implementation_matrix_remaining_2026-02-12.md` is regenerated from the inventory.
- Local `.venv` works for tests and tooling.
- Local model runtime endpoints are available for production plugin paths.

## Sprint 1: Gate Integrity First
**Goal**: Remove `DO_NOT_SHIP` gate failures before broader backlog closure.  
**Demo/Validation**:
- `tools/run_mod021_low_resource.sh` passes.
- `tools/run_all_tests_report.json` reports `status=ok`.

### Task 1.1: Fix failing MOD-021 gate path
- **Location**: `tools/gate_pillars.py`, `tools/run_mod021_low_resource.sh`, `tests/test_retrieval_golden.py`
- **Description**: Resolve deterministic failure path causing `tools/gate_pillars.py` failure in low-resource gate runs.
- **Complexity**: 7
- **Dependencies**: None
- **Acceptance Criteria**:
  - Gate becomes green without relaxing quality standards.
  - Repeated runs are stable.
- **Validation**:
  - `tools/run_mod021_low_resource.sh`

### Task 1.2: Add deterministic regression checks around the failing threshold
- **Location**: `tests/test_retrieval_golden.py` (or new adjacent test file)
- **Description**: Add explicit checks for ordering/tie-break behavior that previously caused precision edge failures.
- **Complexity**: 5
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Test fails before fix and passes after fix.
  - No flaky ordering.
- **Validation**:
  - `PYTHONPATH=. .venv/bin/python -m pytest tests/test_retrieval_golden.py -q`

## Sprint 2: Replace Placeholder Model Paths
**Goal**: Eliminate placeholder logic in production plugin paths.  
**Demo/Validation**:
- OCR/object plugins execute real inference or deterministic fail-closed behavior.
- No TODO/placeholder implementation remains in active model plugins.

### Task 2.1: Implement real Nemotron OCR path
- **Location**: `plugins/builtin/ocr_nemotron_torch/plugin.py`
- **Description**: Replace placeholder return path with real model execution + normalized structured output + model provenance.
- **Complexity**: 8
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Plugin returns schema-valid OCR payloads under configured runtime.
  - Explicit deterministic fail-closed response when unavailable.
- **Validation**:
  - Add and run plugin unit/integration tests.

### Task 2.2: Implement real Nemotron object extraction path
- **Location**: `plugins/builtin/sst_nemotron_objects/plugin.py`
- **Description**: Replace placeholder fan-out stub with object extraction output integrated into SST docs.
- **Complexity**: 8
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Schema-valid outputs with deterministic ordering.
  - Works in end-to-end screenshot processing pipeline.
- **Validation**:
  - Add and run SST/object extraction tests.

### Task 2.3: Classify remaining placeholder markers as actionable vs benign literals
- **Location**: `autocapture_nx/ux/fixture.py`, `tools/run_fixture_pipeline.py`, `tools/run_fixture_stepwise.py`, `autocapture/ux/redaction.py`, `tests/test_ui_accessibility.py`
- **Description**: Distinguish true implementation placeholders from benign placeholder string usage and reduce scanner false positives via explicit allowlist policy.
- **Complexity**: 6
- **Dependencies**: Task 2.1, Task 2.2
- **Acceptance Criteria**:
  - Inventory no longer flags benign placeholder vocabulary as implementation debt.
  - True TODO paths remain visible and gated.
- **Validation**:
  - Re-run `tools/full_repo_miss_inventory.py` and compare diff.

## Sprint 3: Close Authoritative Requirement Backlog
**Goal**: Systematically close or explicitly defer authoritative docs backlog (`I001..I130`, `MOD-*`, `SRC-*`).  
**Demo/Validation**:
- Authoritative-doc miss counts trend toward zero or documented deferral states.
- Every deferred item has rationale and owner.

### Task 3.1: Build requirement-by-requirement closure ledger
- **Location**: `docs/reports/implementation_matrix_remaining_2026-02-12.md`, new `docs/reports/requirement_closure_ledger.md`
- **Description**: For each authoritative requirement ID in the exhaustive list, record status, evidence, owner, and closure/defer decision.
- **Complexity**: 7
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - No authoritative ID is unmapped.
  - Every ID has explicit evidence link(s) or defer rationale.
- **Validation**:
  - Cross-check `requirement_closure_ledger.md` against inventory ID set.

### Task 3.2: Reconcile feature tracker and blueprint checklists with executable truth
- **Location**: `docs/reports/feature_completeness_tracker.md`, `docs/blueprints/autocapture_nx_blueprint.md`, `docs/spec/autocapture_nx_blueprint_2026-01-24.md`
- **Description**: Update checklist states based on tests/gates/code evidence rather than historical intent.
- **Complexity**: 8
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Checklist state matches executable evidence.
  - No "complete" claim without test/gate backing.
- **Validation**:
  - Refresh inventory and verify reduced authoritative misses.

## Sprint 4: 4Pillars Plan Traceability and Implementation
**Goal**: Convert `docs/AutocapturePrime_4Pillars_Upgrade_Plan.md` from intent-only to traceable implementation status.  
**Demo/Validation**:
- A1..A10 and A-* tasks have concrete repo artifacts/tests or explicit defer decisions.
- Matrix no longer shows zero-coverage for all 4Pillars items.

### Task 4.1: Create 4Pillars implementation tracker
- **Location**: new `docs/reports/four_pillars_implementation_tracker.md`
- **Description**: Map each A-item and task to code/tests/docs evidence and current status.
- **Complexity**: 5
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Every A-item is mapped to evidence or explicit deferral.
  - Tracker references executable artifacts where available.
- **Validation**:
  - Run `tools/generate_full_remaining_matrix.py` and verify non-zero external refs where implemented.

### Task 4.2: Implement highest-impact A-task path
- **Location**: `autocapture_nx/indexing/`, `plugins/builtin/`, `tools/query_*`, `tests/`
- **Description**: Prioritize A-CORE-01, A-GROUND-01, A-RAG-01, and A-INDEX-01 with deterministic tests and plugin contribution metrics.
- **Complexity**: 9
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - End-to-end screenshot query path uses full plugin workflow with measurable contribution.
  - Golden query harness captures correctness by plugin sequence.
- **Validation**:
  - Run query evaluation suite with recorded expected answers and plugin-path metrics.

## Sprint 5: Inventory and Matrix Automation Hardening
**Goal**: Keep matrix generation trustworthy, repeatable, and non-recursive.  
**Demo/Validation**:
- One command regenerates inventory + matrix + plan-ready misses.
- Output excludes self-recursive artifacts and tracks scanner version.

### Task 5.1: Add inventory generation smoke tests
- **Location**: `tests/test_full_repo_miss_inventory.py` (new), `tests/test_generate_full_remaining_matrix.py` (new)
- **Description**: Validate scanner/matrix tooling behavior (ID extraction, recursion exclusion, stable output shape).
- **Complexity**: 6
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - Tests fail if recursion or schema regressions reappear.
  - Matrix generation is deterministic for fixed inputs.
- **Validation**:
  - `PYTHONPATH=. .venv/bin/python -m pytest tests/test_full_repo_miss_inventory.py tests/test_generate_full_remaining_matrix.py -q`

### Task 5.2: Add single-command refresh workflow
- **Location**: new `tools/run_full_repo_miss_refresh.sh`
- **Description**: Chain inventory + matrix generation + gate snapshot into one reproducible command.
- **Complexity**: 3
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - One command refreshes all miss artifacts without manual edits.
  - Command output includes paths to canonical reports.
- **Validation**:
  - Execute script and verify outputs exist and are updated.

## Testing Strategy
- Gate-first sequence at each sprint boundary.
- Deterministic regression tests for retrieval and plugin outputs.
- Inventory tooling unit tests to prevent false positives/recursion.
- Golden query suite with expected-answer verification and plugin-sequence metrics.

## Potential Risks & Gotchas
- Large historical report corpus inflates miss counts; classify "historical snapshot" files to prevent noise from obscuring actionable debt.
- Placeholder token scanning can over-count benign text usage; maintain explicit allowlist policy.
- 4Pillars item IDs `A1..A10` are short tokens and require strict matching rules to avoid accidental hits.
- Closing checklist items without executable proof recreates false-green risk.

## Rollback Plan
- Keep previous matrix and inventory artifacts in git history for diff-based rollback.
- Feature-flag new model plugins to deterministic no-op fallback if runtime instability appears.
- If matrix automation regresses, revert generator scripts and temporarily use the last known-good report artifacts.
