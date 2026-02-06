# Plan: Screenshot Query Reliability

**Generated**: 2026-02-05
**Estimated Complexity**: High

## Overview
The current screenshot-only pipeline produced OCR/VLM artifacts, but the query path did not reliably use all available derived text to answer semantic questions like “what song is playing.” Root causes include: (1) query flow limited to state-layer hits and short snippets, (2) `derived.sst.text.extra` artifacts are not indexed or queried, (3) OCR tokenization is noisy, and (4) on-query extraction is disabled. This plan expands retrieval to include all derived text artifacts, upgrades evidence compilation to full-text matching, and adds deterministic tests to guarantee queryability for screenshot-only scenarios.

## Prerequisites
- Fixture run artifacts available under `artifacts/fixture_runs/`
- `pysqlcipher3-binary` and OCR deps installed in the venv
- Ability to run `tools/run_fixture_stepwise.py`

## Sprint 1: Evidence Coverage Audit
**Goal**: Identify which derived artifacts are produced and which are queried; add explicit accounting and diagnostics.
**Demo/Validation**:
- Run `tools/run_fixture_stepwise.py`
- Verify report includes counts by record_type and query evidence sources

### Task 1.1: Add derived artifact audit to stepwise report
- **Location**: `tools/run_fixture_stepwise.py`
- **Description**: Summarize counts by `record_type` and include a list of derived text IDs.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - `stepwise_report.json` includes `record_types` and `derived_text_ids`.
- **Validation**:
  - Re-run stepwise fixture and inspect report.

### Task 1.2: Add evidence-source tags to query results
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Track whether claims came from `state.tokens`, `derived.sst.text/state`, or `derived.sst.text.extra`.
- **Complexity**: 5
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Answer payload contains `evidence_sources`.
- **Validation**:
  - Run a query and confirm tags are present.

## Sprint 2: Retrieval Expansion (All Derived Text)
**Goal**: Make the query engine search *all* derived text artifacts, not only state-layer snippets.
**Demo/Validation**:
- Run stepwise fixture.
- Query terms present in `derived.sst.text.extra` and see cited results.

### Task 2.1: Index `derived.sst.text.extra`
- **Location**: `autocapture_nx/state_layer/retrieval.py`, `autocapture_nx/kernel/query.py`
- **Description**: Add a secondary search path over `derived.sst.text.extra` and `derived.sst.text` records.
- **Complexity**: 6
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Queries can return claims sourced from `derived.sst.text.extra`.
- **Validation**:
  - Test query hits derived text and cites the correct record IDs.

### Task 2.2: Evidence compiler fallback to metadata
- **Location**: `autocapture_nx/state_layer/evidence_compiler.py`
- **Description**: Ensure compiler can fetch metadata when running in a subprocess context.
- **Complexity**: 3
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Snippets are non-empty for state-layer hits.
- **Validation**:
  - Run stepwise and verify `extracted_text_snippets` length > 0.

### Task 2.3: Snippet length and matching strategy
- **Location**: `tools/fixture_config_template.json`, `autocapture_nx/ux/fixture.py`
- **Description**: Increase snippet length or change matching mode for queries; support “contains” mode.
- **Complexity**: 3
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Queries match tokens from OCR-derived text.
- **Validation**:
  - Stepwise queries show zero failures.

## Sprint 3: Semantic Answering for Screenshot-Only Questions
**Goal**: Answer semantic questions (“what song is playing”) using only screenshot artifacts.
**Demo/Validation**:
- Ask “what song is playing” and receive cited result if present in OCR/VLM artifacts.

### Task 3.1: Add “Now Playing” detection to state summarizer
- **Location**: `autocapture_nx/processing/sst/extract_*` or `autocapture_nx/processing/sst/build_state`
- **Description**: Extract media-player widgets (song title, artist, service) into a structured record.
- **Complexity**: 7
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Derived record includes `song_title`, `artist`, `service`.
- **Validation**:
  - Run stepwise and confirm derived record stored.

### Task 3.2: Query-time resolver for “song playing”
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/promptops/*`
- **Description**: Add a query intent rule that maps “song playing” to the media-player structured record.
- **Complexity**: 6
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Query returns a claim with citations to the screenshot-derived record.
- **Validation**:
  - Query “what song is playing” returns cited answer when present.

## Sprint 4: Reliability Tests + Benchmarks
**Goal**: Guard against regressions and ensure screenshot-only answers are stable.
**Demo/Validation**:
- New tests pass in `MOD-021`.

### Task 4.1: Add deterministic fixture tests
- **Location**: `tests/test_query.py`, `tests/test_query_citations_required.py`
- **Description**: Use known screenshots where song title is visible and assert query returns it with citations.
- **Complexity**: 5
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Tests fail when OCR/VLM artifacts are missing.
- **Validation**:
  - Run test suite; ensure tests pass.

### Task 4.2: Add coverage map references
- **Location**: `Coverage_Map`, ADRs as needed
- **Description**: Map each requirement to modules/tests for citeability compliance.
- **Complexity**: 3
- **Dependencies**: Sprint 4.1
- **Acceptance Criteria**:
  - Coverage_Map entries updated with new test references.
- **Validation**:
  - Coverage_Map review.

## Testing Strategy
- Run `tools/run_fixture_stepwise.py` after each sprint.
- Add targeted unit tests for evidence compilation and derived record extraction.
- Verify `queries.failures == 0` in stepwise report.

## Potential Risks & Gotchas
- OCR noise may still obscure song titles; requires multi-provider OCR or higher confidence filters.
- Some services render song text as images, requiring VLM-based extraction.
- For subprocess plugins, metadata access needs explicit capability bridging.
- Query intent rules could overfit; ensure fallback to generic search.

## Rollback Plan
- Keep previous query path intact behind a feature flag.
- Revert retrieval changes if query latency or accuracy regresses.
- Preserve stepwise artifacts for regression comparison.
