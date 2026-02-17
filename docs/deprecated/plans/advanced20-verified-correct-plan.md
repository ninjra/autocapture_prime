# Plan: Advanced20 Verified-Correct Closure

**Generated**: 2026-02-16  
**Estimated Complexity**: High

## Overview
Close the remaining correctness gap for Q1..Q10 + H1..H10 by enforcing a strict, deterministic, promptops-first pipeline where every query is answered from persisted extracted records (not raw screenshot reads at query time), every answer is provenance-backed, and every pass is validated by objective checks rather than weak substring matching.

Approach:
- Make promptops mandatory for all query/model hops.
- Raise extraction fidelity with two-pass VLM and structured derived records.
- Tighten evaluator gates to block false greens.
- Add per-plugin and per-sequence contribution metrics with confidence and citation integrity.
- Run repeated deterministic advanced20 cycles and fail closed on regressions.

## Prerequisites
- External VLM endpoint healthy on `http://127.0.0.1:8000` with multimodal model.
- Golden screenshot-derived run artifact available under `artifacts/single_image_runs/*/report.json`.
- Local virtualenv available: `.venv/bin/python`.
- Plugin locks up to date after manifest/code changes.
- Repro bootstrap step exists and is runnable in one shot:
  - Build/verify venv dependencies.
  - Regenerate golden single-image artifacts.
  - Verify strict local-only endpoint preflight (`/health`, `/v1/models`, and a minimal completion).

## Sprint 1: Truthful Evaluation Gate
**Goal**: Remove false-positive “pass” outcomes and make advanced20 grading strict-by-default.  
**Demo/Validation**:
- Run advanced20 once and inspect failed rows with exact failed checks.
- Confirm evaluator reports pipeline-path failures when expected providers/structured outputs are missing.

### Task 1.1: Harden advanced20 evaluator checks
- **Location**: `tools/run_advanced10_queries.py`
- **Description**: Enforce mandatory gates for Q-series/H-series using structured field checks, promptops usage signal, provider-path requirements, and deterministic reproducibility checks.
- **Complexity**: 7
- **Dependencies**: None
- **Acceptance Criteria**:
  - No case can pass when required structured fields are missing.
  - No case can pass when required provider path is absent.
  - Evaluator output includes explicit failed-check inventory.
- **Validation**:
  - `pytest` for evaluator tests and one strict advanced20 run.

### Task 1.2: Add fail-closed schema for expected checks
- **Location**: `docs/query_eval_cases_advanced20.json`, `tools/run_advanced10_queries.py`
- **Description**: Ensure each case has explicit expected structure and strict match semantics; reject under-specified cases.
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - All 20 cases are strictly evaluated (`evaluated=true` semantics).
  - Missing expected fields fail immediately.
- **Validation**:
  - Local script asserts full strictness coverage for 20/20 cases.

## Sprint 2: PromptOps-First Query and Model Interface
**Goal**: Ensure promptops is the mandatory interface for query text and all VLM/LLM calls with measurable telemetry.  
**Demo/Validation**:
- Query ledger and promptops metrics show prompt rewrites + model interaction rows.
- Promptops review path can persist improved prompts after failed interactions.

### Task 2.1: Enforce promptops at query ingress
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture/promptops/engine.py`, `autocapture/promptops/propose.py`
- **Description**: Use `prepare_query` for state/classic query flows; persist query strategy metadata in processing and ledger payloads.
- **Complexity**: 6
- **Dependencies**: None
- **Acceptance Criteria**:
  - Query output includes promptops usage/applied/strategy fields.
  - Query ledger event includes original/effective query and strategy.
- **Validation**:
  - `tests/test_query_ledger_entry.py`, `tests/test_query_trace_fields.py`.

### Task 2.2: Enforce promptops at model callsites
- **Location**: `plugins/builtin/vlm_vllm_localhost/plugin.py`, `plugins/builtin/answer_synth_vllm_localhost/plugin.py`, `plugins/builtin/ocr_nemotron_torch/plugin.py`, `autocapture_nx/kernel/query.py`
- **Description**: Route every VLM/LLM prompt through promptops and record interaction telemetry (latency, success, error, response footprint, prompt deltas).
- **Complexity**: 8
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - All active `chat_completions` call paths emit promptops model_interaction metrics.
  - Failure-only review can propose/store prompt improvements.
- **Validation**:
  - Unit tests for promptops layer and plugin call paths.
  - Metrics file contains rows for each model path in one run.

### Task 2.3: Lock promptops defaults to non-noop in golden profile
- **Location**: `config/default.json`, `config/profiles/golden_full.json`, plugin manifests in `plugins/builtin/*/plugin.json`
- **Description**: Set non-`none` strategies (`normalize_query` and `model_contract`), enable metrics/review defaults, and keep fail-closed behavior.
- **Complexity**: 5
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Promptops defaults are active for golden profile.
  - Plugin settings schemas support promptops block.
- **Validation**:
  - JSON schema load tests and plugin lock refresh.

### Task 2.4: Enforce localhost-only model endpoint binding
- **Location**: `autocapture_nx/inference/vllm_endpoint.py`, plugin manifests/config under `plugins/builtin/*` and `config/*`
- **Description**: Add/verify diagnostics that reject non-`127.0.0.1` endpoints for VLM/LLM/promptops review paths.
- **Complexity**: 5
- **Dependencies**: Task 2.3
- **Acceptance Criteria**:
  - Non-localhost endpoint config fails preflight.
  - Golden run artifacts record endpoint policy status.
- **Validation**:
  - Endpoint policy tests and one negative test fixture.

## Sprint 3: Structured Extraction Fidelity for Q/H Domains
**Goal**: Increase extracted-record fidelity so answers come from structured evidence, not OCR text dumps.  
**Demo/Validation**:
- Derived records contain normalized fields for windows/focus/incident/details/calendar/chat/console/browser.
- Query answers are concise summaries generated from structured fields plus citations.

### Task 3.1: Complete two-pass VLM ROI extraction contract
- **Location**: `plugins/builtin/vlm_vllm_localhost/plugin.py`, `autocapture_nx/processing/sst/stage_plugins.py`
- **Description**: Strengthen thumbnail ROI proposal + hi-res ROI parse + merge dedupe into stable UI-state JSON with robust windows/facts coverage.
- **Complexity**: 9
- **Dependencies**: Sprint 2 complete
- **Acceptance Criteria**:
  - UI-state contains deterministic windows/rois/facts for advanced20 domains.
  - Re-run on same input yields stable fact keys and ordering tolerances.
- **Validation**:
  - Determinism tests and fixture comparisons.

### Task 3.2: Normalize domain-specific derived records
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/kernel/model_output_records.py`, SST plugins under `autocapture_nx/processing/sst/`
- **Description**: Emit canonical derived records for all question classes (Q1..Q10, H1..H10) with typed fields and confidence.
- **Complexity**: 8
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Every question class maps to one or more generic record types and fields.
  - No question-specific hardcoded answer text generation.
- **Validation**:
  - Case-by-case extraction assertions and schema checks.

### Task 3.3: Enforce metadata-only query mode
- **Location**: `autocapture_nx/kernel/query.py`, `tools/run_advanced10_queries.py`
- **Description**: Ensure evaluation answers are generated from stored records only; disallow direct screenshot dependence during query evaluation.
- **Complexity**: 6
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Advanced20 still answers correctly when screenshot bytes are absent at query time.
  - Explicit failure when required extraction artifacts are missing.
- **Validation**:
  - Metadata-only test mode run with strict advanced20.
  - Explicit mode flag and test harness path documented (no implicit behavior).

## Sprint 4: Attribution, Confidence, and Reviewer Verification Loop
**Goal**: Make outputs auditable: what plugin contributed what, with confidence and correctness tracking from reviewer feedback.  
**Demo/Validation**:
- For each case: answer, confidence, top evidence, provider sequence, and correctness feedback are all captured.

### Task 4.1: Provider sequence attribution report
- **Location**: `tools/run_advanced10_queries.py`, `tools/render_advanced20_answers.py`, `docs/reports/`
- **Description**: Emit per-case path graph: plugin list, contribution basis points, in-path/out-of-path status, and latency slices.
- **Complexity**: 7
- **Dependencies**: Sprint 3 complete
- **Acceptance Criteria**:
  - Report includes all loaded plugins with participation flags.
  - Top contributing provider chain is explicit per answer.
- **Validation**:
  - Report diff checks across runs; schema validation.

### Task 4.2: Correctness feedback as training signal, never pass override
- **Location**: `tools/query_feedback.py`, query/eval tooling paths
- **Description**: Persist reviewer feedback (`expected`, `actual`, `agree/disagree`) for analysis and promptops review, but never let feedback force evaluator pass.
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Feedback affects diagnostics/recommendations only.
  - Evaluator pass state remains evidence/check driven.
  - Any promptops-reviewed prompt change is logged and never auto-promoted to “pass”.
- **Validation**:
  - Regression tests proving feedback cannot flip a failed case to pass.

### Task 4.4: PromptOps review drift guardrail
- **Location**: `autocapture/promptops/engine.py`, evaluator harness files under `tools/`
- **Description**: For each reviewed prompt candidate, persist diff + hash, run deterministic re-eval, and require explicit approval gate before promotion to active prompt store.
- **Complexity**: 7
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Reviewed prompt updates are auditable with before/after and evaluation delta.
  - No silent prompt replacement path exists.
- **Validation**:
  - Unit tests for review/persist behavior and audit rows.

### Task 4.3: Confidence calibration
- **Location**: `tools/run_advanced10_queries.py`, query confidence logic
- **Description**: Calibrate confidence from structural completeness, citation integrity, provider diversity, and deterministic stability.
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Confidence decreases on missing fields/weak citations/inconsistent reruns.
  - Confidence correlates with pass/fail outcomes.
- **Validation**:
  - Calibration test set from advanced20 artifacts.

## Sprint 5: Deterministic Closure and Drift Gate
**Goal**: Ship a repeatable closure gate where advanced20 is truly green and stays green.  
**Demo/Validation**:
- Run `N` repeated strict cycles with same results and confidence deltas within tolerance.
- Generate final “DO_NOT_SHIP if any regress” summary.

### Task 5.1: Repeated strict cycle harness
- **Location**: `tools/run_golden_qh_cycle.sh`, `tools/run_advanced10_queries.py`
- **Description**: Run repeated strict advanced20 cycles; fail on any mismatch in pass/fail, key fields, or determinism checks.
- **Complexity**: 7
- **Dependencies**: Sprint 4 complete
- **Acceptance Criteria**:
  - Reproducible pass set and stable per-case check vectors across runs.
  - Minimum `N=3` consecutive strict runs.
  - Zero drift for pass/fail vectors and required field hashes.
  - Confidence drift tolerance <= 1% absolute per case.
  - Drift report generated automatically.
- **Validation**:
  - Multi-run CI/local gate execution.

### Task 5.2: Golden artifact publication
- **Location**: `docs/reports/advanced20_answers_latest.txt`, new closure report under `docs/reports/`
- **Description**: Publish final table for all 20 questions with answer, correctness verdict, confidence, evidence rationale, and plugin path.
- **Complexity**: 5
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - One canonical latest artifact and one machine-readable JSON artifact.
  - Includes failed-case diagnosis and next-action recommendation if not 20/20.
- **Validation**:
  - Report integrity checks and manual spot-check against artifacts.

## Testing Strategy
- Unit: promptops strategy/metrics/review, evaluator strict checks, provider attribution parsing.
- Integration: query paths (state + classic), VLM/OCR/synth plugin promptops hooks.
- Determinism: repeated advanced20 runs with fixed seeds/config.
- Policy/Security: localhost-only endpoint policy, lock integrity, no fabricated-citation checks.
- Acceptance: strict advanced20 summary must be 20/20 with reproducibility gate green.

## Potential Risks & Gotchas
- VLM server health endpoint can be green while model list/chat path fails.
  - **Mitigation**: preflight checks must test `/v1/models` + one minimal completion, not health only.
- OCR-heavy fallback can swamp structured VLM facts.
  - **Mitigation**: prioritize structured fact channels and down-rank plain OCR-only answers for structured questions.
- Promptops review could drift prompts in a harmful direction.
  - **Mitigation**: keep validation + eval gates before persisting reviewed prompts.
- Determinism can break from hidden env overrides.
  - **Mitigation**: enforce blocked env override list in golden profile and record runtime fingerprint.

## Rollback Plan
- Keep lockfile snapshots and tagged baseline artifacts before each sprint.
- If strict pass rate regresses, revert sprint-local commits and restore last known-good lock/profile.
- Disable promptops review persistence (keep metrics only) if drift appears, then re-enable after guardrail fixes.
