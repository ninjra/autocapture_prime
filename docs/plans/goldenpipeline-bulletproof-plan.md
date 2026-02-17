# Plan: Golden Pipeline Bulletproof Closure

**Generated**: 2026-02-15  
**Estimated Complexity**: High

## Overview
Harden the WSL-side golden pipeline so it is deterministic, citation-grounded, and resilient for natural-language recall from extracted state only (no screenshot dependency at query time). The plan prioritizes strict contract checks, robust VLM/OCR extraction quality, full plugin attribution, and measurable correctness on the 20-question suite.

## Skills Selected (and Why)
- `plan-harder`: required to build the phased implementation plan.
- `shell-lint-ps-wsl`: enforce command correctness and avoid cross-shell mistakes.
- `golden-answer-harness`: run and gate curated Q/H cases against drift.
- `evidence-trace-auditor`: enforce citation/provenance chain for every answer.
- `deterministic-tests-marshal`: detect nondeterminism and lock signatures.
- `perf-regression-gate`: keep latency/throughput targets stable across changes.
- `resource-budget-enforcer`: verify idle CPU/RAM budget behavior and preemption.

## Prerequisites
- Sidecar writes media and contracts under `/mnt/d/autocapture` (Mode B).
- External vLLM service reachable at `http://127.0.0.1:8000` with `/health` and `/v1/models`.
- Embedder endpoint reachable at `http://127.0.0.1:8001` (or fallback policy set).
- Golden profile config locked: `config/profiles/golden_full.json`.

## Sprint 0: Fail-Closed Readiness Preflight
**Goal**: Block all downstream work unless runtime prerequisites are verifiably healthy.
**Demo/Validation**:
- `tools/preflight_runtime.py` returns all checks `ok=true`.
- Missing media root / unreachable endpoint produces explicit fail reason and non-zero exit.

### Task 0.1: Preflight gate wiring
- **Location**: `tools/preflight_runtime.py`, `tools/check_embedder_endpoint.py`, `autocapture_nx/inference/vllm_endpoint.py`
- **Description**: Validate sidecar media root, golden profile readability, vLLM `/v1/models` readiness, and embedder endpoint before any eval/query invocation.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Preflight blocks execution with actionable remediation.
  - Gate output includes endpoint latency, model-id list status, and missing-path diagnostics.
- **Validation**:
  - Unit tests for each fail mode + one all-green fixture.

## Sprint 1: Contracts and Determinism Baseline
**Goal**: Make pipeline preflight fail-closed and reproducible before feature work.
**Demo/Validation**:
- `tools/sidecar_contract_validate.py --dataroot /mnt/d/autocapture` passes.
- `tools/run_full_repo_miss_refresh.sh` shows no actionable misses.
- Determinism signature for a fixed report remains stable.

### Task 1.1: Enforce external endpoint preflight
- **Location**: `tools/preflight_runtime.py`, `tools/check_embedder_endpoint.py`, `autocapture_nx/inference/vllm_endpoint.py`
- **Description**: Add hard-fail checks for vLLM model-list accessibility and embedder health before query/eval starts.
- **Complexity**: 4
- **Dependencies**: Task 0.1
- **Acceptance Criteria**:
  - Preflight fails with explicit reason when `/v1/models` is unreachable.
  - Query/eval tools return actionable remediation text.
- **Validation**:
  - Unit tests for endpoint failure modes and recovery messaging.

### Task 1.2: Determinism signature gate for golden runs
- **Location**: `tools/run_advanced10_queries.py`, `autocapture_nx/kernel/query.py`
- **Description**: Persist and compare canonical signatures for every case (per profile hash + model id + prompt hash).
- **Complexity**: 5
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Signature diff report emitted on any mismatch.
  - Strict mode exits non-zero on drift.
- **Validation**:
  - Re-run same suite twice; assert identical signatures.

## Sprint 2: Ingest and Extraction Hardening (Media Root)
**Goal**: Bulletproof extraction from `/mnt/d/autocapture/media` into durable structured state.
**Demo/Validation**:
- Batch ingest from media root produces expected SST/state artifacts.
- No query path requires original screenshot bytes after extraction.

### Task 2.1: Media-root batch ingest reliability
- **Location**: `autocapture_prime/ingest/*`, `autocapture_nx/processing/idle.py`, `tools/run_single_media_ingest.py` (new)
- **Description**: Add robust directory walker + resumable checkpoints + provenance hashes.
- **Complexity**: 6
- **Dependencies**: Sprint 1 complete
- **Acceptance Criteria**:
  - Interruption-safe resume with no duplicated record IDs.
  - Journal/ledger entries include batch provenance.
- **Validation**:
  - Integration test with synthetic interruption/restart.

### Task 2.2: Two-pass extraction contract lock
- **Location**: `plugins/builtin/vlm_vllm_localhost/plugin.py`, `plugins/builtin/processing_sst_ui_vlm/plugin.py`, `config/profiles/golden_full.json`
- **Description**: Ensure thumbnail pass -> ROI hi-res pass -> merge JSON is always enabled and schema-validated.
- **Complexity**: 7
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Each frame stores `ui_state` with ROI provenance.
  - Merge step rejects malformed ROI outputs.
- **Validation**:
  - Fixture tests with malformed/partial ROI payloads.

## Sprint 3: Retrieval + Reasoning Robustness
**Goal**: Make answers generic and class-based (not tactical shortcuts), with strong evidence mapping.
**Demo/Validation**:
- 20-case suite answers are sourced from pipeline outputs with provider attribution.
- Hard VLM answer path no longer dominates when evidence score is weaker.

### Task 3.1: Provider contribution scoring and arbitration hardening
- **Location**: `autocapture_nx/kernel/query.py`, `plugins/builtin/observation_graph/plugin.py`
- **Description**: Reweight answer arbitration using citation completeness, schema confidence, and cross-provider agreement.
- **Complexity**: 7
- **Dependencies**: Sprint 2 complete
- **Acceptance Criteria**:
  - Arbitration trace explains winner selection deterministically.
  - Failed citation coverage blocks final answer.
- **Validation**:
  - Golden tests asserting winner/provider sequence for selected cases.

### Task 3.2: JEPA/state path utilization verification
- **Location**: `plugins/builtin/state_*`, `autocapture_nx/kernel/query.py`
- **Description**: Require and log state-layer contribution for temporal/relationship questions.
- **Complexity**: 6
- **Dependencies**: Task 2.2, Task 3.1
- **Acceptance Criteria**:
  - Query trace includes state evidence IDs when topic requires state.
  - If missing, answer marked indeterminate.
- **Validation**:
  - Tests for temporal questions with/without state evidence.

### Task 3.3: Baseline metrics instrumentation (before perf sprint)
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/processing/idle.py`, `tools/gate_perf.py`
- **Description**: Emit normalized timing/resource metrics (ingest/query/budget/preemption) so Sprint 5 can compare against real baselines.
- **Complexity**: 5
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Metrics include p50/p95 latencies and budget/preemption counters.
  - Artifacts written in deterministic JSON schema.
- **Validation**:
  - Unit test for metrics schema + integration test for non-empty metric output.

## Sprint 4: Q/H 20-case Bulletproof Gate
**Goal**: Keep all 20 questions passing with confidence + proof output.
**Demo/Validation**:
- `evaluated_passed == 20` on strict run.
- Exported per-case rationale/proof report generated automatically.

### Task 4.1: Unified 20-case report emitter
- **Location**: `tools/run_advanced10_queries.py`, `tools/render_advanced20_answers.py` (new), `docs/reports/advanced20_answers_latest.md`
- **Description**: Emit concise answer, rationale bullets, top providers, and citation proof per case.
- **Complexity**: 5
- **Dependencies**: Sprint 3 complete
- **Acceptance Criteria**:
  - One markdown report with all 20 cases and verifiable evidence pointers.
  - Includes confidence and determinism signature.
- **Validation**:
  - Snapshot test on generated report structure.

### Task 4.2: Determinism/proof bridge into answer report
- **Location**: `tools/run_advanced10_queries.py`, `tools/render_advanced20_answers.py` (new)
- **Description**: Wire canonical signatures + provider traces directly into rendered answer report rows and cross-verify values against strict-run JSON.
- **Complexity**: 4
- **Dependencies**: Task 1.2, Task 4.1
- **Acceptance Criteria**:
  - Every case row includes determinism signature + provider evidence IDs.
  - Mismatch between strict JSON and rendered report fails generation.
- **Validation**:
  - Golden snapshot test with enforced signature equality.

### Task 4.3: Feedback-aware regression loop
- **Location**: `tools/query_latest_single.py`, `tools/query_eval_suite.py`, `docs/query_eval_cases_advanced20.json`
- **Description**: Incorporate user verdicts only as labels; never force-pass. Track failures and plugin deltas.
- **Complexity**: 6
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - No path marks expected pass without matching output.
  - Plugin-change-to-pass trace stored in report.
- **Validation**:
  - Negative test that incorrect answer cannot be marked pass.

### Task 4.4: 20-case corpus governance
- **Location**: `docs/query_eval_cases_advanced20.json`, `tools/run_advanced10_queries.py`, `docs/reports/advanced20_answers_latest.md`
- **Description**: Pin and record corpus hash/version in strict output and rendered report; fail strict run on corpus drift unless explicitly version-bumped.
- **Complexity**: 4
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Strict output includes `cases_sha256`.
  - Report includes corpus version/hash footer.
- **Validation**:
  - Drift test modifying one question causes strict gate failure.

## Sprint 5: Performance and Idle-Time Orchestration Hardening
**Goal**: Maintain reliability under idle budgets with predictable latency.
**Demo/Validation**:
- Idle budget tests pass (`CPU <=50%`, `RAM <=50%`), preemption works on activity.
- Query latency and ingest throughput remain within configured SLO bands.

### Task 5.1: Idle scheduler budget conformance tests
- **Location**: `autocapture/runtime/*`, `autocapture_nx/processing/idle.py`, `tests/test_idle_processor_chunking.py`
- **Description**: Add stress tests for max concurrency, preempt grace, resume behavior.
- **Complexity**: 6
- **Dependencies**: Task 3.3, Sprint 4 complete
- **Acceptance Criteria**:
  - Deterministic pass/fail for over-budget scenarios.
  - Budget and preemption events journaled.
- **Validation**:
  - Resource budget enforcer suite in CI gate.

### Task 5.2: Perf regression checkpoints
- **Location**: `tools/gate_perf.py`, `docs/reports/repo_tooling_summary.md`
- **Description**: Pin p50/p95 thresholds for ingest/query and fail on regression.
- **Complexity**: 4
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Gate blocks on threshold breach.
  - Report includes trend deltas.
- **Validation**:
  - Controlled benchmark run with synthetic baseline.

## Testing Strategy
- Unit tests for parsers, arbitration, endpoint preflight, and schema contracts.
- Integration tests for media-root ingest -> SST/state -> query.
- Golden 20-case strict gate with deterministic signatures and evidence checks.
- Performance + resource-budget gates in pre-merge.

## Potential Risks & Gotchas
- vLLM `/health` may pass while `/v1/models` fails: enforce model-list preflight.
- Tactical shortcut regressions may reappear through fallback paths: require strict structured checks.
- Archived docs can pollute miss inventory: keep `docs/deprecated` excluded in scanners.
- Large OCR noise can drown VLM evidence: enforce bounded evidence windows + schema-first extraction.

## Rollback Plan
- Revert profile/plugin gating changes by commit if strict gate blocks production flow.
- Keep previous report artifacts for forensic diff.
- Toggle strict mode only for emergency debugging, never for golden pass criteria.
