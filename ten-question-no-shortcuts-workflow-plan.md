# Plan: Ten Question No Shortcuts Workflow

**Generated**: 2026-02-11  
**Estimated Complexity**: High

## Overview
Implement a deterministic, citation-grounded workflow that answers the 10 advanced screenshot questions through generic extraction and reasoning plugins, not tactical question-specific shortcuts.

Research baseline (current system, same single screenshot dataset) shows major gaps:
- Q1/Q4/Q5/Q7/Q8/Q9/Q10 return generic OCR/SST dump text.
- Q2 incorrectly returns background color for focus query.
- Q3 incorrectly returns inbox count for incident email query.
- Attribution is often too coarse to prove which plugin sequence is actually useful.

Approach:
1. Define strict structured schemas for all required signal families.
2. Build generic parser plugins for windowing/UI primitives and reusable domain components.
3. Route all query answering through a typed reasoning planner over extracted records only.
4. Add deterministic benchmark + metrics + recommendation gates across these 10 questions.

## Prerequisites
- Existing single-image fixture workflow is functioning:
  - `tools/process_single_screenshot.py`
  - `tools/query_latest_single.sh`
  - `tools/query_eval_suite.py`
- Query trace + attribution output available:
  - `autocapture_nx/kernel/query.py`
  - `tools/query_effectiveness_report.py`
  - `tools/export_run_workflow_tree.py`
- Current schema/lock process:
  - `contracts/lock.json`
  - `config/plugin_locks.json`
- Localhost-only and append-only constraints preserved.

## Sprint 1: Baseline Harness For The 10 Questions
**Goal**: Make these 10 prompts a deterministic benchmark with strict fail conditions and no auto-pass behavior.  
**Demo/Validation**:
- Run one command to execute all 10 questions and produce pass/fail artifacts.
- Every failure includes structured reason and plugin/path attribution.

### Task 1.1: Add canonical 10-question benchmark manifest
- **Location**: `docs/query_eval_cases_advanced_10.json` (new)
- **Description**: Store all 10 prompts with exact/structured expectation rules and citation requirements.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Each case has an id, query text, expected output contract, and fail reason contract.
  - Includes ordering assertions where required (z-order, timeline rows, form order).
- **Validation**:
  - Add manifest validation test in `tests/test_query_eval_cases_advanced.py` (new).

### Task 1.2: Add structured expected-output schema per question class
- **Location**: `contracts/query_expected_output.schema.json` (new), `contracts/lock.json`
- **Description**: Define typed expected outputs:
  - window list with z-order/occlusion/context,
  - focus evidence array,
  - incident email extraction,
  - timeline rows,
  - ordered key-value list,
  - calendar tuple list,
  - chat transcript list + thumbnail description,
  - sectioned dev-note extraction,
  - color-classified log lines,
  - browser window tuples.
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Schema catches missing fields and order mismatches.
- **Validation**:
  - Contract validation tests in `tests/test_query_expected_output_schema.py` (new).

### Task 1.3: Extend eval runner for structured assertions
- **Location**: `tools/query_eval_suite.py`
- **Description**: Add evaluation modes:
  - `exact_string`,
  - `ordered_list`,
  - `kv_ordered`,
  - `tuple_list`,
  - `domain_only`,
  - `hostname_only`.
- **Complexity**: 7
- **Dependencies**: Tasks 1.1, 1.2
- **Acceptance Criteria**:
  - Fails precisely on ordering/type/domain leaks (for example full email address leakage).
- **Validation**:
  - Add tests in `tests/test_query_eval_suite_structured.py` (new).

## Sprint 2: Core Scene Understanding Plugins (Q1/Q2 Foundations)
**Goal**: Extract generic UI scene graph signals reusable beyond these 10 prompts.  
**Demo/Validation**:
- Q1 and Q2 have structured outputs with evidence citations and order confidence.

### Task 2.1: Window scene graph plugin
- **Location**: `plugins/builtin/window_scene_graph/plugin.py` (new), `plugins/builtin/window_scene_graph/plugin.json` (new)
- **Description**: Extract:
  - distinct top-level windows,
  - host-vs-VDI context,
  - occlusion status,
  - front-to-back ordering confidence.
- **Complexity**: 9
- **Dependencies**: Sprint 1 complete
- **Acceptance Criteria**:
  - Emits `derived.ui.window` records with explicit z-order index and occlusion state.
- **Validation**:
  - `tests/test_window_scene_graph_plugin.py` (new).

### Task 2.2: Focus evidence plugin
- **Location**: `plugins/builtin/focus_evidence/plugin.py` (new), `plugins/builtin/focus_evidence/plugin.json` (new)
- **Description**: Extract focused window and at least 2 evidence items with exact text spans.
- **Complexity**: 8
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Output includes evidence text + citation offsets.
  - Rejects focus claims with fewer than 2 evidence items.
- **Validation**:
  - `tests/test_focus_evidence_plugin.py` (new).

### Task 2.3: Scene normalization and ambiguity resolution
- **Location**: `autocapture_nx/kernel/scene_normalizer.py` (new)
- **Description**: Normalize overlapping detections and produce deterministic tie-breaks for z-order/focus.
- **Complexity**: 7
- **Dependencies**: Tasks 2.1, 2.2
- **Acceptance Criteria**:
  - Same screenshot yields stable ordered output across repeated runs.
- **Validation**:
  - Determinism test `tests/test_scene_normalizer_determinism.py` (new).

## Sprint 3: Domain Parser Plugin Set (Q3-Q10 Coverage)
**Goal**: Implement reusable domain parsers, not query-specific hardcoding.  
**Demo/Validation**:
- Each domain parser emits structured records independent of query text.

### Task 3.1: Incident/email parser plugin
- **Location**: `plugins/builtin/incident_mail_parser/plugin.py` (new)
- **Description**: Extract subject, sender display name, sender domain-only, and task-card action labels.
- **Complexity**: 8
- **Dependencies**: Sprint 2 complete
- **Acceptance Criteria**:
  - Domain-only enforcement for sender email.
  - Action button labels captured with order.
- **Validation**:
  - `tests/test_incident_mail_parser.py` (new).

### Task 3.2: Timeline and details parser plugins
- **Location**: `plugins/builtin/record_activity_parser/plugin.py` (new), `plugins/builtin/details_kv_parser/plugin.py` (new)
- **Description**: Extract ordered timeline rows and ordered key-value field lists including empty values.
- **Complexity**: 8
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Row grouping and ordering stable.
  - Empty fields represented as empty string.
- **Validation**:
  - `tests/test_record_activity_parser.py` (new)
  - `tests/test_details_kv_parser.py` (new)

### Task 3.3: Calendar/chat/dev-notes/log/browser parser plugins
- **Location**:
  - `plugins/builtin/calendar_schedule_parser/plugin.py` (new)
  - `plugins/builtin/chat_transcript_parser/plugin.py` (new)
  - `plugins/builtin/doc_section_parser/plugin.py` (new)
  - `plugins/builtin/color_log_parser/plugin.py` (new)
  - `plugins/builtin/browser_chrome_parser/plugin.py` (new)
- **Description**: Emit typed records for Q6-Q10 requirements with strict normalization (hostname-only, color classes, tab counts, ordered messages).
- **Complexity**: 10
- **Dependencies**: Tasks 3.1, 3.2
- **Acceptance Criteria**:
  - All parser outputs carry provenance and confidence.
  - No parser output depends on user query wording.
- **Validation**:
  - New tests per parser module under `tests/`.

## Sprint 4: Query Planner And Reasoner Over Extracted Data
**Goal**: Ensure query answers come from typed extracted records only, with explicit path attribution.  
**Demo/Validation**:
- All 10 queries answer via planner + reasoner path with concise structured responses.

### Task 4.1: Query intent-to-schema planner
- **Location**: `autocapture_nx/kernel/query_planner.py` (new), `autocapture_nx/kernel/query.py`
- **Description**: Map NL queries to required record schemas and constraints (order, count, domain-only, evidence count).
- **Complexity**: 8
- **Dependencies**: Sprint 3 complete
- **Acceptance Criteria**:
  - Planner chooses schema constraints generically by intent class.
- **Validation**:
  - `tests/test_query_planner_advanced_intents.py` (new).

### Task 4.2: Structured response renderer
- **Location**: `autocapture_nx/kernel/query_renderer.py` (new), `autocapture_nx/kernel/query.py`
- **Description**: Render one-line summary + compact verification bullets + citation IDs from reasoner output.
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Outputs are human-verifiable and machine-checkable against expected schema.
- **Validation**:
  - `tests/test_query_renderer_structured.py` (new).

### Task 4.3: Sequence attribution and handoff trace hardening
- **Location**: `autocapture_nx/kernel/query.py`, `tools/export_run_workflow_tree.py`
- **Description**: Capture exact plugin sequence contributions and export run tree for each query.
- **Complexity**: 5
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Each answer includes winner path + competing path metadata.
- **Validation**:
  - Extend `tests/test_export_run_workflow_tree.py`.

## Sprint 5: Metrics, Feedback Loop, And Recommendation Engine
**Goal**: Track correctness and plugin value for iterative improvement without answer substitution.  
**Demo/Validation**:
- Metrics report shows per-plugin correctness contribution, latency, and recommendation rules.

### Task 5.1: Advanced benchmark runner
- **Location**: `tools/run_query_benchmark_advanced.sh` (new), `tools/query_eval_suite.py`
- **Description**: One-command execution for all 10 advanced queries and structured assertions.
- **Complexity**: 5
- **Dependencies**: Sprint 4 complete
- **Acceptance Criteria**:
  - Emits pass/fail JSON, per-query artifacts, and summary markdown.
- **Validation**:
  - Integration test `tests/test_run_query_benchmark_advanced.py` (new).

### Task 5.2: Effectiveness metrics by plugin sequence
- **Location**: `tools/query_effectiveness_report.py`
- **Description**: Add accuracy/latency metrics for parser families and reasoning paths across the 10-question benchmark.
- **Complexity**: 6
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Report shows winner frequency, correctness, and p50/p95 latency per sequence.
- **Validation**:
  - Extend `tests/test_query_effectiveness_report.py`.

### Task 5.3: Deterministic recommendation rules
- **Location**: `docs/spec/plugin_recommendation_rules.md` (new), `tools/query_effectiveness_report.py`
- **Description**: Recommend new parser/plugin classes when repeated failure clusters appear; flag low-value expensive plugins.
- **Complexity**: 6
- **Dependencies**: Task 5.2
- **Acceptance Criteria**:
  - Recommendations are threshold-based and evidence-backed.
- **Validation**:
  - `tests/test_plugin_recommendation_rules.py` (new).

## Sprint 6: Operational Gates And Documentation
**Goal**: Make this maintainable and regression-resistant under ongoing changes.  
**Demo/Validation**:
- CI/local gates fail on accuracy, citation, or ordering regressions.

### Task 6.1: Regression gate script
- **Location**: `tools/gate_query_advanced.py` (new)
- **Description**: Fail if advanced benchmark drops below configured thresholds (accuracy, citation compliance, ordering stability).
- **Complexity**: 5
- **Dependencies**: Sprint 5 complete
- **Acceptance Criteria**:
  - Deterministic exit codes and actionable fail report.
- **Validation**:
  - `tests/test_gate_query_advanced.py` (new).

### Task 6.2: Workflow docs and operator runbook
- **Location**: `docs/query-advanced-workflow.md` (new)
- **Description**: Document data flow, plugin responsibilities, benchmark command, and interpretation guide.
- **Complexity**: 4
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Includes troubleshooting for common failure clusters per question type.
- **Validation**:
  - Doc lint + manual dry run.

## Testing Strategy
- Unit tests for each parser plugin and planner/renderer.
- Integration tests for end-to-end single-image advanced benchmark.
- Determinism tests for ordering-sensitive outputs (windows/timeline/KV lists).
- Security tests for domain-only/hostname-only sanitization expectations.
- Metrics validation tests ensuring no answer substitution from feedback.

## Potential Risks & Gotchas
- OCR noise in dense UI can destabilize row/field grouping.
  - Mitigation: geometry + anchor-based grouping and confidence thresholds.
- Overlapping windows can cause unstable z-order inference.
  - Mitigation: compositor-like tie-break rules and deterministic fallback ordering.
- Domain parsers might overfit one screenshot.
  - Mitigation: schema-first extraction and parser tests with synthetic variants.
- Color classification can fail under gamma/scale differences.
  - Mitigation: line-level color sampling with tolerance bands + fallback class.
- Plugin latency growth from many parser passes.
  - Mitigation: staged fan-out and cached intermediate artifacts.

## Rollback Plan
- Keep advanced parser/plugin set behind feature flags while retaining current stable query path.
- Disable newly added parser families individually if they regress accuracy.
- Preserve all evaluation traces and feedback append-only; no deletion.

## Post-Save Gotcha Review And Improvements
- Added explicit structured schema task before parser implementation to prevent ad-hoc outputs.
- Added deterministic ordering tests for all order-sensitive questions.
- Added explicit no-shortcut metrics requirement (feedback remains evaluation-only).
- Added plugin recommendation engine tasks tied to measurable failure clusters.

## Review Note
Subagent review is not available in this environment. This plan includes an internal review checklist through acceptance criteria in Sprint 1/4/5/6 to enforce correctness, attribution quality, and no-shortcut policy.
