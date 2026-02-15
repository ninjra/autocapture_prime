# Plan: Screenshot Query Complete Coverage

**Generated**: 2026-02-05  
**Estimated Complexity**: High

## Overview
The current pipeline generates OCR/VLM artifacts, but the query path only uses a subset (state-layer snippets). This causes legitimate metadata (for example `derived.sst.text.extra`) to be ignored during answering. The plan below makes *all derived artifacts* queryable, builds an orchestrated batch processor for OCR/VLM (idle-only processing, GPU-parallel batches), and adds time‑series support for multi‑frame queries. The goal is: **any natural‑language query must be answerable from media‑derived metadata alone** (single screenshot or video frames), without special-casing by media type.

## Prerequisites
- Working fixture run pipeline (`tools/run_fixture_stepwise.py`)
- SQLCipher + OCR dependencies available in `.venv`
- GPU access in WSL for batch OCR/VLM
- Capture plugins run only when user is active; all processing runs only when idle
- FFmpeg available for video-to-frame decomposition (when video inputs are used)
- Audio extraction is **out of scope** for now (visual-only processing)

## Sprint 1: Evidence Inventory + Universal Index
**Goal**: Enumerate all derived artifacts and make them searchable.
**Demo/Validation**:
- Run stepwise fixture.
- Confirm every `record_type` is cataloged.
- Confirm queries can retrieve from `derived.sst.text.extra`.

### Task 1.1: Evidence Catalog
- **Location**: `autocapture_nx/state_layer/evidence_catalog.py` (new), `tools/run_fixture_stepwise.py`
- **Description**: Create a catalog that enumerates every metadata record type and maps it to queryable text (raw + normalized), with source record IDs and payload hashes.
- **Complexity**: 6
- **Dependencies**: None
- **Acceptance Criteria**:
  - Catalog includes `derived.sst.text`, `derived.sst.text.extra`, `derived.sst.state` tokens, VLM outputs, UI parse outputs.
  - Stepwise report includes catalog summary and counts.
- **Validation**:
  - Inspect `stepwise_report.json` for catalog entries.

### Task 1.2: Universal Text Index
- **Location**: `autocapture_nx/state_layer/retrieval.py`, `autocapture_nx/kernel/query.py`
- **Description**: Add a universal text index (lexical + vector) over cataloged artifacts, not just state spans.
- **Complexity**: 7
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Query hits can come from any derived text artifact.
  - Results include citations to the source record ID + payload hash.
- **Validation**:
  - Query returns citations sourced from `derived.sst.text.extra`.

## Sprint 2: Media-Agnostic Decomposition + Batch Orchestrator
**Goal**: Treat screenshots and videos identically by decomposing all media into frames and batching OCR/VLM over the full frame set.
**Demo/Validation**:
- Batch execution report produced per run.
- GPU/CPU budget respected; deterministic outputs across reruns.
- Video inputs produce the same derived artifacts as screenshots.

### Task 2.1: Media Decomposition Layer
- **Location**: `autocapture_nx/capture/pipeline.py`, `autocapture_nx/processing/idle.py`
- **Description**: Normalize inputs (single screenshot or video) into a unified frame stream with stable IDs, timestamps, and provenance.
- **Complexity**: 7
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Screenshots and videos both produce `evidence.capture.frame` and `derived.sst.*`.
  - Frame IDs are stable and usable for time‑series queries.
- **Validation**:
  - Run fixture with 1+ screenshots and confirm consistent artifact types.

### Task 2.2: Batch Orchestrator
- **Location**: `autocapture_nx/processing/batch_orchestrator.py` (new), `autocapture_nx/processing/idle.py`
- **Description**: Implement a batch scheduler that groups artifacts by model/plugin, executes in resource‑aware batches, and records batch metadata in the ledger. Processing runs only during idle; capture-only when active.
- **Complexity**: 8
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - OCR/VLM runs are batched and logged.
  - All available OCR/VLM providers run in batch (no filtering).
  - GPU is utilized when available; CPU/RAM limits enforced.
- **Validation**:
  - Stepwise run shows batch logs and per‑provider outputs.

### Task 2.3: Artifact Normalization
- **Location**: `autocapture_nx/processing/sst/persist.py`, new helpers
- **Description**: Normalize all OCR/VLM outputs into consistent text artifacts with provenance and hashes.
- **Complexity**: 5
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - All outputs have `record_type`, `payload_hash`, and `provenance`.
- **Validation**:
  - Catalog (Sprint 1) captures normalized artifacts.

## Sprint 3: Semantic Queries Without Special-Case Plugins
**Goal**: Answer semantic questions (song playing, etc.) using only full‑coverage metadata and the universal index.
**Demo/Validation**:
- Query “what song is playing” returns a cited answer if visible in screenshot.

### Task 3.1: Universal Evidence Ranking
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/state_layer/retrieval.py`
- **Description**: Expand retrieval scoring to rank derived OCR/VLM outputs relevant to semantic queries without a dedicated media plugin.
- **Complexity**: 6
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - “song playing” matches visible song/title text when present.
- **Validation**:
  - Fixture query returns cited result from derived OCR/VLM text.

### Task 3.2: Answer Composition Rules
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Compose answers from top-ranked text spans and ensure citations reference originating artifacts.
- **Complexity**: 5
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Answer cites exact derived artifact IDs and hashes.
- **Validation**:
  - Query produces an answer with validated citations.

## Sprint 4: Time‑Series + Regression Tests
**Goal**: Support temporal queries across multiple frames and lock in reliability.
**Demo/Validation**:
- Query “what did it say before we changed it” returns cited answer when multiple frames present.

### Task 4.1: Frame Timeline Builder
- **Location**: `autocapture_nx/processing/sst/temporal_*`, `autocapture_nx/state_layer/*`
- **Description**: Build a time‑series index over frames and derived artifacts.
- **Complexity**: 7
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Timeline index created for multi‑frame runs.
- **Validation**:
  - Query over multiple frames returns earlier values.

### Task 4.2: Deterministic Tests
- **Location**: `tests/test_query.py`, `tests/test_query_citations_required.py`
- **Description**: Add screenshot fixtures with known “song” and “variable change” text; assert queries return exact matches with citations.
- **Complexity**: 6
- **Dependencies**: Sprint 4.1
- **Acceptance Criteria**:
  - Tests fail if OCR/VLM artifacts are missing or not indexed.
- **Validation**:
  - Full test suite passes in `MOD-021`.

## Testing Strategy
- Run `tools/run_fixture_stepwise.py` after each sprint.
- Validate `queries.failures == 0` and that answers cite the correct records.
- Add golden queries for “song playing” and “variable before change.”

## Potential Risks & Gotchas
- OCR/VLM noise may still obscure text; mitigation is multiple providers + merged normalization + token voting.
- Full “all plugin” execution may be expensive; batching must enforce CPU/RAM limits.
- Cross‑process capabilities must remain accessible to evidence compiler and query.
- Universal index must remain deterministic and citeable.
- Persisting all derived artifacts increases storage; we’ll keep raw-first locally and avoid pruning per policy.

## Rollback Plan
- Feature‑flag universal index and media extraction.
- Retain state‑layer retrieval as fallback.
- Preserve stepwise artifacts for regression comparison.
