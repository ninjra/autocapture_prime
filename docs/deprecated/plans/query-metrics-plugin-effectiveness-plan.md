# Plan: Query Metrics And Plugin Effectiveness Tracking

**Generated**: 2026-02-11  
**Estimated Complexity**: High

## Overview
Implement an end-to-end evaluation and observability layer for query runs so each asked question produces chartable evidence for:
- Answer correctness (including user agreement/disagreement and correction).
- Plugin/path contribution and handoff lineage.
- Per-plugin and per-stage latency/cost metrics.
- Automated recommendation signals for missing or low-value plugins.

The plan preserves current non-negotiables:
- Localhost-only operation.
- Raw-first local storage (no local masking/deletion).
- Citation-backed answers with explicit indeterminate states.
- No capture-plugin coupling (queries operate on persisted extracted data).

## Prerequisites
- Existing query pipeline and attribution outputs:
  - `autocapture_nx/kernel/query.py`
  - `tools/query_eval_suite.py`
  - `tools/query_latest_single.sh`
  - `tools/export_run_workflow_tree.py`
- Existing metadata/journal/ledger append-only stores in configured data root.
- Existing plugin lock and policy enforcement:
  - `config/default.json`
  - `config/plugin_locks.json`

## Sprint 1: Query Run Telemetry Foundation
**Goal**: Emit complete per-query execution telemetry with deterministic IDs and traceable handoff spans.
**Demo/Validation**:
- Run a single query and verify a new query-trace record exists with stage/plugin timings and handoff edges.
- Confirm no answer-path regression on existing golden query suite.

### Task 1.1: Define Query Trace Record Schema
- **Location**: `contracts/query_trace.schema.json` (new), `contracts/lock.json`
- **Description**: Define canonical schema for one query execution record:
  - `query_run_id`, `query_sha256`, `ts_utc`
  - stage timings (`retrieve_ms`, `build_claims_ms`, `validate_citations_ms`, `format_display_ms`, total)
  - plugin spans (`provider_id`, `doc_kind`, `claim_count`, `citation_count`, `latency_ms`)
  - handoff edges (`from`, `to`, `count`, `latency_ms`)
  - answer quality fields (`state`, `coverage_bp`, `claim_count`, `citation_count`)
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Schema validates all generated query trace records.
  - Lock updated and verified.
- **Validation**:
  - `python -m unittest` schema validation tests.
  - Contract lock update check.

### Task 1.2: Instrument Query Pipeline Spans
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Add deterministic timing capture and span aggregation around:
  - retrieval/search
  - claim construction
  - citation resolution
  - arbitration/state fallback
  - display formatting
- **Complexity**: 7
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Query output includes `processing.query_trace` block.
  - Trace includes per-provider contribution span rows.
- **Validation**:
  - `tests/test_query_processing_status.py`
  - New test: `tests/test_query_trace_spans.py` (deterministic fields asserted)

### Task 1.3: Persist Append-Only Query Trace Facts
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/storage/facts_ndjson.py`
- **Description**: Append one fact per query to `query_trace.ndjson` with normalized schema and immutable run identifiers.
- **Complexity**: 5
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Each query run writes a valid trace row.
  - Failures still emit a partial trace with error code.
- **Validation**:
  - New test: `tests/test_query_trace_fact_append.py`
  - Manual run with malformed query and validation of error trace.

## Sprint 2: Human Feedback And Ground-Truth Loop
**Goal**: Capture your agreement and corrections for each question and bind feedback to the exact query run.
**Demo/Validation**:
- Ask a question, record `agree/disagree`, include corrected answer text, and verify linked feedback row.
- Verify feedback survives repeated runs and is query-run-addressable.

### Task 2.1: Feedback Record Schema And IDs
- **Location**: `contracts/query_feedback.schema.json` (new), `contracts/lock.json`
- **Description**: Add schema for feedback rows:
  - `query_run_id`, `question_text`, `answer_summary`
  - `user_verdict` (`agree`/`disagree`/`partial`)
  - `correct_answer_text`
  - `confidence_user_bp`
  - `notes`
- **Complexity**: 3
- **Dependencies**: Sprint 1 Task 1.1
- **Acceptance Criteria**:
  - Schema accepted in contract registry.
  - Query feedback records are validated at write-time.
- **Validation**:
  - New tests for schema and validation errors.

### Task 2.2: Add CLI Feedback Command
- **Location**: `autocapture_nx/cli.py`, `autocapture_nx/ux/facade.py`, `tools/query_feedback.py`
- **Description**: Implement a single command to submit feedback against latest or explicit `query_run_id`.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Command writes append-only `query_feedback.ndjson`.
  - Rejects missing query reference and invalid verdict values.
- **Validation**:
  - New tests: `tests/test_query_feedback_cli.py`
  - Manual run with both accepted and rejected payloads.

### Task 2.3: Extend Short Query Runner For Feedback Capture
- **Location**: `tools/query_latest_single.sh`, `tools/query_latest_single_feedback.sh` (new)
- **Description**: Keep one-line query execution command and add optional one-line feedback command that records verdict/correction.
- **Complexity**: 4
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Query command remains short and stable.
  - Feedback command is one-line-compatible and deterministic.
- **Validation**:
  - Script smoke tests in WSL.

## Sprint 3: Plugin Effectiveness Analytics And Recommendations
**Goal**: Produce chartable data and automated “new plugin recommended” signals from run history.
**Demo/Validation**:
- Generate a report across 10 questions showing per-plugin accuracy contribution, latency, and handoff cost.
- Report includes ranked recommendations with explicit evidence criteria.

### Task 3.1: Aggregation Engine For Effectiveness Metrics
- **Location**: `tools/query_effectiveness_report.py` (new)
- **Description**: Aggregate `query_trace.ndjson` + `query_feedback.ndjson` into metrics:
  - plugin path hit rate on correct answers
  - plugin path false-positive association on disagreed answers
  - mean/p95 latency per plugin
  - handoff edge counts and latency
  - contribution-weighted cost-per-correct-answer
- **Complexity**: 8
- **Dependencies**: Sprint 1 + Sprint 2
- **Acceptance Criteria**:
  - Report outputs JSON + CSV suitable for plotting.
  - Deterministic sort order and stable field names.
- **Validation**:
  - New tests: `tests/test_query_effectiveness_report.py`
  - Fixture-based deterministic output test.

### Task 3.2: Recommendation Rules For Missing/Weak Plugins
- **Location**: `tools/query_effectiveness_report.py`, `docs/spec/plugin_recommendation_rules.md` (new)
- **Description**: Add explicit rule engine:
  - Recommend plugin class when repeated disagreement clusters map to missing signal types.
  - Flag low-value plugins when high latency + low correctness gain.
  - Recommend path tuning when handoff latency dominates.
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Recommendation output includes reason code + supporting metrics.
  - No opaque heuristic-only output; each recommendation cites thresholds.
- **Validation**:
  - Rule-level unit tests with synthetic datasets.

### Task 3.3: Workflow Tree + Metrics Bundle Per Query Set
- **Location**: `tools/export_run_workflow_tree.py`, `tools/query_set_bundle.py` (new)
- **Description**: Bundle tree diagrams with per-question metrics for review:
  - per-question markdown tree
  - set-level summary markdown
  - machine-readable JSON bundle
- **Complexity**: 5
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Bundle generated from a list of question runs.
  - Includes both answer text and attribution/timing evidence.
- **Validation**:
  - New tests: `tests/test_query_set_bundle.py`

## Sprint 4: Golden 10-Question Harness And Gates
**Goal**: Turn the 10 known-answer questions into a reproducible benchmark with strict regression visibility.
**Demo/Validation**:
- Run benchmark once and get pass/fail + disagreement diagnostics + plugin recommendations.
- Re-run after a plugin change and compare drift.

### Task 4.1: Define 10-Question Benchmark Manifest
- **Location**: `docs/query_eval_cases_10.json` (new), `docs/query_eval_answers_10.json` (new)
- **Description**: Add canonical question set and expected answers with matching mode (`exact`, `contains`, `equivalent`).
- **Complexity**: 3
- **Dependencies**: None
- **Acceptance Criteria**:
  - Schema-valid cases and expected-answer set.
  - Versioned timestamp and hash.
- **Validation**:
  - New manifest validation tests.

### Task 4.2: Benchmark Runner With Feedback Merge
- **Location**: `tools/run_query_benchmark.sh` (new), `tools/query_eval_suite.py`
- **Description**: Execute all benchmark questions, capture outputs, optionally merge your feedback, compute correctness and plugin metrics.
- **Complexity**: 6
- **Dependencies**: Sprint 2 + Sprint 3
- **Acceptance Criteria**:
  - Single command run.
  - Output includes benchmark summary + recommendation table.
- **Validation**:
  - Integration test with fixture dataset.

### Task 4.3: Add Regression Gates
- **Location**: `tools/gate_phase4.py` (or new `tools/gate_query_effectiveness.py`), CI script wiring
- **Description**: Fail gate when:
  - accuracy drops below configured threshold
  - citation validity regresses
  - latency budget exceeds threshold without correctness gain
- **Complexity**: 5
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Gate exit codes deterministic.
  - Fail outputs identify offending plugin/path.
- **Validation**:
  - Gate unit tests and one integration gate test fixture.

## Testing Strategy
- Unit tests:
  - Trace generation, schema validation, feedback validation, recommendation rules.
- Integration tests:
  - Single-image query run -> trace + feedback + report.
- Golden tests:
  - 10-question benchmark deterministic outputs.
- Determinism checks:
  - Stable IDs/hashes, sorted output, fixed schema versions.
- Performance checks:
  - Per-plugin timing collection overhead bounded and measured.

## Potential Risks & Gotchas
- Attribution ambiguity:
  - Multiple plugins may touch same claim text.
  - Mitigation: tie each citation to exact record/provider and include claim/citation indices.
- Feedback skew:
  - Partial user corrections may be noisy.
  - Mitigation: capture verdict type (`partial`) and confidence field.
- Overhead inflation:
  - Fine-grained timing may increase latency.
  - Mitigation: keep metrics collection lightweight and sampling-configurable if needed.
- Recommendation false positives:
  - Small sample sizes can mislead.
  - Mitigation: minimum sample thresholds and confidence bounds in rule engine.
- Schema drift:
  - New fields may break old consumers.
  - Mitigation: versioned schemas and backward-compatible defaults.

## Rollback Plan
- Disable enhanced trace emission via config flag and retain baseline query output path.
- Revert recommendation output to informational-only mode (no gates).
- Keep feedback ingestion append-only; if schema changes regress, route to quarantine file without deletion.

