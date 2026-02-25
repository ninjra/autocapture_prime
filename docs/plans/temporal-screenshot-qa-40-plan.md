# Plan: Temporal Screenshot QA 40 Integration

**Generated**: 2026-02-24  
**Estimated Complexity**: High

## Overview
Integrate `docs/temporal_screenshot_qa_40.md` as a first-class strict evaluation suite against the normalized corpus (no raw fallback), then gate promotion on deterministic correctness and evidence quality.

Target release state:
- New temporal suite is runnable end-to-end from CLI and CI.
- Strict semantics enforced: `evaluated=40`, `skipped=0`, `failed=0`.
- Every `OK` answer includes contract-compliant evidence with citations/joins.
- Failures are deterministic (`NOT_FOUND` or `NEEDS_CLARIFICATION`) with no speculation.

## Skills by Section (and Why)
- Sprint design and sequencing: `plan-harder`
  Why: phased, demoable increments with explicit strict gate exits.
- Case and harness integration: `golden-answer-harness`
  Why: existing query case runners and strict gate wiring already live here.
- Evidence contract enforcement: `evidence-trace-auditor`
  Why: temporal suite requires frame/HID/UIA linkage proof, not just answer text.
- Matrix and strict counters: `config-matrix-validator`
  Why: enforce `40/40` strict semantics and fail closed on any skip/fail.
- Determinism: `deterministic-tests-marshal`
  Why: repeated runs must keep IDs/order/status stable.
- Test implementation: `python-testing-patterns`
  Why: deterministic unit + integration tests for parser, planner, and evaluator.
- Throughput/resource safety: `perf-regression-gate`, `resource-budget-enforcer`
  Why: keep query latency and idle budgets within 4-pillar constraints.
- Command correctness: `shell-lint-ps-wsl`
  Why: operational command reliability for repeatable runs.

## Prerequisites
- Stable normalized stores available (`metadata.db` + vector/derived docs).
- Query runtime available on localhost (popup path can be validated separately).
- Existing runners remain authoritative:
  - `tools/run_advanced10_queries.py`
  - `tools/eval_q40_matrix.py`
  - `tools/run_synthetic_gauntlet.py`

## Sprint 1: Temporal QA40 Contract Scaffolding
**Goal**: Convert the markdown archetype spec into a strict machine-readable case pack + answer schema contract.
**Skills**: `plan-harder`, `python-testing-patterns`, `config-matrix-validator`  
**Demo/Validation**:
- New temporal case file exists with exactly 40 unique IDs (`TQ01..TQ40` or mapped IDs).
- New schema validates required answer JSON block fields.

### Task 1.1: Add case pack derived from archetypes
- **Location**: `docs/query_eval_cases_temporal_screenshot_qa_40.json` (new)
- **Description**: Materialize 40 case prompts with metadata tags:
  - modality requirements (`text`, `uia`, `hid`, `vector`)
  - required evidence minima
  - failure policy expectations
- **Complexity**: 5
- **Dependencies**: none
- **Acceptance Criteria**:
  - 40 unique case IDs.
  - Each case declares expected contract paths and strict mode behavior.
- **Validation**:
  - `tests/test_query_eval_cases_temporal_screenshot_qa_40_contract.py` (new).

### Task 1.2: Add answer JSON schema for temporal suite
- **Location**: `docs/schemas/temporal_screenshot_qa_40_answer.schema.json` (new)
- **Description**: Encode required fields from doc contract (`status`, `question_id`, `time_window`, `answer`, `evidence`, joins).
- **Complexity**: 4
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Schema rejects missing/invalid evidence blocks.
  - Supports `OK|NOT_FOUND|NEEDS_CLARIFICATION`.
- **Validation**:
  - `tests/test_temporal_qa40_answer_schema.py` (new).

## Sprint 2: Query Path Mapping for Temporal Questions
**Goal**: Ensure the runtime query pipeline can resolve all 40 archetypes using normalized data only.
**Skills**: `golden-answer-harness`, `evidence-trace-auditor`, `python-testing-patterns`  
**Demo/Validation**:
- Query planner routes temporal prompts through deterministic retrieval stages.
- No raw media access path is used.

### Task 2.1: Add temporal intent classifier + route map
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/ux/facade.py`
- **Description**: Add deterministic mapping for temporal archetypes (windowing, focus, HID cadence, vector similarity, state-return).
- **Complexity**: 7
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Each archetype category routes to known normalized sources.
  - Unknown/unsupported routes return deterministic structured errors quickly.
- **Validation**:
  - `tests/test_query_temporal_route_map.py` (new).

### Task 2.2: Retrieval/extraction adapters for required evidence
- **Location**: `plugins/builtin/retrieval_basic/plugin.py`, `plugins/builtin/storage_sqlcipher/plugin.py`
- **Description**: Guarantee bounded retrieval APIs can return:
  - frame ids + screenshot_time
  - UIA node refs (node_id/role/name/value)
  - HID event refs
  - vector doc IDs
- **Complexity**: 8
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Bounded latency path (no unbounded scans).
  - Evidence handles are returned in one consistent shape.
- **Validation**:
  - Extend `tests/test_retrieval_basic_plugin.py`
  - Extend `tests/test_storage_sqlcipher_latest_projection.py`.

## Sprint 3: Strict Answer Contract Rendering
**Goal**: Enforce the required answer format (short markdown + exactly one JSON block) for temporal QA.
**Skills**: `evidence-trace-auditor`, `python-testing-patterns`, `golden-answer-harness`  
**Demo/Validation**:
- Temporal answers always produce contract shape or deterministic failure shape.
- No top-k candidate output.

### Task 3.1: Add response formatter contract mode
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Add formatter mode for temporal suite:
  - markdown summary (1-6 lines)
  - single embedded JSON code block only
  - status discipline (`OK|NOT_FOUND|NEEDS_CLARIFICATION`)
- **Complexity**: 6
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Exactly one JSON block per response in suite mode.
  - `OK` responses include required evidence minima.
- **Validation**:
  - `tests/test_query_temporal_response_contract.py` (new).

### Task 3.2: Add evidence completeness guard
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/ux/facade.py`
- **Description**: If required evidence for `OK` is incomplete, downgrade deterministically to `NOT_FOUND`/`NEEDS_CLARIFICATION`.
- **Complexity**: 5
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - No unsupported `OK` survives contract validation.
- **Validation**:
  - `tests/test_query_temporal_evidence_guard.py` (new).

## Sprint 4: Harness + Strict Matrix Integration
**Goal**: Integrate temporal suite into existing gauntlet runners and strict matrix outputs.
**Skills**: `golden-answer-harness`, `config-matrix-validator`, `deterministic-tests-marshal`  
**Demo/Validation**:
- One command runs temporal40 and emits strict matrix artifact with enforced counters.

### Task 4.1: Runner support for temporal case file
- **Location**: `tools/run_advanced10_queries.py`, `tools/run_synthetic_gauntlet.py`
- **Description**: Add temporal case-file path support and output labels without breaking current advanced/generic runs.
- **Complexity**: 4
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Temporal run produces deterministic per-case results.
- **Validation**:
  - `tests/test_run_temporal_qa40_queries.py` (new).

### Task 4.2: Strict matrix evaluator support for temporal40 profile
- **Location**: `tools/eval_q40_matrix.py`
- **Description**: Add profile metadata + strict checks for temporal suite:
  - evaluated must equal 40
  - skipped must equal 0
  - failed must equal 0
- **Complexity**: 4
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Non-compliant temporal run fails gate with deterministic reason.
- **Validation**:
  - Extend `tests/test_eval_q40_matrix.py`.

## Sprint 5: 4-Pillar Gates + Promotion Evidence
**Goal**: Prove correctness, citeability, performance, and stability before promotion.
**Skills**: `evidence-trace-auditor`, `deterministic-tests-marshal`, `perf-regression-gate`, `resource-budget-enforcer`  
**Demo/Validation**:
- Temporal strict run succeeds repeatedly.
- Latency/resource budgets are within thresholds.

### Task 5.1: Determinism replay gate
- **Location**: `tools/gate_temporal_qa40_determinism.py` (new)
- **Description**: Run temporal suite `N=5` (default), compare:
  - status vectors
  - key answer hashes
  - evidence id sets
- **Complexity**: 5
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - Zero drift across reruns.
- **Validation**:
  - `tests/test_gate_temporal_qa40_determinism.py` (new).

### Task 5.2: Performance/resource guard
- **Location**: `tools/gate_temporal_qa40_perf.py` (new)
- **Description**: Enforce p50/p95 and runtime resource constraints under idle policy.
- **Complexity**: 4
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Gate emits pass/fail with exact deltas.
- **Validation**:
  - `tests/test_gate_temporal_qa40_perf.py` (new).

### Task 5.3: Reports/matrices update
- **Location**: `docs/reports/implementation_matrix.md`, `artifacts/query_acceptance/`
- **Description**: Publish temporal suite artifacts and strict summary for promotion.
- **Complexity**: 2
- **Dependencies**: Task 5.2
- **Acceptance Criteria**:
  - Report references exact artifact paths and timestamps.

## Testing Strategy
- After each sprint, run targeted tests for that sprint plus temporal smoke query run.
- Sprint 4+: run strict temporal40 matrix each sprint exit.
- Final promotion requires:
  - strict temporal40 (`40/40`, `0 skipped`, `0 failed`)
  - determinism gate pass (`N=5`)
  - no uncited `OK` answers.

## Potential Risks and Mitigations
- Risk: archetypes impossible on current corpus slice.
  - Mitigation: deterministic `NOT_FOUND/NEEDS_CLARIFICATION` and keep strict failure accounting visible.
- Risk: evidence payload bloat hurts latency.
  - Mitigation: bounded evidence windows + explicit caps while preserving required minima.
- Risk: vector similarity questions drift by backend behavior.
  - Mitigation: lock retrieval params and record embedding/doc IDs in evidence.
- Risk: hidden fallback to raw media.
  - Mitigation: explicit query-path guard + test asserting no raw-access dependency.

## Rollback Plan
- Keep existing advanced/generic suites untouched and feature-flag temporal suite path.
- If temporal profile regresses latency or correctness, disable temporal profile in release gate while retaining artifacts for debugging.
- Re-enable only after strict matrix and determinism gates pass again.

