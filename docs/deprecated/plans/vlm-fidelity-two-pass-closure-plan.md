# Plan: VLM Fidelity Two-Pass Closure

**Generated**: 2026-02-14  
**Estimated Complexity**: High

## Overview
Raise extraction fidelity to production grade for the golden pipeline by hardening a two-pass VLM workflow (thumbnail ROI discovery + native-resolution ROI parse), enforcing schema-complete structured outputs, and making strict Q/H evaluation fail only on real misses.

The target outcome is deterministic, citation-backed answers from extracted metadata only (no query-time screenshot dependency) with full plugin-path attribution and confidence calibration.

## Required vLLM Server-Side Changes
- Serve a **vision-capable OpenAI-compatible model** on `http://127.0.0.1:8000` that returns grounded image reasoning (not template placeholders).
- Ensure server supports multimodal chat requests with `image_url` content and stable JSON-mode responses.
- Required runtime checks:
  - `GET /v1/models` returns at least one vision-capable model id.
  - `POST /v1/chat/completions` with one known screenshot sanity prompt returns grounded fields (subject/button/text) not generic boilerplate.
- Recommended serving constraints:
  - `host=127.0.0.1` only.
  - Sufficient context and image budget for multi-ROI extraction (do not starve multimodal tokens).
  - Keep model stable across runs (pin model id/version) to prevent eval drift.

## Prerequisites
- External vLLM healthy on localhost: `127.0.0.1:8000`.
- Golden profile baseline: `config/profiles/golden_full.json`.
- Strict eval sets:
  - `docs/query_eval_cases_advanced20.json`
  - `docs/autocapture_prime_testquestions2.txt`
- Existing strict runner:
  - `tools/run_golden_qh_cycle.sh`
  - `tools/run_advanced10_queries.py`

## Sprint 1: vLLM Contract + Guardrails
**Goal**: Fail fast when server/model cannot provide high-fidelity multimodal output.  
**Demo/Validation**:
- Preflight rejects weak/invalid VLM backends before long runs.
- Sanity probe artifact includes measured groundedness checks.

### Task 1.1: Add VLM groundedness preflight probe
- **Location**: `tools/preflight_runtime.py`, `autocapture_nx/inference/vllm_endpoint.py`
- **Description**: Add a multimodal sanity prompt test using a fixed fixture image and strict expected fields.
- **Complexity**: 5
- **Dependencies**: None
- **Acceptance Criteria**:
  - Preflight returns non-zero when model responds with boilerplate/non-grounded text.
  - Report includes model id, latency, and failure reason.
- **Validation**:
  - Unit test + manual run against healthy and intentionally weak model.

### Task 1.2: Enforce preflight in golden cycle
- **Location**: `tools/run_golden_qh_cycle.sh`, `tools/process_single_screenshot.py`
- **Description**: Block cycle execution when vLLM groundedness preflight fails.
- **Complexity**: 3
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Golden run aborts early with clear actionable server-side message.
- **Validation**:
  - Integration test with mocked failing preflight.

## Sprint 2: Two-Pass VLM Hardening
**Goal**: Ensure two-pass extraction produces dense, structured UI state from full-resolution image regions.  
**Demo/Validation**:
- `derived.text.vlm` carries non-trivial windows/elements/facts from multiple ROIs.
- Sparse recovered layouts no longer dominate pipeline.

### Task 2.1: Query-conditioned ROI strategy
- **Location**: `plugins/builtin/vlm_vllm_localhost/plugin.py`
- **Description**: Add topic-aware ROI expansion policies (calendar, incident card, Slack pane, console, tab strip) with native-resolution crops.
- **Complexity**: 7
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - ROI list includes domain-relevant panes and preserves global coordinate mapping.
- **Validation**:
  - Fixture tests asserting ROI coverage for Q1..Q10 regions.

### Task 2.2: Schema-complete retry loop per ROI
- **Location**: `plugins/builtin/vlm_vllm_localhost/plugin.py`
- **Description**: Retry extraction with tighter crops/alternate prompts when required schema keys are missing.
- **Complexity**: 8
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Structured fields for incident/activity/details/calendar are present or explicitly marked indeterminate with reason.
- **Validation**:
  - Deterministic tests with forced partial outputs.

### Task 2.3: Add parser quality metrics to payload
- **Location**: `plugins/builtin/vlm_vllm_localhost/plugin.py`, `autocapture_nx/processing/idle.py`
- **Description**: Persist extraction quality counters (elements, windows, facts, schema completeness %, retries, backend path).
- **Complexity**: 5
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Metadata includes quality metrics consumed by downstream gating.
- **Validation**:
  - Record-schema tests and sample artifact assertions.

## Sprint 3: Structured Extractor Fidelity (Generic, Not Question-Specific)
**Goal**: Improve advanced record correctness using generic parsers over fused VLM/OCR/layout evidence.  
**Demo/Validation**:
- `adv.*` and `obs.*` records include complete high-signal values for strict Q/H checks.

### Task 3.1: Robust incident/timeline/details parsers
- **Location**: `plugins/builtin/observation_graph/plugin.py`
- **Description**: Replace brittle regex-only extraction with row/column-aware structured parsers and confidence gates.
- **Complexity**: 8
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Subject/sender/domain/buttons/timeline/details fields are consistently extracted with provenance.
- **Validation**:
  - New unit fixtures for each parser domain.

### Task 3.2: Calendar/slack/dev/console/browser parsers
- **Location**: `plugins/builtin/observation_graph/plugin.py`
- **Description**: Add layout-aware parsing for schedule rows, DM message pairing, dev-note sections, line-color classification, and browser chrome.
- **Complexity**: 8
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - `adv_calendar`, `adv_slack`, `adv_dev`, `adv_console`, `adv_browser` produce strict-grade fields.
- **Validation**:
  - Domain fixture tests + regression snapshots.

### Task 3.3: VLM/OCR fusion policy with explicit provenance
- **Location**: `plugins/builtin/observation_graph/plugin.py`
- **Description**: Keep VLM as grounding source, use OCR for completion only when VLM graph quality is below threshold; store fusion mode flags.
- **Complexity**: 6
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Each derived advanced record exposes source modality, backend, and mixed-fallback state.
- **Validation**:
  - Tests for VLM-only, OCR-only, and mixed paths.

## Sprint 4: Query Path + Hard-Question Reliability
**Goal**: Ensure advanced and hard questions consume structured extracted data and return deterministic fields.  
**Demo/Validation**:
- No “indeterminate” for cases where structured evidence exists.
- Hard question fields emitted as typed structures, not free-text only.

### Task 4.1: Strengthen advanced source selection
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Prefer highest-quality `adv.*` source by provenance and completeness; enforce deterministic tie-breaks.
- **Complexity**: 6
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Advanced topics consistently select populated `adv.*` records.
- **Validation**:
  - Query tests for Q1..Q10 with source-trace assertions.

### Task 4.2: Hard-VLM field contract tightening
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Add per-topic required fields and structured retries before returning hard-topic display output.
- **Complexity**: 7
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - `H1..H10` fields emitted in structured form when evidence exists.
- **Validation**:
  - Hard-case contract tests (`expected_answer` exact structure).

### Task 4.3: Eliminate false fallback confidence
- **Location**: `autocapture_nx/kernel/query.py`, `tools/run_advanced10_queries.py`
- **Description**: Keep strict-mode exact checks and ensure display summaries cannot mask missing structured fields.
- **Complexity**: 4
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Strict eval only passes on structured correctness.
- **Validation**:
  - Existing strict eval tests + added negative tests.

## Sprint 5: Metrics, Confidence, and Plugin Path Attribution
**Goal**: Produce actionable optimization data per question and per plugin path.  
**Demo/Validation**:
- Each question row includes confidence, plugin path, timings, and correctness.
- Reports identify underperforming plugins/stages.

### Task 5.1: Per-question confidence calibration
- **Location**: `autocapture_nx/kernel/query.py`, `tools/run_advanced10_queries.py`
- **Description**: Add calibrated confidence score/label from evidence quality + consistency.
- **Complexity**: 5
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - Every Q/H result includes confidence numeric + band.
- **Validation**:
  - Calibration tests and confusion matrix checks.

### Task 5.2: Full plugin execution matrix export
- **Location**: `tools/generate_qh_plugin_validation_report.py`, `docs/reports/`
- **Description**: Emit all plugins with `loaded/failed/in-path/out-of-path/helped/hurt/latency`.
- **Complexity**: 6
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - One report shows complete plugin inventory and per-question contribution.
- **Validation**:
  - Snapshot test on matrix schema and non-empty contribution rows.

### Task 5.3: Workflow tree artifact per run
- **Location**: `tools/export_run_workflow_tree.py`, `docs/reports/question-validation-plugin-trace-*.md`
- **Description**: Generate deterministic tree linking answer -> path -> plugin -> record -> citation.
- **Complexity**: 4
- **Dependencies**: Task 5.2
- **Acceptance Criteria**:
  - Tree generated for every strict run.
- **Validation**:
  - CI check for artifact presence and parseable format.

## Sprint 6: Performance + Resource Optimization
**Goal**: Use GPU aggressively while preserving stability and deterministic output.  
**Demo/Validation**:
- Throughput improves while accuracy does not regress.
- Idle/active budget constraints remain within policy.

### Task 6.1: Batched ROI inference scheduling
- **Location**: `plugins/builtin/vlm_vllm_localhost/plugin.py`, `autocapture_nx/processing/idle.py`
- **Description**: Batch ROI calls and reserve step budget for OCR+VLM+SST in one bounded cycle.
- **Complexity**: 6
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Fewer idle steps to complete full extraction; no starvation of SST/state stages.
- **Validation**:
  - Performance benchmark + step-level metrics assertions.

### Task 6.2: Resource budget verification under load
- **Location**: `tools/`, `tests/`
- **Description**: Add deterministic soak checks for CPU/RAM idle gates and sustained GPU utilization behavior.
- **Complexity**: 5
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Policy budget tests pass with extraction workload enabled.
- **Validation**:
  - Automated soak verification job.

## Testing Strategy
- **Unit**: parser behavior, source selection, confidence logic, strict evaluator modes.
- **Integration**: `tools/process_single_screenshot.py` + `tools/run_advanced10_queries.py` on fixture screenshot.
- **End-to-end**: `tools/run_golden_qh_cycle.sh` strict mode, with generated plugin tree + metrics artifacts.
- **Regression gate**: fail on any drop in strict pass count or confidence calibration sanity.

## Potential Risks & Gotchas
- VLM server appears healthy but outputs low-quality generic JSON; mitigate with groundedness preflight and schema retry logic.
- Plugin lock mismatches after code edits can silently break required plugins; enforce lock refresh in dev workflow.
- Overfitting to one screenshot can creep in via regexes; enforce generic parser tests with synthetic variants.
- High GPU utilization may starve other stages if scheduling is naive; enforce bounded per-step budgets and staged quotas.

## Rollback Plan
- Keep changes behind profile flags (`golden_full`/feature toggles) until strict pass improvements are validated.
- If fidelity regresses, rollback to last known-good commit and retain new instrumentation/reporting for diagnosis.
- Preserve old evaluator artifacts for diff comparison before and after rollback.

