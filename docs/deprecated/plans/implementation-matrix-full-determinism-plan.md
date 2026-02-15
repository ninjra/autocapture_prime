# Plan: Fully Implement And Deterministically Verify Implementation Matrix Items

**Generated**: 2026-02-06
**Estimated Complexity**: Very High

## Overview
You want every item in the implementation matrix to be *fully implemented* with **fully deterministic tests and gates**. That means:
- Every acceptance-criteria bullet must map to at least one deterministic validator (a unit/integration test or a gate).
- “Implemented” cannot rely on manual audits, “seems to work”, or non-deterministic/hardware-only behavior.
- Docs must not be hand-wavy: traceability has to be regeneratable, and drift must be caught by gates.
- Verification must remain WSL-stable (resource bounded, no runaway subprocess fan-out).

This plan upgrades the repo from “we believe all items are implemented” to “we can prove it continuously”.

## Scope
- In scope items:
  - FX001, FX002 and all I001-I130 from `docs/reports/implementation_matrix.md`.
  - Source of truth for I-items acceptance criteria: `tools/blueprint_items.json`.
- In scope artifacts:
  - `docs/reports/implementation_matrix.md`
  - `docs/reports/blueprint-gap-YYYY-MM-DD.md`
  - `docs/spec/autocapture_nx_blueprint_2026-01-24.md` (`Coverage_Map`)
- Out of scope:
  - Anything not required to produce deterministic validators for the above.

## Definition Of Done
- For every FX/I item, every acceptance bullet is mapped to a deterministic validator (test/gate).
- New “traceability + acceptance coverage” gates are in `tools/run_all_tests.py` so regressions fail fast.
- Docs are generated and freshness-gated (no silent drift).
- `tools/run_mod021_low_resource.sh` passes on WSL.

## Determinism Policy (Proposed)
- A validator is “deterministic” if its pass/fail outcome is stable across repeated runs with fixed inputs.
- Hardware-dependent paths (GPU/NVENC/DX capture) must still have deterministic validators:
  - Either via pure unit tests of selection/routing logic, or
  - via deterministic stubs/fixtures (preferred), or
  - via explicit “capability not available” gates that enforce fail-closed/fallback behavior.
- “Skip” is allowed only if there is also a deterministic non-skip validator proving the invariant the item cares about (for example: “NVENC path used when available” becomes “NVENC selection logic chooses NVENC when config + capability available, otherwise fallback emits ledger event”).

## Prerequisites
- Low-resource test runner works: `tools/run_mod021_low_resource.sh`.
- Baseline traceability script works: `tools/refresh_blueprint_traceability.sh` (already exists).

## Sprint 0: Baseline Inventory And Risk Ranking
**Goal**: Identify where “acceptance bullets” are currently not explicitly validated, even if the code exists.
**Demo/Validation**:
- A generated report exists: `docs/reports/acceptance-coverage-YYYY-MM-DD.md` with initial coverage stats (expected to be incomplete at first).

### Task 0.1: Normalize Item Inventory
- **Location**: `tools/traceability/item_inventory.py` (new)
- **Description**:
  - Parse `docs/reports/implementation_matrix.md` to extract all item IDs (FX + I).
  - Parse `tools/blueprint_items.json` to extract I-item acceptance criteria bullets.
  - Define FX001/FX002 acceptance bullets explicitly (see Task 1.2) instead of leaving them implicit prose.
- **Complexity**: 5/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - Script outputs a deterministic list of item IDs and their bullet lists.
- **Validation**:
  - `python3 tools/traceability/item_inventory.py`

### Task 0.2: Rank Items By Determinism Risk
- **Location**: `docs/reports/determinism-risk-YYYY-MM-DD.md` (new)
- **Description**:
  - Generate a short risk ranking based on keywords in acceptance criteria and evidence:
    - Windows-only APIs
    - GPU/NVENC/DX capture
    - network / egress
    - time / scheduling
    - concurrency
  - This drives sprint ordering.
- **Complexity**: 3/10
- **Dependencies**: Task 0.1
- **Acceptance Criteria**:
  - Report exists with an ordered list and rationale per high-risk item.
- **Validation**:
  - Re-running the generator produces identical ordering.

## Sprint 1: Create A Single Traceability + Acceptance Source Of Truth
**Goal**: Create structured, versioned traceability where “implemented” is defined by acceptance bullet coverage.
**Demo/Validation**:
- A new file exists that is the single source of truth for evidence + validators.
- A gate fails if any acceptance bullet has no validator.

### Task 1.1: Define Traceability Manifest Schema
- **Location**: `tools/traceability/traceability.schema.json` (new)
- **Description**:
  - Define a schema for a manifest file that contains, per item:
    - `id` (FX001 / I001)
    - `title`
    - `acceptance_bullets[]` (verbatim)
    - `validators[]` (per bullet: references to tests/gates)
    - `code_paths[]`, `test_paths[]`, `gate_paths[]`
    - `platform_scope` (linux/wsl/windows) where relevant
- **Complexity**: 6/10
- **Dependencies**: Sprint 0
- **Acceptance Criteria**:
  - Schema is strict enough to prevent hand-wavy entries (no empty validators).
- **Validation**:
  - Unit test validates schema can parse the current manifest.

### Task 1.2: Create The Traceability Manifest (Initial)
- **Location**: `tools/traceability/traceability.json` (new)
- **Description**:
  - Populate the manifest from existing curated evidence:
    - Use `docs/reports/blueprint-gap-2026-02-02.md` as a starting point for I-items code/test paths.
    - Use `docs/reports/implementation_matrix.md` as a starting point for FX items.
  - For FX001/FX002:
    - Define explicit acceptance bullets (do not leave as prose-only “planned change summary”).
- **Complexity**: 8/10
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Manifest includes FX001/FX002 and I001-I130.
  - Every acceptance bullet has at least one validator reference (may be placeholder validators initially if missing; those become Sprint 3 tasks).
- **Validation**:
  - `python3 tools/traceability/validate_traceability.py`

### Task 1.3: Add Traceability Validators Registry
- **Location**: `tools/traceability/validators.py` (new)
- **Description**:
  - Define validator types:
    - `unittest_file`: path like `tests/test_x.py`
    - `unittest_test_id`: fully qualified test id
    - `gate_script`: `tools/gate_*.py`
    - `script`: one-line runnable script (must be deterministic)
  - Add validation that referenced tests/gates exist and are runnable in MOD-021.
- **Complexity**: 7/10
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Validator resolution is deterministic and cross-platform safe.
- **Validation**:
  - Unit tests for validator resolution.

### Task 1.4: New Gate: Acceptance Bullet Coverage
- **Location**: `tools/gate_acceptance_coverage.py` (new), `tools/run_all_tests.py`
- **Description**:
  - Gate that fails if:
    - any item is missing from the traceability manifest
    - any acceptance bullet has zero validators
    - any validator points to a missing path
  - Gate also prints a short actionable summary of missing items/bullets.
- **Complexity**: 6/10
- **Dependencies**: Tasks 1.2-1.3
- **Acceptance Criteria**:
  - Gate is deterministic and fast (sub-second ideally).
- **Validation**:
  - `python3 tools/gate_acceptance_coverage.py`

## Sprint 2: Generate And Gate Documentation (No Drift)
**Goal**: The matrix and gap reports are generated from traceability, and stale docs fail CI/tests.
**Demo/Validation**:
- Regenerated docs match committed docs.
- Docs freshness gate is wired into the test harness.

### Task 2.1: Generate `docs/reports/implementation_matrix.md`
- **Location**: `tools/generate_implementation_matrix.py` (new), `docs/reports/implementation_matrix.md`
- **Description**:
  - Generate the implementation matrix from `tools/traceability/traceability.json`.
  - Ensure the “Test / gate” column is always populated (no blanks).
- **Complexity**: 6/10
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Generator output is stable and sorted by ID.
- **Validation**:
  - Unit test compares generated output to committed output.

### Task 2.2: Generate `docs/reports/blueprint-gap-YYYY-MM-DD.md`
- **Location**: `tools/generate_blueprint_gap_report.py` (new), `docs/reports/blueprint-gap-*.md`
- **Description**:
  - Generate the blueprint gap report from traceability:
    - `implemented` iff all acceptance bullets have validators and all referenced paths exist.
    - `missing` otherwise.
- **Complexity**: 6/10
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Output matches existing “implemented” semantics once coverage is complete.
- **Validation**:
  - Unit test ensures all I-items appear and are ordered.

### Task 2.3: Update `Coverage_Map` From Generated Evidence
- **Location**: `tools/update_blueprint_coverage_map.py`, `docs/spec/autocapture_nx_blueprint_2026-01-24.md`
- **Description**:
  - Extend current updater so it pulls from the generated gap report (not manually curated).
- **Complexity**: 3/10
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - `tests/test_blueprint_spec_validation.py` stays green.
- **Validation**:
  - `python3 -m unittest tests/test_blueprint_spec_validation.py -q`

### Task 2.4: Gate: Docs Freshness
- **Location**: `tools/gate_docs_freshness.py` (new), `tools/run_all_tests.py`
- **Description**:
  - Gate that regenerates docs and fails if git diff is non-empty for the generated files.
- **Complexity**: 6/10
- **Dependencies**: Tasks 2.1-2.3
- **Acceptance Criteria**:
  - Manual edits cause deterministic failures; regeneration fixes it.
- **Validation**:
  - `python3 tools/gate_docs_freshness.py`

## Sprint 3: Close All Acceptance Bullet Gaps (Worklist -> Zero)
**Goal**: Every missing bullet gets deterministic validators, and the gate passes.
**Demo/Validation**:
- `tools/gate_acceptance_coverage.py` passes.
- `tools/run_mod021_low_resource.sh` passes.

### Task 3.1: Generate Determinism Worklist
- **Location**: `tools/traceability/generate_worklist.py` (new), `docs/reports/determinism-worklist-YYYY-MM-DD.md` (new)
- **Description**:
  - Emit a deterministic worklist of acceptance bullets that have placeholder/weak validators.
- **Complexity**: 4/10
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Worklist is stable across runs and sorted by (phase, item id).
- **Validation**:
  - Re-run generator; ensure identical output.

### Task 3.2: Implement Missing Validators (Batched)
- **Location**: Varies (tests under `tests/`, gates under `tools/`)
- **Description**:
  - For each worklist bullet:
    - Prefer a unit test that can run on WSL.
    - If OS/hardware-dependent, write deterministic stubs and unit test selection/fallback + ledger/journal evidence.
    - Update traceability manifest to reference the new validators.
- **Complexity**: 10/10
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Worklist shrinks to zero.
- **Validation**:
  - `tools/run_mod021_low_resource.sh`

### Task 3.3: WSL Resource Stability Gates (Meta)
- **Location**: `tools/gate_resource_stability.py` (new)
- **Description**:
  - Add a small deterministic gate that asserts:
    - No runaway plugin host processes after test run (best-effort `pgrep` count check, but deterministic by using test-local process tracking).
    - Optional: per-test-file peak RSS stays within config ceiling.
- **Complexity**: 7/10
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Gate is stable and doesn’t flake.
- **Validation**:
  - Run gate twice; outputs identical.

## Sprint 4: Single Golden “Matrix Complete” Command
**Goal**: Provide one WSL-safe command that proves “everything is implemented and deterministic”.
**Demo/Validation**:
- A script exists and runs end-to-end without high resource usage.

### Task 4.1: Add A Single Golden Script
- **Location**: `tools/run_matrix_golden_low_resource.sh` (new)
- **Description**:
  - Runs:
    - traceability validation + acceptance coverage gate
    - docs freshness gate
    - full low-resource suite
    - fixture pipeline + metadata-only query checks (FX001 domain)
- **Complexity**: 6/10
- **Dependencies**: Sprints 1-3
- **Acceptance Criteria**:
  - One command is sufficient to assert “complete”.
- **Validation**:
  - Run twice; results identical.

### Task 4.2: Update Workflow Documentation
- **Location**: `docs/fixture_pipeline_workflow.md` (or `docs/workflows/implementation_matrix_golden.md` new)
- **Description**:
  - Document the exact golden steps and expected artifacts (including evidence paths).
- **Complexity**: 3/10
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Doc matches script behavior exactly.
- **Validation**:
  - Follow doc from scratch.

## Testing Strategy
- Default suite: `tools/run_mod021_low_resource.sh`.
- Targeted runs: `python3 tools/run_unittest_sharded.py --start-at <file>`.
- Gates are required to be deterministic and fast (avoid network, avoid timeouts).

## Potential Risks & Gotchas
- Acceptance bullets in `tools/blueprint_items.json` may be high-level and ambiguous.
  - Mitigation: convert each bullet into an unambiguous invariant and write a deterministic validator for it; do not rely on interpretation.
- OS-specific functionality without a CI platform to run it.
  - Mitigation: validate “policy + selection + fallback” on WSL using stubs/mocks; treat real OS/hardware as performance-only.
- Docs generation gates can be brittle from timestamps.
  - Mitigation: forbid timestamps inside generated files; keep “Generated:” only in non-gated docs or inject date via filename only.

## Rollback Plan
- Introduce new gates behind an env flag first (warn-only), then flip to blocking once the manifest is populated.
- If generators prove too brittle, keep existing docs but keep the acceptance coverage gate (that’s the real correctness bar).

## Review (Process Constraint)
The `plan-harder` template suggests a “subagent review” step, but I don’t have a subagent tool in this environment. Recommended review:
1. Human reviewer reviews `tools/traceability/traceability.json` schema and gate logic.
2. Human reviewer reviews determinism policy compliance for OS/hardware-dependent bullets.

