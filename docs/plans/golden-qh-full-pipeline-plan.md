# Plan: Golden QH Full Pipeline Completion

**Generated**: 2026-02-14  
**Estimated Complexity**: High

## Overview
Close all remaining Q/H evaluation gaps using generic pipeline improvements (no question-specific shortcuts).  
Primary blocker class is missing VLM-grounded extraction records (`source_modality=vlm`, `source_state_id=vlm`) when localhost VLM is unavailable or misconfigured.

## Prerequisites
- Local OpenAI-compatible VLM endpoint reachable at `http://127.0.0.1:8000`.
- Golden profile applied (`config/profiles/golden_full.json`).
- Plugin lock hashes up to date (`config/plugin_locks.json`).

## Sprint 1: VLM Reliability and Determinism
**Goal**: Ensure pipeline always binds to a live localhost VLM model when available.
**Demo/Validation**:
- `builtin.vlm.vllm_localhost` loads without hash mismatch.
- Single-image run emits no VLM model-missing errors when endpoint is healthy.

### Task 1.1: Auto-resolve Live VLM Model
- **Location**: `plugins/builtin/vlm_vllm_localhost/plugin.py`
- **Description**: Resolve configured model against `/v1/models`; fallback to served model when stale.
- **Complexity**: 5
- **Dependencies**: none
- **Acceptance Criteria**:
  - Stale model id no longer causes permanent OCR fallback.
  - Model-not-found responses trigger automatic model refresh + retry.
- **Validation**:
  - `tests/test_vlm_vllm_localhost_plugin.py`

### Task 1.2: Lockfile Update for Plugin Integrity
- **Location**: `config/plugin_locks.json`, `tools/hypervisor/scripts/update_plugin_locks.py`
- **Description**: Recompute lock hashes after plugin edits.
- **Complexity**: 2
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Kernel boot does not reject modified VLM plugin with hash mismatch.
- **Validation**:
  - Single-image run boot passes required plugin gate.

## Sprint 2: VLM-Grounded Advanced Observation Emission
**Goal**: Emit advanced records with VLM modality/state so query-layer advanced intents can answer.
**Demo/Validation**:
- `obs.adv.*` rows show `source_modality=vlm` and `source_state_id=vlm`.
- `sst_diagnostics` includes effective VLM signal path.

### Task 2.1: Enforce UI Parse Upgrade Path
- **Location**: `plugins/builtin/processing_sst_vlm_ui/plugin.py`, `plugins/builtin/observation_graph/plugin.py`
- **Description**: Ensure `ui.parse` upgrades pending graph to VLM graph when any valid VLM layout exists.
- **Complexity**: 7
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Advanced docs are not tagged OCR when VLM data is available.
  - No regression for OCR-only fallback when VLM is truly unavailable.
- **Validation**:
  - New/extended tests for stage hook behavior + modality tagging.

### Task 2.2: Golden Profile Hardening
- **Location**: `config/profiles/golden_full.json`, `config/profiles/golden_full.sha256`
- **Description**: Keep VLM settings model-agnostic and hash-locked.
- **Complexity**: 3
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Profile lock test passes.
  - Run config avoids stale model pinning.
- **Validation**:
  - `tests/test_golden_full_profile_lock.py`

## Sprint 3: Query-Layer Generic Normalization and Scoring
**Goal**: Raise failed Q/H classes with generic parsers and stronger evidence fusion.
**Demo/Validation**:
- Strict advanced20 evaluation improves to full pass target.

### Task 3.1: Advanced Field Normalizers
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Improve normalization for timestamps, counts, tab/window hostnames, calendar rows, color-classified lines, action boxes.
- **Complexity**: 8
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - No per-question hardcoded answers.
  - Structured outputs produced from extracted metadata only.
- **Validation**:
  - `tools/run_advanced10_queries.py --strict-all`

### Task 3.2: Timeout/Retry Robustness for Eval Runner
- **Location**: `tools/run_advanced10_queries.py`
- **Description**: Keep deterministic batch execution with lock retries + per-query timeout.
- **Complexity**: 4
- **Dependencies**: none
- **Acceptance Criteria**:
  - No indefinite hangs.
  - Lock contention is retried and surfaced.
- **Validation**:
  - `tests/test_run_advanced10_expected_eval.py`

## Sprint 4: Evidence, Metrics, and Release Gate
**Goal**: Ship with auditable plugin contribution traces and confidence metrics.
**Demo/Validation**:
- Per-question plugin path + confidence available in report artifacts.

### Task 4.1: Plugin Contribution Trace Fidelity
- **Location**: `tools/generate_qh_plugin_validation_report.py`, `tools/query_effectiveness_report.py`
- **Description**: Ensure every answer includes provider chain and confidence fields.
- **Complexity**: 5
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Report shows which plugins participated vs. loaded-only.
- **Validation**:
  - `docs/reports/question-validation-plugin-trace-*.md`

### Task 4.2: Strict Gate and Matrix Refresh
- **Location**: `docs/reports/implementation-matrix.md` (or current matrix doc), `artifacts/advanced10/*.json`
- **Description**: Refresh matrix with implemented/missing-by-blocker status.
- **Complexity**: 3
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Q/H matrix reflects latest strict-all run and confidence.
- **Validation**:
  - `evaluated_passed == evaluated_total` in advanced20 artifact.

## Testing Strategy
- Unit tests for model selection, lock retries, and parsing helpers.
- Single-image golden processing regression run.
- Strict advanced20 eval as final gate.
- Plugin trace generation for citation/provenance inspection.

## Potential Risks & Gotchas
- VLM endpoint instability can cause OCR fallback and false “pipeline failures.”
- Plugin lock mismatches will silently block updated plugins unless lockfile is refreshed.
- OCR fallback may appear accurate for some cases but violates VLM-grounded requirements for advanced intents.

## Rollback Plan
- Revert profile and plugin changes to last passing commit.
- Restore prior `config/plugin_locks.json`.
- Re-run single-image baseline and strict eval to confirm rollback integrity.
