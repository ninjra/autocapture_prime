# Plan: Golden Workflow Plugin Attribution And Reasoning

**Generated**: 2026-02-11  
**Estimated Complexity**: High

## Overview
Replace narrow answer generation with a workflow-first architecture where answers are produced by a multi-stage reasoning pipeline over persisted extracted data, and every final claim includes a verifiable plugin contribution path.  
Primary outcomes:
- `builtin.sst.qa.answers` is no longer the dominant answer source.
- Multiple plugin sequences compete and are scored against golden truth.
- A run-level tree diagram shows exact plugin inputs, outputs, and answer contribution for a sample screenshot.

## Prerequisites
- Sidecar capture/ingest already writing Mode-B compatible artifacts.
- Working fixture run path (single screenshot) under `artifacts/single_image_runs/`.
- `.venv` with project dependencies.
- Localhost-only policy maintained for all services.
- Existing golden cases in `docs/query_eval_cases.json` as starting seed.

## Sprint 1: Truth Harness And Attribution Foundation
**Goal**: Build the ground-truth + telemetry base needed to evaluate plugin sequences.
**Demo/Validation**:
- A single command runs fixture processing and emits:
  - query answers,
  - per-query plugin-sequence attribution,
  - correctness scores by sequence.

### Task 1.1: Define canonical golden set (first 10 questions)
- **Location**: `docs/query_eval_cases.json`, `docs/query_eval_cases_extra.json` (new)
- **Description**: Expand from current 4 questions to 10 with strict expected outputs and citation requirements.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Each case has exact expectation and pass/fail reason fields.
  - Cases cover collaborator ambiguity, time extraction, inbox counting, song, and temporal reasoning.
- **Validation**:
  - `tools/query_eval_suite.py --cases ...` returns deterministic pass/fail rows.

### Task 1.2: Add per-answer attribution schema
- **Location**: `autocapture_nx/kernel/query.py`, `contracts/schemas/` (new JSON schema)
- **Description**: Introduce canonical attribution payload:
  - `candidate_id`,
  - `path_id`,
  - `plugin_sequence[]`,
  - `input_record_ids[]`,
  - `output_record_ids[]`,
  - `selected:boolean`,
  - `score_components`.
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Every query response contains attribution for all considered paths, not only winner.
  - At least one selected path has citations resolving to persisted records.
- **Validation**:
  - New tests in `tests/test_query_attribution.py` (new).

### Task 1.3: Add query-eval correctness-by-path metrics
- **Location**: `tools/query_eval_suite.py`, `autocapture_nx/storage/facts_ndjson.py`
- **Description**: Log per-path correctness metrics:
  - `path_id`,
  - `plugin_sequence_hash`,
  - `correct:boolean`,
  - `coverage_bp`,
  - `citation_count`.
- **Complexity**: 5
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Eval output includes winner and all competing paths with correctness labels.
  - Metrics are append-only.
- **Validation**:
  - New tests in `tests/test_query_eval_path_metrics.py` (new).

## Sprint 2: Observation Graph Plugin (Generalized Extraction)
**Goal**: Replace question-specific heuristics with typed observation extraction.
**Demo/Validation**:
- New plugin emits normalized entities/events/relations from OCR+VLM+SST artifacts.
- Query path can answer core questions without `sst.qa.answers` dominance.

### Task 2.1: Implement observation graph plugin
- **Location**: `plugins/builtin/observation_graph/plugin.py` (new), `plugins/builtin/observation_graph/plugin.json` (new)
- **Description**: Build typed records:
  - `derived.obs.entity`,
  - `derived.obs.event`,
  - `derived.obs.relation`,
  - `derived.obs.temporal_link`.
- **Complexity**: 9
- **Dependencies**: Sprint 1 complete
- **Acceptance Criteria**:
  - Records contain role/context/time fields and provenance back to source records.
  - Supports partial names/initials (`Nikki M`) without collapsing to contractor fallbacks.
- **Validation**:
  - New tests `tests/test_observation_graph_extraction.py` (new).

### Task 2.2: Demote `builtin.sst.qa.answers` to optional feature plugin
- **Location**: `config/default.json`, `autocapture_nx/kernel/query.py`
- **Description**: Keep plugin for backward compatibility but remove it as default primary answer source.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Default answer path chooses observation graph + retrieval orchestration first.
  - If `sst.qa.answers` contributes, it is clearly flagged as one candidate path.
- **Validation**:
  - Integration test proving correct answer with `sst.qa.answers` disabled.

### Task 2.3: Persist explicit role labels for ambiguous people
- **Location**: `plugins/builtin/observation_graph/plugin.py` (new), `contracts/`
- **Description**: Add role model:
  - `message_author`,
  - `message_mention`,
  - `task_assignee`,
  - `contractor`,
  - `requestor`.
- **Complexity**: 7
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - “who is working with me on the flagged quorum message” selects `message_*` role over `contractor`.
- **Validation**:
  - Golden case for `Nikki M` passes with explicit role trace.

## Sprint 3: Multi-Path Reasoning Orchestrator
**Goal**: Execute multiple reasoning paths and pick winner by evidence quality and golden-calibrated scoring.
**Demo/Validation**:
- Query outputs include competing paths and winner.
- Winner not hardcoded to one plugin family.

### Task 3.1: Implement path orchestrator
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/kernel/query_paths.py` (new)
- **Description**: Build path runners:
  - `path.obs_graph_temporal`,
  - `path.state_retrieval`,
  - `path.vector_retrieval`,
  - `path.synth_reasoner` (if enabled).
- **Complexity**: 8
- **Dependencies**: Sprint 2 complete
- **Acceptance Criteria**:
  - Each path returns structured candidate claims + citations + path telemetry.
  - Orchestrator produces deterministic winner selection.
- **Validation**:
  - `tests/test_query_path_orchestrator.py` (new).

### Task 3.2: Add calibrated scoring model for selection
- **Location**: `autocapture_nx/kernel/query_scoring.py` (new)
- **Description**: Score by:
  - citation validity,
  - role-context alignment,
  - temporal consistency,
  - claim precision (no OCR dump leakage),
  - golden historical success for similar query type.
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Wrong collaborator fallback (`Ricardo Lopez`) is ranked below true message collaborator path.
- **Validation**:
  - New tests for path-ranking failure cases.

### Task 3.3: Enforce concise answer rendering from selected structured path
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Render summary from winner path schema only, no raw OCR claim flooding.
- **Complexity**: 4
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Output format remains concise, auditable, and consistent across queries.
- **Validation**:
  - Snapshot tests in `tests/test_query_output_format.py` (new).

## Sprint 4: JEPA And State Path Integration Proof
**Goal**: Ensure JEPA/state plugins are actually loaded, used, and measured.
**Demo/Validation**:
- Run report and attribution show JEPA/state contribution where applicable.

### Task 4.1: Make expected reasoning plugins explicit and fail-closed when missing
- **Location**: `tools/process_single_screenshot.py`, `autocapture_nx/kernel/loader.py`
- **Description**: Add expected plugin assertion list for golden runs (configurable), including JEPA/state modules.
- **Complexity**: 6
- **Dependencies**: Sprint 3 complete
- **Acceptance Criteria**:
  - Golden run fails with clear error if expected plugin is enabled but not loaded.
- **Validation**:
  - `tests/test_expected_plugin_presence.py` (new).

### Task 4.2: Add JEPA/state contribution metrics
- **Location**: `autocapture_nx/kernel/query.py`, `tools/query_eval_suite.py`
- **Description**: Track if JEPA/state path produced winning claim, supporting claim, or no useful signal.
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Metrics include per-query contribution matrix by path.
- **Validation**:
  - `tests/test_query_jepa_contribution_metrics.py` (new).

## Sprint 5: Workflow Tree Diagram And Operator Reporting
**Goal**: Produce tree diagram for one run showing full plugin workflow and answer contribution.
**Demo/Validation**:
- A markdown report contains a tree diagram for the sample screenshot and per-question winning path.

### Task 5.1: Build run graph exporter
- **Location**: `tools/export_run_workflow_tree.py` (new)
- **Description**: Export plugin DAG/tree from metadata + query attribution:
  - node: plugin/path/record,
  - edge: `derived_from`, `selected_by`, `cites`.
- **Complexity**: 6
- **Dependencies**: Sprint 4 complete
- **Acceptance Criteria**:
  - Exports JSON and Mermaid tree for one run ID.
- **Validation**:
  - Unit test `tests/test_run_workflow_tree_export.py` (new).

### Task 5.2: Generate sample tree report for current fixture
- **Location**: `docs/reports/sample-screenshot-workflow-tree.md` (new)
- **Description**: Include tree diagram + per-answer plugin contribution breakdown + correctness table.
- **Complexity**: 3
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Report is human-readable and directly maps answers to plugin sequences.
- **Validation**:
  - Manual review + automated check that all cited record IDs resolve.

## Testing Strategy
- Deterministic unit tests for extraction, role labeling, path scoring, and output rendering.
- Integration tests over fixture screenshot with and without `builtin.sst.qa.answers`.
- Golden harness checks exact expected answers for first 10 questions.
- Attribution integrity tests: every displayed claim must resolve to persisted record chain.
- Policy checks:
  - citations required by default,
  - no query-time raw media dependency,
  - localhost-only behavior unchanged.

## Potential Risks & Gotchas
- Overfitting to one screenshot: mitigate via role/context abstraction and adversarial fixtures.
- Plugin load drift: expected-plugin assertions in golden runs.
- False precision from OCR noise: typed role/context scoring must outrank raw lexical overlap.
- JEPA availability variability: provide explicit “loaded + contributed + won/lost” metrics.
- Performance overhead from multi-path orchestration: cap candidate count and keep async path time budgets.

## Rollback Plan
- Revert new observation graph/orchestrator files and restore previous query arbitration.
- Re-enable prior default plugin precedence if critical regressions occur.
- Keep golden case files and attribution schemas (they remain useful diagnostics).
- Re-run baseline fixture command and previous passing tests before merge.

