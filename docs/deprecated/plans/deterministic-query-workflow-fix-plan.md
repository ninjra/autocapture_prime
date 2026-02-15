# Plan: Deterministic Query Workflow Fix

**Generated**: 2026-02-11  
**Estimated Complexity**: High

## Overview
Eliminate shortcut behavior and make query answers strictly derived from persisted extracted records produced by the full processing workflow. The target state is:
- No answer substitution from reviewer feedback or manual overrides.
- Generic, deterministic reasoning across OCR, VLM, JEPA/state, and structured extraction outputs.
- Full attribution for every answer path (plugin sequence, citations, timing, handoffs).
- Benchmark-driven iteration where each fix is tied to measurable correctness gains.

This plan addresses all known failures in the current run loop:
- False positives from narrow query-specific aggregation.
- Inability to prove plugin value vs. dead weight.
- Ambiguous collaborator selection in Quorum-like UI contexts.
- Weak operator-facing output formatting for verification.

## Prerequisites
- Existing pipeline and tooling in place:
  - `autocapture_nx/kernel/query.py`
  - `plugins/builtin/observation_graph/plugin.py`
  - `tools/query_latest_single.py`
  - `tools/query_feedback.py`
  - `tools/query_effectiveness_report.py`
  - `tools/export_run_workflow_tree.py`
- Stable single-image fixture run path under `artifacts/single_image_runs/`.
- Local append-only fact storage enabled.
- Plugin lock workflow available (`config/plugin_locks.json`).

## Sprint 1: Integrity And Policy Hardening
**Goal**: Remove all non-deterministic/shortcut answer behavior and enforce strict evidence-only answers.  
**Demo/Validation**:
- Query output never changes due to reviewer feedback records.
- Feedback remains evaluation-only telemetry.
- Tests prove override behavior is gone.

### Task 1.1: Remove Feedback Answer Override Path
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Delete `_feedback_override`, `_apply_feedback_override`, and all runtime code paths that alter answer content from `query_feedback.ndjson`.
- **Complexity**: 5
- **Dependencies**: None
- **Acceptance Criteria**:
  - No query answer text is sourced from reviewer feedback.
  - Query trace only reports feedback linkage as optional eval metadata, never as answer source.
- **Validation**:
  - Update/add tests in `tests/test_query_arbitration.py`.
  - Remove/replace `tests/test_query_feedback_override.py` with a negative assertion test.

### Task 1.2: Enforce Source-Type Guardrails
- **Location**: `autocapture_nx/kernel/query.py`, `contracts/` (new schema/enum file if needed)
- **Description**: Restrict answer claims to approved source classes (`derived.obs.*`, `derived.state.*`, `derived.vlm.*`, `derived.ocr.*`, etc.), and reject evaluator-only records during arbitration.
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - `derived.eval.*` cannot directly back final claims.
  - Violations emit explicit indeterminate state with diagnostics.
- **Validation**:
  - New tests in `tests/test_query_source_class_guards.py`.

### Task 1.3: Add Audit Record For Policy-Critical Query Decisions
- **Location**: `autocapture_nx/kernel/query.py`, append-only facts path
- **Description**: Emit auditable records when claim candidates are rejected by source policy or citation policy.
- **Complexity**: 4
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Every policy rejection produces a structured append-only record with reason code.
- **Validation**:
  - New test `tests/test_query_policy_rejection_audit.py`.

## Sprint 2: Generic Visual Semantics Extraction
**Goal**: Replace tactical per-question logic with reusable structured scene understanding records.  
**Demo/Validation**:
- The same extraction can answer inbox/song/time/collaborator and new unseen UI questions without new hardcoded query branches.

### Task 2.1: Define Canonical UI Semantics Record Model
- **Location**: `contracts/ui_semantics.schema.json` (new), `contracts/lock.json`
- **Description**: Create canonical record types for windows/views/controls/entities:
  - `derived.ui.surface`
  - `derived.ui.window`
  - `derived.ui.application_session`
  - `derived.ui.signal`
  - `derived.ui.relationship`
- **Complexity**: 6
- **Dependencies**: Sprint 1 complete
- **Acceptance Criteria**:
  - Schema supports app identity, session identity, role, state (open/focused/background/taskbar), and provenance links.
- **Validation**:
  - Schema validation tests.

### Task 2.2: Implement UI Semantics Plugin
- **Location**: `plugins/builtin/ui_semantics/plugin.py` (new), `plugins/builtin/ui_semantics/plugin.json` (new)
- **Description**: Build deterministic extraction from OCR tokens + VLM summaries + layout geometry + state signals; produce session-aware records (e.g., separate Gmail tabs, Outlook desktop, Outlook VDI web client).
- **Complexity**: 9
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Records encode explicit per-session evidence, not a single collapsed count.
  - Ambiguous names carry confidence and alternate candidates.
- **Validation**:
  - New tests `tests/test_ui_semantics_plugin.py`.

### Task 2.3: Integrate JEPA/State Features As First-Class Inputs
- **Location**: `plugins/builtin/ui_semantics/plugin.py`, `autocapture_nx/kernel/loader.py`, `config/default.json`
- **Description**: Ensure JEPA/state-derived embeddings and transitions are consumed as structured inputs (not optional comments), with fail-closed behavior when configured-but-missing.
- **Complexity**: 8
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Pipeline exposes JEPA/state contribution fields in generated records.
  - Missing critical inputs cause clear degraded/indeterminate mode, not silent fallback.
- **Validation**:
  - New tests `tests/test_ui_semantics_jepa_state_integration.py`.

## Sprint 3: Multi-Path Query Reasoning Over Persisted Data
**Goal**: Route natural-language queries through deterministic reasoning paths over extracted records only.  
**Demo/Validation**:
- Query command answers from DB/facts without direct image dependence.
- Winning answer includes concise human-readable breakdown and machine-readable path evidence.

### Task 3.1: Build Query Intent-To-Facet Planner
- **Location**: `autocapture_nx/kernel/query_planner.py` (new), `autocapture_nx/kernel/query.py`
- **Description**: Map query intents to facets (actor/time/object/state/relationship) and required evidence classes, avoiding question-specific hardcoding.
- **Complexity**: 7
- **Dependencies**: Sprint 2 complete
- **Acceptance Criteria**:
  - Planner selects evidence facets for known and novel query phrasing.
- **Validation**:
  - New tests `tests/test_query_planner_facets.py`.

### Task 3.2: Implement Deterministic Candidate Graph Builder
- **Location**: `autocapture_nx/kernel/query_graph.py` (new), `autocapture_nx/kernel/query.py`
- **Description**: Build candidate answer graph from persisted records with constraints:
  - citation validity,
  - temporal consistency,
  - role-context compatibility,
  - confidence aggregation.
- **Complexity**: 8
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Candidate graph contains all considered hypotheses and why they were rejected/accepted.
- **Validation**:
  - New tests `tests/test_query_candidate_graph.py`.

### Task 3.3: Upgrade Response Renderer To Verification-Friendly Output
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Standardize short output format:
  - one-line summary,
  - compact bullets for breakdown (e.g., `inboxes: 4 (gmail_1, gmail_2, outlook_vdi, outlook_desktop)`),
  - citation IDs and source plugin/path IDs.
- **Complexity**: 4
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Answers are quickly human-verifiable and machine-auditable.
- **Validation**:
  - Snapshot tests in `tests/test_query_response_format.py`.

## Sprint 4: Effectiveness Metrics, Plugin Attribution, And Recommendations
**Goal**: Quantify which plugins and sequences improve correctness and when new plugins are needed.  
**Demo/Validation**:
- Running a question set yields correctness, latency, handoff, and contribution metrics with recommendations.

### Task 4.1: Extend Query Trace To Full Path Attribution
- **Location**: `autocapture_nx/kernel/query.py`, `tools/query_effectiveness_report.py`
- **Description**: Capture per-query:
  - all candidate paths,
  - winning path,
  - per-plugin contribution weights,
  - stage latency and handoff edges.
- **Complexity**: 7
- **Dependencies**: Sprint 3 complete
- **Acceptance Criteria**:
  - Reports can compute plugin/path value using only trace + feedback facts.
- **Validation**:
  - Extend tests `tests/test_query_trace_fields.py`, `tests/test_query_effectiveness_report.py`.

### Task 4.2: Build Deterministic Plugin Recommendation Engine
- **Location**: `tools/query_effectiveness_report.py`, `docs/spec/plugin_recommendation_rules.md` (new)
- **Description**: Add thresholded rules that recommend:
  - new plugin class for repeated error clusters,
  - plugin retirement/tuning for low-value high-latency paths,
  - missing signal extraction for recurring indeterminate cases.
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Every recommendation has explicit reason codes and metrics.
- **Validation**:
  - New tests `tests/test_plugin_recommendation_rules.py`.

### Task 4.3: Add Workflow Tree Export Per Query Run
- **Location**: `tools/export_run_workflow_tree.py`, `tools/query_tree_latest_single.sh`
- **Description**: Export run-level Mermaid/JSON tree showing plugin DAG and evidence flow into each final claim.
- **Complexity**: 5
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Tree includes plugin nodes, record nodes, and winner/rejected candidate edges.
- **Validation**:
  - Extend `tests/test_export_run_workflow_tree.py`.

## Sprint 5: Golden Benchmark And Regression Gates
**Goal**: Lock in deterministic correctness improvements across the rolling question set.  
**Demo/Validation**:
- Golden round runs report true pass/fail and never auto-pass incorrect answers.

### Task 5.1: Canonical Golden Question Registry (10+)
- **Location**: `docs/query_eval_cases.json`, `docs/query_eval_cases_rolling.json` (new)
- **Description**: Maintain expected answers and normalization rules for the full question set; each case includes rationale and evidence expectations.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Registry supports strict exact/contains/structured matching modes.
- **Validation**:
  - Extend `tests/test_query_eval_suite_exact.py`.

### Task 5.2: Truthful Eval Runner (No Override, No Auto-Pass)
- **Location**: `tools/query_eval_suite.py`, `tools/query_latest_single.py`
- **Description**: Ensure evaluation reflects actual answer text and citations; feedback can annotate but not rewrite results.
- **Complexity**: 5
- **Dependencies**: Sprint 1 Task 1.1
- **Acceptance Criteria**:
  - A wrong answer always remains wrong in reports until workflow logic is fixed.
- **Validation**:
  - New regression tests `tests/test_query_eval_no_override.py`.

### Task 5.3: Add Regression Gate For Correctness + Explainability
- **Location**: `tools/gate_query_effectiveness.py` (new), `tools/run_query_benchmark.sh` (new)
- **Description**: Block regressions when accuracy drops, citation coverage drops, or attribution completeness drops below thresholds.
- **Complexity**: 5
- **Dependencies**: Tasks 5.1, 5.2
- **Acceptance Criteria**:
  - Gate output identifies failing plugin/path with actionable diagnostics.
- **Validation**:
  - Integration test over fixture dataset.

## Testing Strategy
- Deterministic unit tests for planning, extraction, candidate graph scoring, rendering, and guardrails.
- Integration tests for single-image workflow and persisted-data-only query answering.
- Golden benchmark tests for known-answer queries with strict no-override policy.
- Performance checks for per-stage latency and handoff overhead.
- Reliability checks for append-only audit and trace integrity.

## Potential Risks & Gotchas
- OCR/VLM ambiguity in dense UIs may still produce competing entities.
  - Mitigation: explicit alternate-candidate recording with confidence + role context.
- JEPA/state inputs may be unavailable during some runs.
  - Mitigation: fail-closed configuration with explicit degraded-mode diagnostics.
- Attribution payload growth can increase storage/latency.
  - Mitigation: compact normalized trace fields plus optional verbose artifacts.
- Recommendation engine may overfit to small sample counts.
  - Mitigation: minimum sample thresholds and confidence intervals before recommendation.
- Existing tactical logic may hide in older helper paths.
  - Mitigation: mandatory static scan for banned patterns and required tests for no override.

## Rollback Plan
- Keep previous query path behind a feature flag for short-term rollback only.
- Disable new planner/graph components via config if critical regression occurs.
- Preserve all facts/feedback traces append-only; do not delete historical records.

## Post-Save Gotcha Review And Improvements
- Added explicit policy task to remove and ban feedback answer substitution permanently (Sprint 1).
- Added deterministic source-type guardrails to prevent evaluator records from entering final answers.
- Added explicit truthful-eval regression test to prevent false “pass” outcomes.
- Added workflow-tree requirement so plugin contribution is always inspectable.

## Review Note
Subagent review capability is not available in this environment, so this plan includes an explicit self-review checklist (guardrails, truthful eval, deterministic pathing, and attribution completeness) embedded in Sprint 1/4/5 acceptance criteria.
