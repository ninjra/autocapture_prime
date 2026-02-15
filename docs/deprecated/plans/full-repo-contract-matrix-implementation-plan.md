# Plan: Full Repo Contract Matrix Implementation

**Generated**: 2026-02-13
**Estimated Complexity**: High

## Overview
Complete all currently detected repo-wide contract misses and convert them into deterministic, test-gated implementation. The current exhaustive scan (`1363` files) reports `13` misses, all sourced from two authoritative docs updated today: `docs/autocapture_prime_UNDER_HYPERVISOR.md` and `docs/codex_autocapture_prime_blueprint.md`.

Approach:
1. Resolve contract placeholders/open items in `docs/autocapture_prime_UNDER_HYPERVISOR.md`.
2. Implement missing contract-required artifacts from `docs/codex_autocapture_prime_blueprint.md`.
3. Add deterministic validators + gates so future scans fail closed when these contracts regress.
4. Re-run full-repo matrix generation and require zero actionable misses.

## Prerequisites
- Python venv available at `.venv`.
- Current matrix tooling operational:
  - `tools/full_repo_miss_inventory.py`
  - `tools/generate_full_remaining_matrix.py`
  - `tools/run_full_repo_miss_refresh.sh`
- Traceability tooling operational:
  - `tools/traceability/item_inventory.py`
  - `tools/traceability/generate_traceability.py`
  - `tools/traceability/validate_traceability.py`

## Scope Inputs (Research Snapshot)
- Exhaustive inventory output: `artifacts/repo_miss_inventory/latest.json`
- Remaining matrix: `docs/reports/implementation_matrix_remaining_2026-02-12.md`
- Today contract docs:
  - `docs/autocapture_prime_UNDER_HYPERVISOR.md`
  - `docs/codex_autocapture_prime_blueprint.md`

Detected misses:
- `doc_contract_placeholder` x3
- `doc_open_item` x3
- `doc_required_artifact_missing` x7

## Sprint 1: Close Contract Documentation Gaps
**Goal**: Make both today docs fully concrete and contract-complete.
**Demo/Validation**:
- `tools/run_full_repo_miss_refresh.sh` runs cleanly with zero misses from these two docs.
- No `<...>` placeholders remain in `docs/autocapture_prime_UNDER_HYPERVISOR.md`.

### Task 1.1: Replace `<AP_ENTRYPOINT>` with concrete runnable command
- **Location**: `docs/autocapture_prime_UNDER_HYPERVISOR.md`
- **Description**: Resolve all `<AP_ENTRYPOINT>` placeholders with a concrete CLI entrypoint and arguments aligned with current repo commands.
- **Complexity**: 3
- **Dependencies**: None
- **Acceptance Criteria**:
  - No unresolved placeholder tokens remain.
  - Command reflects real runtime path and supports run-id/data-root/output controls.
- **Validation**:
  - `rg -n '<[A-Z][A-Z0-9_-]*>' docs/autocapture_prime_UNDER_HYPERVISOR.md` returns no hits.

### Task 1.2: Resolve “Open items to fill in” section
- **Location**: `docs/autocapture_prime_UNDER_HYPERVISOR.md`
- **Description**: Fill all open items with concrete values or explicit linked references to implementing files.
- **Complexity**: 4
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Section has no unresolved items.
  - Each resolved item references a concrete file path or contract artifact.
  - Explicitly resolved:
    - `AP_ENTRYPOINT` command path
    - capture-device strategy (`exclusive` vs `lockfile`) with lock path contract
    - stats-harness output schema reference consumed downstream
- **Validation**:
  - `tools/full_repo_miss_inventory.py` reports `doc_open_item=0` for this source.

### Task 1.3: Create contract artifacts declared by codex blueprint
- **Location**:
  - `docs/_codex_repo_manifest.txt`
  - `docs/_codex_repo_review.md`
- **Description**:
  - Generate and store full tracked file manifest.
  - Write insertion-point and constraints review summary required by blueprint.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Both files exist and are non-empty.
  - Review doc references plugin model, safe mode, constraints, and insertion points.
- **Validation**:
  - File existence + minimum content checks in automated test.

### Task 1.4: Create schema artifacts declared by codex blueprint
- **Location**:
  - `docs/schemas/ui_graph.schema.json`
  - `docs/schemas/provenance.schema.json`
- **Description**: Add deterministic JSON schemas for UI graph and provenance object contracts.
- **Complexity**: 5
- **Dependencies**: Task 1.3
- **Acceptance Criteria**:
  - Both schema files exist and parse as valid JSON.
  - Schema versions and required fields are explicit.
- **Validation**:
  - JSON parse test + schema smoke validation test.

### Task 1.5: Create golden test corpus scaffolding
- **Location**:
  - `tests/golden/questions.yaml`
  - `tests/golden/expected.yaml`
- **Description**: Add initial golden query/expected structure required by codex blueprint.
- **Complexity**: 4
- **Dependencies**: Task 1.4
- **Acceptance Criteria**:
  - Files exist and load via YAML parser.
  - At least one baseline case is present.
- **Validation**:
  - New test validates file presence and YAML shape.

## Sprint 2: Implement Screen Structure Pipeline Contracts
**Goal**: Implement blueprint-required `screen.parse/index/answer` contracts as real plugins with deterministic outputs.
**Demo/Validation**:
- Plugins load in doctor output.
- End-to-end query returns evidence-referenced answers from structured UI graph path.

### Task 2.1: Add `screen.parse.v1` plugin + manifest
- **Location**:
  - `plugins/` new plugin package + `plugin.json`
  - related contracts in `contracts/`
- **Description**: Parse screenshot/layout into structured `ui_graph` with stable ordering and node ids.
- **Complexity**: 8
- **Dependencies**: Sprint 1 complete
- **Acceptance Criteria**:
  - Plugin capability is discoverable.
  - Output includes hierarchy, bbox, text nodes.
- **Validation**:
  - Unit tests for deterministic ordering + schema compliance.

### Task 2.1b: Codify evidence object contract + policy wiring
- **Location**:
  - `contracts/` schema files
  - plugin manifests/lockfiles and safe-mode policy configs
- **Description**: Implement the codex blueprint evidence object contract (`evidence_id`, `type`, `source`, optional `bbox`, `hash`) and wire safe-mode allowlist + plugin lock hash updates for new screen plugins.
- **Complexity**: 7
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Evidence object schema exists and is used by screen parse/index/answer outputs.
  - Doctor/safe-mode/lockfile flows recognize new plugin artifacts.
- **Validation**:
  - Contract tests for evidence object schema.
  - Lockfile/safe-mode tests fail when plugin hashes or allowlist entries are missing.

### Task 2.2: Add `screen.index.v1` plugin
- **Location**: `plugins/` + retrieval/index integration points
- **Description**: Chunk/index UI nodes and store embeddings with node references.
- **Complexity**: 7
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Indexed nodes retrievable by node id and evidence linkage.
- **Validation**:
  - Retrieval tests over fixture UI graphs.

### Task 2.3: Add `screen.answer.v1` plugin
- **Location**: `plugins/` + query orchestration
- **Description**: Answer from retrieved UI nodes with required evidence references per claim.
- **Complexity**: 8
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Factual claims include evidence ids/provenance.
  - Returns insufficient evidence when support is missing.
- **Validation**:
  - Golden tests enforcing evidence-bearing answers.

### Task 2.4: Integrate with promptops/query arbitration path
- **Location**: `autocapture_nx/kernel/query.py`, plugin preference config
- **Description**: Register screen-structure pipeline as first-class provider in answer workflow.
- **Complexity**: 7
- **Dependencies**: Tasks 2.1-2.3
- **Acceptance Criteria**:
  - Provider contribution visible in query trace.
  - Deterministic arbitration with explainable winner.
- **Validation**:
  - Query trace tests for provider attribution.

### Task 2.5: Add golden corpus runner integration for screen pipeline
- **Location**: `tools/` runner + test entrypoint wiring in existing suite
- **Description**: Execute `tests/golden/questions.yaml` + `tests/golden/expected.yaml` in automated test flow and fail when evidence references/schema checks are violated.
- **Complexity**: 6
- **Dependencies**: Tasks 2.1-2.4, Task 1.5
- **Acceptance Criteria**:
  - Golden runner is invoked from standard test/gate path.
  - Failures surface deterministic diff output.
- **Validation**:
  - CI/local run demonstrates pass/fail behavior on known-good and intentionally-bad fixture.

## Sprint 3: Hypervisor Contract Runtime Enforcement
**Goal**: Ensure runtime aligns with `UNDER_HYPERVISOR` contract and is testable.
**Demo/Validation**:
- Hypervisor contract flags/env are accepted and surfaced in run metadata.
- Offline and concurrency checks pass.

### Task 3.1: Wire run identity/output/data-root controls
- **Location**: `autocapture_nx/cli.py`, runtime config path handling
- **Description**: Ensure `--run-id`, `--out`, `--data-root` (and env equivalents) are supported and deterministic.
- **Complexity**: 6
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Flags/env produce isolated run dirs and stable manifests.
- **Validation**:
  - Integration tests for run isolation.

### Task 3.2: Enforce `--no-network`/`AP_NO_NETWORK`
- **Location**: plugin execution policy + network guards
- **Description**: Deny egress during offline mode with explicit fail-closed behavior.
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Outbound HTTP attempts are blocked and auditable.
- **Validation**:
  - Offline regression test with expected denial events.
  - Negative test: plugin outbound HTTP attempt is denied and recorded.

### Task 3.3: Add ready-file and structured run logging contract
- **Location**: CLI/runtime boot flow + run metadata output
- **Description**: Emit readiness marker and JSON logs for harness orchestration.
- **Complexity**: 5
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Ready file emitted once system is query-ready.
  - Log format stable and machine-parseable.
- **Validation**:
  - Integration test verifies ready file + log schema.

## Sprint 4: Deterministic Gates + Matrix Closure
**Goal**: Make matrix closure automatic and enforceable in CI/local gates.
**Demo/Validation**:
- Full refresh outputs zero actionable misses for these contracts.
- Gate fails if any contract regression reappears.

### Task 4.1: Add tests for contract-doc artifact obligations
- **Location**: `tests/` new test module(s)
- **Description**: Assert existence and basic validity of required files declared in today docs.
- **Complexity**: 5
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Test suite fails when required artifact is deleted/renamed.
- **Validation**:
  - Run targeted pytest file.

### Task 4.1b: Add safe-mode + plugin lock regression tests for new plugins
- **Location**: `tests/` safe-mode and plugin lock test modules
- **Description**: Add deterministic tests that enforce default-pack-only safe mode and hash-locked plugin manifests after introducing `screen.*` plugins.
- **Complexity**: 5
- **Dependencies**: Task 2.1b
- **Acceptance Criteria**:
  - Safe mode rejects unlisted/unlocked screen plugins.
  - Lockfile mismatch fails deterministically.
- **Validation**:
  - Targeted pytest coverage over safe-mode boot and lock verification paths.

### Task 4.2: Add gate command for full-repo miss inventory
- **Location**: `tools/` gate script + docs
- **Description**: CI/local command that runs inventory + remaining matrix generation and fails on actionable cluster rows.
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Non-zero exit on actionable misses.
  - Emits concise summary with cluster IDs.
- **Validation**:
  - Simulated regression run confirms gate failure.

### Task 4.3: Final matrix + traceability regeneration and lock-in
- **Location**:
  - `docs/reports/implementation_matrix_remaining_2026-02-12.md`
  - `artifacts/repo_miss_inventory/latest.json`
  - `tools/traceability/traceability.json`
- **Description**: Regenerate and commit deterministic outputs after all tasks land.
- **Complexity**: 4
- **Dependencies**: Sprints 1-3
- **Acceptance Criteria**:
  - Actionable clusters cleared or explicitly deferred with rationale.
- **Validation**:
  - Re-run generator suite and verify expected counts.

## Testing Strategy
- Unit:
  - schema parsing, plugin capability contracts, deterministic node ordering.
- Integration:
  - end-to-end screenshot -> ui_graph -> index -> answer with evidence.
  - hypervisor run-id/data-root/out/no-network/ready-file contract behavior.
- Regression/Gates:
  - full miss inventory refresh and actionable cluster check.
  - traceability generation + validation.

## Potential Risks & Gotchas
- Contract docs may evolve faster than scanner heuristics.
  - Mitigation: keep scanner rules explicit per authoritative docs and add tests for scanner output categories.
- New plugin capabilities may duplicate existing paths and confuse arbitration.
  - Mitigation: deterministic provider precedence + trace visibility tests.
- Offline/no-network mode can break model-dependent tests in WSL.
  - Mitigation: use fixtures/mocks for deterministic CI tests; keep live-model tests optional.
- Generated report churn can cause noisy diffs.
  - Mitigation: only gate actionable categories; keep archival/generated docs excluded from debt signals.

## Rollback Plan
- Revert scanner category additions in:
  - `tools/full_repo_miss_inventory.py`
  - `tools/generate_full_remaining_matrix.py`
- Re-run matrix generation to restore prior baseline behavior.
- Keep new contract artifacts behind additive-only changes (no deletion of existing flows).
