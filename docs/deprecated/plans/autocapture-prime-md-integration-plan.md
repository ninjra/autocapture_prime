# Plan: Integrate `docs/autocapture_prime.md` into Implementation

**Generated**: 2026-02-15  
**Estimated Complexity**: High

## Overview
Align the current `autocapture_prime` implementation with the architecture and contract requirements captured in `docs/autocapture_prime.md` and `docs/autocapture_prime_codex_implementation.md`.  
Primary focus: tighten safe defaults, complete two-pass extraction flow, improve temporal linking with input anchors, strengthen retrieval/answer grounding path, and update traceability + matrix artifacts.

## Prerequisites
- Local Python env available at `.venv/bin/python`
- Existing local vLLM endpoint available at `http://127.0.0.1:8000`
- Existing chronicle contract files under `contracts/chronicle/v0/`
- Existing test fixtures in `tests/fixtures/chronicle_spool/`

## Sprint 1: Contract and Safety Alignment
**Goal**: Ensure config/runtime defaults and contract behavior match the document.
**Demo/Validation**:
- `autocapture_prime` starts with localhost-only vLLM policy.
- Config defaults are fail-closed for risky options.
- Contract drift gate remains green.

### Task 1.1: Tighten default config values
- **Location**: `config/autocapture_prime.yaml`, `config/example.autocapture_prime.yaml`, `autocapture_prime/config.py`
- **Description**: Set safe defaults for `privacy.allow_mm_embeds`, AGPL layout gate, and vLLM trust settings while preserving explicit override behavior.
- **Complexity**: 3
- **Dependencies**: None
- **Acceptance Criteria**:
  - Defaults are conservative (false unless explicitly enabled).
  - Existing explicit overrides continue to work.
- **Validation**:
  - `tests/test_autocapture_prime_config_schema.py`

### Task 1.2: Preserve localhost-only runtime enforcement
- **Location**: `services/chronicle_api/app.py`
- **Description**: Keep strict localhost enforcement and add deterministic error handling for non-localhost or unavailable endpoints.
- **Complexity**: 3
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Any non-localhost vLLM URL is rejected.
  - Errors are explicit and testable.
- **Validation**:
  - `tests/test_chronicle_api_chat_completions.py`

## Sprint 2: Two-Pass Extraction and Temporal Linking
**Goal**: Implement doc-aligned extraction quality improvements without hardcoding question-specific heuristics.
**Demo/Validation**:
- Ingestion runs full-frame + ROI OCR pass.
- Temporal linker uses click/input anchors.
- Output rows include provenance needed for deterministic QA.

### Task 2.0: Validate anchor metadata availability
- **Location**: `autocapture_prime/ingest/session_loader.py`, `autocapture_prime/ingest/proto_decode.py`, `tests/fixtures/chronicle_spool/`
- **Description**: Confirm fixture/live spool metadata provides required fields (`qpc_ticks`, pointer coordinates, frame index alignment). Add fixture refresh step if fields are missing.
- **Complexity**: 4
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Loader exposes deterministic click-anchor candidates per frame window.
  - Fixture data shape is documented and covered by tests.
- **Validation**:
  - New fixture contract test for anchor availability.

### Task 2.1: Implement configurable ROI strategy in OCR pipeline
- **Location**: `autocapture_prime/ingest/pipeline.py`, `autocapture_prime/ocr/paddle_engine.py`, `autocapture_prime/config.py`
- **Description**: Add deterministic ROI generation (`none`, `dirty_rects`, `heuristic_tabs`, `click_anchored`) and run mixed full-frame + ROI OCR.
: Mode contract:
: `none` = only full-frame ROI.
: `dirty_rects` = merge + clamp dirty rects from frame metadata.
: `heuristic_tabs` = top strip band(s) + window chrome candidate bands.
: `click_anchored` = fixed-size ROI centered on click points snapped to desktop bounds.
: Priority order when multiple modes are enabled by config: `dirty_rects` -> `click_anchored` -> `heuristic_tabs`, with deterministic dedup by `(x,y,w,h)` and sorted ordering.
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - OCR pass supports both full-frame and ROIs from session metadata/input.
  - ROI output maps back to desktop coordinates.
- **Validation**:
  - `tests/test_chronicle_ingest_pipeline.py`
  - New unit tests for ROI generation and coordinate remap

### Task 2.2: Integrate input-anchor-aware temporal linking
- **Location**: `autocapture_prime/ingest/pipeline.py`, `autocapture_prime/link/temporal_linker.py`
- **Description**: Parse mouse/click events by frame-time and pass anchor map to linker; keep deterministic tie-breaks.
: Anchor map contract: `dict[int, tuple[int,int]]` keyed by `frame_index`, values in desktop-pixel coordinates. Matching rule: nearest event by `qpc_ticks` within bounded window; tie-break by lower absolute delta then lower `event_index`.
- **Complexity**: 5
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Linker receives `click_points` when input is present.
  - No crash when input is missing.
- **Validation**:
  - `tests/test_chronicle_ingest_pipeline.py`
  - `tests/test_temporal_linker.py`

### Task 2.3: Add per-row provenance markers
- **Location**: `autocapture_prime/ingest/pipeline.py`
- **Description**: Add extraction source/provenance tags to OCR/elements/tracks rows for downstream plugin attribution.
- **Complexity**: 4
- **Dependencies**: Task 2.1, Task 2.2
- **Acceptance Criteria**:
  - Rows include engine + pass metadata (full/roi + strategy).
  - Attribution can be surfaced in query metrics.
- **Validation**:
  - New tests for row metadata shape.

## Sprint 3: Retrieval/Answer Path and Metrics
**Goal**: Improve chronicle query quality and expose deterministic plugin-path evidence.
**Demo/Validation**:
- Queries retrieve evidence with stable ordering and provenance.
- Metrics log plugin contributions and confidence.

### Task 3.1: Strengthen retrieval ordering and evidence packaging
- **Location**: `services/chronicle_api/app.py`, `autocapture_prime/store/index.py`
- **Description**: Add deterministic ranking tie-breaks and richer evidence payload while retaining top-k behavior.
: Evidence payload contract:
: `session_id`, `frame_index`, `source_table`, `extractor`, `text`, `score`, `rank`.
- Deterministic sort: `score desc`, then `session_id`, then `frame_index`, then row ordinal.
- **Complexity**: 5
- **Dependencies**: Sprint 2 complete
- **Acceptance Criteria**:
  - Evidence set is deterministic for repeated runs.
  - API response includes chronicle usage metadata.
- **Validation**:
  - `tests/test_chronicle_api_chat_completions.py`

### Task 3.2: Add query metrics for contribution analysis
- **Location**: `autocapture_prime/eval/metrics.py`, `tools/query_feedback.py`, `tools/run_advanced10_queries.py`
- **Description**: Record which extraction/retrieval paths contributed to answers and whether user feedback marks pass/fail.
: Metric fields:
: `query_sha256`, `run_id`, `plugin_path`, `retrieval_count`, `evidence_order_hash`, `confidence`, `feedback_state`.
- **Complexity**: 6
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Metrics include query hash, plugin path, confidence, and feedback outcome.
  - No synthetic “pass” is recorded without explicit verifier match.
- **Validation**:
  - `tests/test_run_advanced10_expected_eval.py`
  - New tests for feedback semantics

## Sprint 4: Matrix/Docs/Verification
**Goal**: Update implementation matrix and verify remaining gaps are explicit.
**Demo/Validation**:
- Updated matrix maps doc requirement → implementation/test.
- Full targeted test set passes.

### Task 4.1: Update implementation matrix entries for autocapture_prime.md
- **Location**: `docs/reports/implementation_matrix.md`, `docs/reports/autocapture_prime_codex_implementation_matrix.md`
- **Description**: Add explicit rows showing implemented vs pending for each requirement in `docs/autocapture_prime.md`.
- **Complexity**: 4
- **Dependencies**: Sprint 1-3
- **Acceptance Criteria**:
  - Every major requirement has status + file + test reference.
  - Remaining misses are concrete and actionable.
- **Validation**:
  - `tools/run_full_repo_miss_refresh.sh`

### Task 4.2: Regression and determinism run
- **Location**: `tools/run_chronicle_pipeline.sh`, `tools/run_advanced10_queries.py`
- **Description**: Run ingest + query tests on fixture/sample and confirm stable outputs across repeated runs.
- Add fixture refresh step if updated metadata contract requires new fixture artifacts.
- **Complexity**: 5
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Determinism checks stable.
  - No failing golden cases in configured suite.
- **Validation**:
  - Targeted pytest selection + query harness report

## Testing Strategy
- Unit:
  - ROI generation/normalization, temporal linking, ranking tie-breaks.
- Integration:
  - Chronicle spool ingest fixture with COMPLETE gating.
  - Chronicle API completion flow with mocked vLLM response.
- Regression:
  - Existing eval harnesses (`advanced10`, golden suite) with feedback tracking.
- Determinism:
  - Repeat-run checks for same query and same stored extracted data.

## Potential Risks & Gotchas
- Missing GPU or vLLM availability can block live VLM tests.
  - Mitigation: keep mocked API tests and offline fixture passes.
- OCR fallback noise can overtake structured VLM evidence.
  - Mitigation: preserve source tags and ranking that prefers structured/grounded spans.
- Overly broad heuristics could regress other screenshots.
  - Mitigation: generic ROI + linker logic only; avoid question-specific code.
- Contract drift between repo and sidecar expectations.
  - Mitigation: contract pin gate + explicit update script workflow.
- Fixture drift can hide determinism regressions.
  - Mitigation: pin fixture hashes and record evidence-order hash in query runs.

## Rollback Plan
- Revert changed config defaults and pipeline logic commit-by-commit.
- Disable new ROI/linker behavior via config flags while retaining old flow.
- Keep previous matrix report for diff-based restoration.
