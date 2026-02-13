# Plan: Windows Sidecar Capture Interface + Capture Plugin Deprecation

**Generated**: 2026-02-10
**Estimated Complexity**: High

## Overview

Goal:

- Define and publish a stable, exact contract for a Windows sidecar repo to provide capture data for processing by this repo.
- Deprecate (disable-by-default and document as unsupported on WSL) the in-repo capture plugins, keeping the processing/index/query pipeline healthy.

Approach:

- Treat "capture+ingest" as an external responsibility. This repo becomes "processing-only" by default on WSL.
- Standardize the interchange boundary around a portable, integrity-checked artifact (Backup Bundle zip) while still documenting the low-level DataRoot contract.

## Prerequisites

- Agreement on interchange mode:
  - Mode A: backup bundle zip handoff (recommended)
  - Mode B: shared DataRoot directory (risky across NTFS/WSL)
- Agreement on which evidence types are in scope for the sidecar:
  - Minimum: `evidence.capture.frame` (screenshots)
  - Optional: `evidence.window.meta`, input tracking, audio, segments
- A target run cadence (frame interval) and data volume expectations.

## Sprint 1: Publish Sidecar Data Contract
**Goal**: Provide a single authoritative contract doc the sidecar repo can implement.
**Demo/Validation**:
- Confirm `docs/windows-sidecar-capture-interface.md` is complete and unambiguous.
- Review the doc against current implementation invariants:
  - `contracts/evidence.schema.json`
  - `plugins/builtin/journal_basic/plugin.py`
  - `plugins/builtin/ledger_basic/plugin.py`
  - `autocapture_nx/kernel/backup_bundle.py`

### Task 1.1: Document Interchange Modes And Recommend One
- **Location**: `docs/windows-sidecar-capture-interface.md`
- **Description**: Document Mode A (backup bundle) and Mode B (shared DataRoot), including when each is acceptable.
- **Complexity**: 3
- **Dependencies**: None
- **Acceptance Criteria**:
  - Doc contains a clear "recommended mode" and explains why.
  - Doc states the minimum required evidence type(s) for SST processing.
- **Validation**:
  - Manual review.

### Task 1.2: Specify Required On-Disk Formats (Journal/Ledger/Evidence)
- **Location**: `docs/windows-sidecar-capture-interface.md`
- **Description**: Provide exact required fields and hashing rules for:
  - `journal.ndjson` entries
  - `ledger.ndjson` entries (hash chaining)
  - `evidence.capture.frame` records
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Doc references the canonical implementations used for correctness (module paths above).
  - Doc calls out canonical JSON constraints (no floats, NFC normalization).
- **Validation**:
  - Manual spot-check against code.

### Task 1.3: Add A Minimal "Interop Fixture" Spec
- **Location**: `docs/windows-sidecar-capture-interface.md`
- **Description**: Define a minimal test dataset the sidecar can generate:
  - One frame record + PNG
  - Matching journal + ledger entry
  - Optional backup bundle packaging
- **Complexity**: 4
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Sidecar can implement a deterministic one-record smoke test.
- **Validation**:
  - Manual review.

## Sprint 2: Deprecate In-Repo Capture Plugins On WSL
**Goal**: Make WSL runs stable by removing capture as a default responsibility of this repo.
**Demo/Validation**:
- Running `autocapture` on WSL should not attempt to start capture plugins by default.
- Processing/index/query features remain available and testable with fixtures.

### Task 2.1: Introduce A "Processing-Only" Default Profile On WSL
- **Location**: `config/default.json`, `autocapture_nx/kernel/config.py`, `autocapture_nx/ux/facade.py`
- **Description**:
  - Add a platform-aware default that disables capture plugins and capture threads on WSL.
  - Keep capture available only as an explicit opt-in.
- **Complexity**: 7
- **Dependencies**: Sprint 1 complete (contract exists)
- **Acceptance Criteria**:
  - Plugin registry no longer tries to load Windows capture plugins on WSL by default.
  - User can still explicitly enable capture on native Windows if desired.
- **Validation**:
  - Unit test: config resolution on WSL-like environment.
  - Existing plugin tests updated to account for new defaults.

### Task 2.2: Deprecation Signaling In UX And Docs
- **Location**: `README.md`, `contracts/user_surface.md`, `autocapture_nx/ux/plugin_options.py`
- **Description**:
  - Update user-facing docs/commands to state capture plugins are deprecated on WSL.
  - Hide or mark capture options as "Windows-sidecar required" when on WSL.
- **Complexity**: 5
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - No WSL-facing UI suggests capture plugins are supported/required.
- **Validation**:
  - Manual review + snapshot tests if present.

### Task 2.3: Keep Stub Capture For Deterministic Tests Only
- **Location**: `plugins/builtin/capture_stub/`, `tests/test_capture_stub_plugin.py`
- **Description**:
  - Ensure the stub plugin remains available for tests/fixtures and does not require Windows APIs.
  - Ensure default configs do not enable capture stub in production mode unless explicitly requested.
- **Complexity**: 4
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Stub-based fixture tests still pass.
- **Validation**:
  - Run relevant unit tests.

## Sprint 3: Pipeline Health Gate (Processing/Index/Query)
**Goal**: Prove the pipeline still works without capture plugins by default.
**Demo/Validation**:
- MOD-021 suite passes in low-resource mode.

### Task 3.1: Add Deterministic Processing-Only Fixture Test
- **Location**: `tests/`, `docs/test sample/README.md`, `autocapture_nx/processing/sst/`
- **Description**:
  - Add/extend a test that runs SST processing on a fixed screenshot fixture and verifies:
    - derived records exist
    - indexes update
    - query path returns citable results
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Test runs on WSL without requiring capture plugins.
- **Validation**:
  - `tools/run_mod021_low_resource.sh`

### Task 3.2: Ensure "No Deletion" + Raw-First Constraints Still Hold
- **Location**: `autocapture_nx/kernel/evidence_writer.py`, `autocapture_nx/kernel/backup_bundle.py`, `tests/`
- **Description**:
  - Add regression tests ensuring disabling capture does not introduce deletion/cleanup codepaths.
  - Ensure restore paths archive rather than overwrite where required.
- **Complexity**: 5
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - No-delete policy tests remain green.
- **Validation**:
  - Full test run in MOD-021 gate.

### Task 3.3: Fix MOD-021 Gate Failure In Evidence Validation Test
- **Location**: `tests/test_metadata_record_type.py`, `autocapture_nx/kernel/metadata_store.py`
- **Description**:
  - Align the test expectations with current evidence normalization behavior:
    - Evidence-like records have `payload_hash` normalized on write, so missing `content_hash` should not necessarily fail schema validation.
  - Ensure we still fail when required fields are missing (for example `run_id`).
- **Complexity**: 2
- **Dependencies**: None
- **Acceptance Criteria**:
  - `tools/run_mod021_low_resource.sh` passes end-to-end.
  - Evidence contract remains consistent with `contracts/evidence.schema.json` and canonical hashing rules.
- **Validation**:
  - `tools/run_mod021_low_resource.sh`

## Testing Strategy

- Primary gate: MOD-021 low-resource run.

Target shell: Bash (WSL)

```bash
tools/run_mod021_low_resource.sh
```

- Focused tests:
  - Capture disabled defaults
  - Fixture-based processing-only pipeline
  - Backup bundle restore + integrity checks

## Potential Risks & Gotchas

- Cross-platform key protection:
  - Windows DPAPI-protected keys are not usable on WSL; portable keyring bundles must be used for handoff.
- SQLCipher availability:
  - Metadata store depends on `sqlcipher3`; ensure sidecar and processor environments match expectations.
- Partial handoffs:
  - Shared DataRoot can lead to partially-written files across NTFS/WSL; Mode A minimizes this.
- Canonical JSON constraints:
  - Floats are disallowed in canonical JSON; sidecar record payloads must avoid floats if computing `payload_hash`.
- Time normalization:
  - Use ISO-8601 with timezone, prefer UTC; ensure `offset_minutes` is consistent with `tzid`.

## Rollback Plan

- Revert platform-aware defaults to the prior behavior.
- Keep contract docs; they are additive and should not be removed.
- Re-enable capture plugins explicitly via user config if needed for a Windows-native run.
