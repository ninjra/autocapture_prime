# Plan: Full Query Accuracy From Extracted Metadata

**Generated**: 2026-02-11
**Estimated Complexity**: High

## Overview
Replace tactical QA shortcuts with a durable extraction-first architecture where screenshots are processed once into canonical derived records, and promptops queries are answered only from stored metadata/indexes. Implement answer arbitration across state/classic paths, add strict golden QA checks (including exact expected answers), and validate that inbox/song/VDI-time questions succeed through the same pipeline with citations.

## Prerequisites
- Local repo at 
- Existing fixture screenshot at 
- Working venv: 
- Plugin lock updater: 

## Sprint 1: Remove Tactical Paths
**Goal**: Eliminate OCR-only tactical answer injection and enforce extraction-first flow.
**Demo/Validation**:
-  is no longer produced by the idle OCR shortcut path.
- Queries still operate via promptops + retrieval with citations.

### Task 1.1: Deprecate idle QA shortcut writer
- **Location**: , 
- **Description**: Remove/disable  invocation and stop emitting ad-hoc fixture QA docs from raw OCR text during idle extraction.
- **Complexity**: 5
- **Dependencies**: none
- **Acceptance Criteria**:
  - No new  from idle tactical path.
  - No regression in core OCR/VLM derived text persistence.
- **Validation**:
  - Unit tests touching idle extraction and derived record creation.

### Task 1.2: Surface and document deprecated shortcuts
- **Location**:  (or new report update section)
- **Description**: Record removed tactical paths and rationale.
- **Complexity**: 2
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Explicit list of deprecated shortcut paths and replacements.
- **Validation**:
  - Doc lint/smoke test coverage unchanged.

## Sprint 2: Canonical Observation Extraction
**Goal**: Produce reusable, query-agnostic observation records from SST/state outputs.
**Demo/Validation**:
- Pipeline emits canonical observation docs for clock, collaborator, song, and mailbox/workspace signals.
- Observation extraction uses stored SST/state/OCR/VLM artifacts, not query-time media decode.

### Task 2.1: Refactor stage hook into observation extractor
- **Location**: 
- **Description**: Convert from tactical question-focused logic to canonical observation extraction with structured debug traces and deterministic IDs.
- **Complexity**: 8
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Outputs include canonical observation docs and supporting trace docs.
  - Inboxes count is derived from multi-signal clustering (tab/inbox tokens + mail-client context clusters) and is reproducible.
- **Validation**:
  - Extend  with deterministic assertions.

### Task 2.2: Keep plugin lock integrity valid
- **Location**: , 
- **Description**: Update plugin locks after artifact changes so stage plugin loads in fixture/soak runs.
- **Complexity**: 3
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - No plugin hash mismatch for .
- **Validation**:
  - Plugin load report contains no lock mismatch for updated plugin.

## Sprint 3: Query Arbitration + PromptOps Unified Path
**Goal**: Ensure promptops query interface selects the most grounded answer path (state vs classic) with citations.
**Demo/Validation**:
-  executes both paths when state-layer query is enabled, scores groundedness, and returns best result deterministically.

### Task 3.1: Implement answer arbitration
- **Location**: 
- **Description**: Add deterministic method scoring (citation presence, lexical query alignment, count/time suitability) and choose best result between state and classic pipelines.
- **Complexity**: 7
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - State path no longer masks clearly better classic answers.
  - Arbitration metadata explains winner and scores.
- **Validation**:
  - New/updated tests in  and/or .

### Task 3.2: Keep query metrics append-only and method-aware
- **Location**: , 
- **Description**: Persist chosen method and arbitration info in  without breaking schema consumers.
- **Complexity**: 4
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Metrics contain selected method and remain append-only.
- **Validation**:
  - Existing metric append tests pass; add method/arbitration assertions.

## Sprint 4: Golden Workflow + Exact Answer Regression
**Goal**: Store user-validated Q/A pairs and enforce exact match checks on every update.
**Demo/Validation**:
- Single command runs full screenshot processing + promptops queries + strict golden checks.
- Failing answers are visible with exact mismatch details.

### Task 4.1: Extend query eval case schema for exact answers
- **Location**: , 
- **Description**: Support exact expected answer checks in addition to token-any/all checks, with citation requirements.
- **Complexity**: 5
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Cases can require exact phrase/line (e.g., ).
- **Validation**:
  - Unit tests for exact-match behavior and failure reasons.

### Task 4.2: Persist canonical golden question set
- **Location**: , optionally 
- **Description**: Store validated queries + exact expected outputs for:
  - how many inboxes do i have open
  - what song is playing
  - what time is it on the vdi
- **Complexity**: 3
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Golden cases are executable and versioned in repo.
- **Validation**:
  -  returns pass/fail per case with exact diagnostics.

### Task 4.3: One-line runner for full regression
- **Location**: {"ok": true, "report": "/mnt/d/projects/autocapture_prime/artifacts/single_image_runs/single_20260211T160227Z/report.json"} (or replacement script)
- **Description**: Ensure one short command runs processing + query eval against the golden case file.
- **Complexity**: 2
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - One-line command under terminal width executes full flow.
- **Validation**:
  - Run command on fixture screenshot and confirm summary output.

## Testing Strategy
- Unit tests:
  - 
  - 
  -  / 
- Golden regression:
  - {"ok": true, "report": "/mnt/d/projects/autocapture_prime/artifacts/single_image_runs/single_20260211T160306Z/report.json"}
- Policy checks:
  - Verify citations exist and resolve for matched claims.
  - Ensure no query-time media decode is required for answers.

## Potential Risks & Gotchas
- State-layer retrieval may still return noisy OCR-heavy claims that outscore true answers unless arbitration weights are calibrated.
- Plugin lock mismatch will silently disable new logic; lock update must be part of every plugin edit.
- Fixture text variance (OCR jitter) can break exact answer checks if output phrasing changes; keep canonical answer templates stable.
- Overfitting to one screenshot is a risk; clustering heuristics should rely on generalized positional/context signals and be covered by synthetic tests.

## Rollback Plan
- Revert modified files in:
  - 
  - 
  - 
  - updated tests/case files
- Restore previous plugin lock file from git if lock update introduces load failures.
- Re-run targeted tests and fixture regression to confirm baseline restoration.
