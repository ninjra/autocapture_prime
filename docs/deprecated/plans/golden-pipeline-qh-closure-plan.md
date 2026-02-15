# Plan: Golden Pipeline Q/H Closure

**Generated**: 2026-02-13
**Estimated Complexity**: High

## Overview
Build a deterministic, full-plugin golden workflow that can answer all current Q/H questions from extracted metadata only (no query-time image dependence), with strict correctness evaluation, per-plugin contribution proof, and performance telemetry.

This plan closes the current failure mode where answers appear "ok" while strict coverage is incomplete and attribution collapses to a single provider label.

## Current Reality (Evidence)
- Q/H artifact shows partial correctness: `artifacts/advanced10/advanced20_20260213T032827Z_rerun1.json`.
- Q1..Q10 are currently non-strict (`expected_eval.evaluated=false`), so pass/fail is not enforcement-grade.
- Provider attribution is coarse because `derived.sst.*` maps to `builtin.processing.sst.pipeline` in `autocapture_nx/kernel/query.py`.
- `builtin.observation.graph` failed load in the last run report, reducing graph-based reasoning coverage.
- Current hard-question route relies on query-topic heuristics in `autocapture_nx/kernel/query.py` (keyword-triggered path), which is not fully generic.

## Goals
- 100% strict pass on Q1..Q10 and H1..H10 in one deterministic run.
- Every answer must include machine-verifiable provenance and plugin path trace.
- Full workflow must prove contribution from extraction/reasoning/index/retrieval stages, not just one aggregate SST provider label.
- No tactical shortcuts: remove question-text-specific routing logic as primary answer mechanism.
- Optimize 4 pillars: Performance, Accuracy, Security, Citeability.

## Non-Goals
- Reintroducing capture plugins in this repo.
- Query-time direct screenshot dependence for golden eval answers.

## Prerequisites
- External vLLM service available on `127.0.0.1:8000`.
- Sidecar provides Mode-B contract data where needed.
- Existing eval sets:
  - `docs/query_eval_cases_advanced20.json`
  - `docs/autocapture_prime_testquestions2.txt`

## Sprint 1: Strict Evaluation Baseline
**Goal**: Make Q/H grading fail-closed and deterministic.
**Demo/Validation**:
- Single run emits strict pass/fail for all 20 questions.
- No heuristic "ok" accepted without strict checks.

### Task 1.1: Convert all Q/H questions to strict expected-eval contracts
- **Location**: `docs/query_eval_cases_advanced20.json`, `tools/run_advanced10_queries.py`
- **Description**: Add explicit expected structures/validators for Q1..Q10 and revalidate/refactor H1..H10 so all 20 items use strict deterministic grading.
- **Complexity**: 6
- **Dependencies**: None
- **Acceptance Criteria**:
  - `expected_eval.evaluated=true` for all Q/H rows.
  - Any mismatch marks run failed.
- **Validation**:
  - Run advanced suite and assert `evaluated_total == 20`.

### Task 1.2: Add deterministic evaluator adapters per question class
- **Location**: `tools/query_eval_suite.py`, `tools/run_advanced10_queries.py`
- **Description**: Implement schema/tuple/IoU/order-aware validators for each question class (window list, timeline, KV, color lines, bbox).
- **Complexity**: 8
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Evaluator output includes per-constraint failures, not generic "failed".
- **Validation**:
  - Unit tests under `tests/` for validator behavior with fixed fixtures.

## Sprint 2: Full Plugin Activation Profile (Fail-Closed)
**Goal**: Ensure the golden run actually loads required plugin graph and fails when required nodes are absent.
**Demo/Validation**:
- Run report contains expected plugin set loaded (or explicit hard fail).

### Task 2.1: Define golden processing profile
- **Location**: `config/profiles/golden_qh.json` (new), `tools/process_single_screenshot.py`
- **Description**: Introduce explicit profile enabling extraction/index/reasoning plugins, including observation/state/JEPA path plugins.
- **Complexity**: 6
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Profile is the only config used for Q/H eval pipeline.
- **Validation**:
  - `report.json` shows profile hash and enabled plugin list.

### Task 2.2: Required-plugin gate
- **Location**: `tools/process_single_screenshot.py`, `autocapture_nx/kernel/loader.py`
- **Description**: Add `required_plugins` enforcement for golden mode; if any required plugin is failed/missing, run exits non-zero.
- **Complexity**: 7
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - `builtin.observation.graph` or any required stage missing => hard fail.
- **Validation**:
  - Negative test with one plugin intentionally disabled.

### Task 2.3: Lock/artifact integrity refresh path
- **Location**: `config/plugin_locks.json`, plugin build tooling scripts under `tools/`
- **Description**: Add deterministic lock refresh + verification step to prevent stale-hash load failures.
- **Complexity**: 5
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - No lock-hash mismatch in golden run.
- **Validation**:
  - `autocapture plugins load-report` clean for required plugins.

### Task 2.4: Wire golden profile into all eval entry points
- **Location**: `tools/process_single_screenshot.py`, `tools/run_advanced10_queries.py`, `tools/query_latest_single.py`
- **Description**: Make `config/profiles/golden_qh.json` the explicit profile for golden Q/H runs and CI jobs.
- **Complexity**: 5
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Golden profile is always visible in run artifacts and query traces.
- **Validation**:
  - CI/local runner asserts loaded profile id/hash matches golden profile.

### Task 2.5: Required-plugin preflight and retry safety
- **Location**: `tools/process_single_screenshot.py`, `autocapture_nx/kernel/loader.py`
- **Description**: Add preflight checks and bounded retries for transient plugin load failures before hard-failing required-plugin gate.
- **Complexity**: 4
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Transient startup issues are retried deterministically; persistent issues fail closed.
- **Validation**:
  - Fault-injection test for transient and persistent plugin failures.

## Sprint 3: Generic UI-State Extraction (VLM-first with OCR support)
**Goal**: Replace query-specific extraction logic with generic structured UI-state generation.
**Demo/Validation**:
- One ingestion pass emits reusable UI-state JSON and derived records used by all Q/H questions.

### Task 3.1: Two-pass UI extraction pipeline integration
- **Location**: `plugins/builtin/vlm_vllm_localhost/plugin.py`, `autocapture_nx/processing/sst/stage_plugins.py`
- **Description**: Implement thumbnail ROI proposal + hi-res ROI parse + merge into canonical UI-state records.
- **Complexity**: 9
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Emits stable `derived.obs.*` / `derived.ui_state.*` records with coordinates + confidence.
- **Validation**:
  - Determinism test: unchanged image yields stable state (within tolerance).

### Task 3.2: Structured extractors (window/focus/incidents/timeline)
- **Location**: `plugins/builtin/observation_graph/plugin.py`, `autocapture_nx/processing/sst/*`
- **Description**: Add reusable extractors for top-level windows, focus evidence, incident email header/buttons, and record-activity timeline.
- **Complexity**: 8
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Each extractor writes typed records independent of question wording.
- **Validation**:
  - Per-extractor fixture tests.

### Task 3.3: Structured extractors (details/calendar/chat/console/browser/actions)
- **Location**: `plugins/builtin/observation_graph/plugin.py`, `autocapture_nx/processing/sst/*`
- **Description**: Add reusable extractors for details KV forms, calendar rows, Slack messages, color-coded console lines, browser chrome, and button grounding boxes.
- **Complexity**: 8
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Extracted records support Q5-Q10 + H8-H10 without question-specific logic.
- **Validation**:
  - Per-domain fixture tests with strict expected outputs.

### Task 3.4: Producer metadata propagation for attribution
- **Location**: `autocapture_nx/kernel/derived_records.py`, `autocapture_nx/processing/sst/*`, `plugins/builtin/observation_graph/plugin.py`
- **Description**: Persist producer plugin id/stage metadata on all derived records to enable true stage-level attribution later.
- **Complexity**: 7
- **Dependencies**: Task 3.3
- **Acceptance Criteria**:
  - Every derived record consumed by query path includes producer metadata.
- **Validation**:
  - Record schema tests confirm producer fields exist and are stable.

### Task 3.5: OCR as support channel, not sole answer path
- **Location**: `autocapture_nx/kernel/query.py`, extractor modules
- **Description**: Keep OCR in fusion, but require structured observation grounding for final claims when available.
- **Complexity**: 7
- **Dependencies**: Task 3.4
- **Acceptance Criteria**:
  - Final answers reference structured records; OCR-only fallback marked low-confidence/indeterminate.
- **Validation**:
  - Policy tests for VLM-grounded questions.

## Sprint 4: Query Reasoner Refactor (No Keyword Routing)
**Goal**: Remove tactical query-topic hardcoding as primary logic.
**Demo/Validation**:
- Same answer from paraphrased question variants.

### Task 4.1: Replace `_query_topic` hard branches with intent + schema matching
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/kernel/query_intent.py` (new)
- **Description**: Build intent classifier + capability resolver over available structured records.
- **Complexity**: 8
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Hard-coded question-string triggers removed from primary pipeline.
- **Validation**:
  - Paraphrase regression tests per Q/H item.

### Task 4.2: Keyword-shortcut audit and migration
- **Location**: `autocapture_nx/kernel/query.py`, `tools/`, extractors and query helpers
- **Description**: Repo-wide scan for keyword-triggered shortcuts and migrate any remaining logic to intent/capability resolution.
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - No production answer path depends on literal question-string matching.
- **Validation**:
  - Static scan + dynamic tests using paraphrases/word-order variants.

### Task 4.3: Multi-path reasoning arbitration
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/kernel/query_paths.py` (new)
- **Description**: Score candidate answers across paths (state/retrieval/observation) using evidence quality, consistency, and coverage.
- **Complexity**: 8
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Winner selection deterministic and explainable.
- **Validation**:
  - Tests where previous wrong collaborator answer is rejected.

## Sprint 5: Fine-Grained Plugin Attribution + Metrics
**Goal**: Prove exact plugin contributions and runtime tradeoffs.
**Demo/Validation**:
- Per-question report lists every loaded plugin, whether it contributed, confidence impact, and latency.

### Task 5.1: Attribution model upgrade
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/kernel/derived_records.py`
- **Description**: Attribute by true producer plugin/stage (not only by `record_type` prefix).
- **Complexity**: 7
- **Dependencies**: Sprint 4 (and producer metadata from Task 3.4)
- **Acceptance Criteria**:
  - `providers[]` includes stage-level plugin ids with contribution basis points.
- **Validation**:
  - Golden report contains non-trivial multi-plugin paths.

### Task 5.2: Plugin usefulness scoreboard
- **Location**: `tools/query_effectiveness_report.py`, `tools/generate_qh_plugin_validation_report.py`
- **Description**: Add correctness-weighted contribution, latency cost, and recommendation output (`keep/tune/remove/add`).
- **Complexity**: 6
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - For each plugin: `used`, `helped`, `hurt`, `neutral`, `mean_latency_ms`, `confidence_delta`.
- **Validation**:
  - CSV/JSON exports generated in one command.

### Task 5.3: Confidence calibration + answerability gate
- **Location**: `autocapture_nx/kernel/query.py`, `tools/query_eval_suite.py`, `tools/generate_qh_plugin_validation_report.py`
- **Description**: Add per-answer calibrated confidence and explicit `answerable` state (`answerable`, `indeterminate`, `uncitable`) with deterministic thresholds.
- **Complexity**: 6
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Every Q/H result includes confidence score, confidence label, and answerability state.
  - Fail strict eval if answer marked `answerable` but incorrect, or `indeterminate` when required evidence exists.
- **Validation**:
  - Calibration tests on historical Q/H artifacts and confusion-matrix export.

### Task 5.4: Workflow tree artifact per run
- **Location**: `tools/export_run_workflow_tree.py`, `docs/reports/`
- **Description**: Emit Mermaid + table view linking answer -> path -> plugins -> records -> citations.
- **Complexity**: 4
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Tree includes all loaded plugins and marks path inclusion/exclusion.
- **Validation**:
  - Snapshot test for expected node/edge schema.

### Task 5.5: Full plugin execution inventory report
- **Location**: `tools/generate_qh_plugin_validation_report.py`, `tools/query_effectiveness_report.py`
- **Description**: Emit exhaustive plugin table for each run: loaded, failed, skipped, in-path, out-of-path, contribution to each answer id.
- **Complexity**: 4
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Report includes all configured plugins, not only providers that appear in citations.
  - For each plugin: status plus explicit question ids influenced.
- **Validation**:
  - Automated check that inventory count matches discovered plugin manifests or configured required plugin list.

## Sprint 6: Performance + Resource Optimization (4 Pillars)
**Goal**: Maximize GPU utilization and throughput while preserving deterministic quality.
**Demo/Validation**:
- GPU-utilized run shows reduced latency with equal or better strict accuracy.

### Task 6.1: GPU-first extraction scheduling
- **Location**: `autocapture_nx/processing/idle.py`, `autocapture_nx/processing/sst/pipeline.py`
- **Description**: Batch VLM ROI tasks, parallelize safe independent stages, and reduce serial bottlenecks.
- **Complexity**: 7
- **Dependencies**: Sprint 5
- **Acceptance Criteria**:
  - Improved p95 question latency without strict-score regression.
- **Validation**:
  - Perf gate compares baseline vs optimized run.

### Task 6.2: Budget + safety enforcement alignment
- **Location**: runtime governor/scheduler configs and tests
- **Description**: Ensure idle budget constraints remain enforced while allowing GPU saturation.
- **Complexity**: 5
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - CPU/RAM budget checks pass under soak load.
- **Validation**:
  - Resource budget tests and soak report.

## Q/H Closure Matrix (Target State)
| ID | Required State | Pass Criterion |
| --- | --- | --- |
| Q1-Q10 | strict evaluated | exact/structured checks pass |
| H1-H10 | strict evaluated | all acceptance constraints pass |
| Overall | 20/20 strict pass | no `no_evidence` on answerable items; uncitable items explicitly marked |

## Testing Strategy
- Unit: extractor validators, intent routing, attribution mapping, scorer.
- Integration: full single-image golden run with strict Q/H suite.
- Determinism: rerun same image/config 3x; identical strict outcomes and bounded confidence drift.
- Regression: block merge when strict pass rate <100% for golden set.

## Potential Risks & Gotchas
- Overfitting to one screenshot; mitigate with paraphrase variants and perturbation fixtures.
- Attribution inflation; mitigate by requiring citation-linked producer ids.
- VLM variability; mitigate with constrained JSON schema + deterministic decode settings.
- Plugin lock drift; mitigate with preflight lock verification.
- Required-plugin hard gate can fail on transient startup issues; mitigate with bounded preflight retries before fail-closed.
- Attribution/metrics instrumentation can increase latency; mitigate via async/sampled exports and perf gating in Sprint 6.
- Security drift; enforce localhost-only and PolicyGate checks in CI.

## Rollback Plan
- Keep current query path behind feature flag while new reasoner stabilizes.
- Allow staged rollout: strict eval and attribution first, then reasoning migration.
- Preserve old reports for before/after comparability.

## Execution Order (Do Not Reorder)
1. Sprint 1 (strict eval)
2. Sprint 2 (plugin fail-closed)
3. Sprint 3 (generic extraction)
4. Sprint 4 (reasoner refactor)
5. Sprint 5 (attribution/metrics)
6. Sprint 6 (performance)
