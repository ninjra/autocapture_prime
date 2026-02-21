# Plan: Mode B WSL Golden Workflow (Sidecar Evidence -> Processing -> NL Query)

**Generated**: 2026-02-10  
**Estimated Complexity**: High

## Overview

Goal: make the WSL-side processor (`autocapture_prime`) reliably consume a **Mode B shared DataRoot** produced by a Windows sidecar (no in-repo capture), run the full processing pipeline (SST + state layer + indexing), and answer natural-language queries via the existing query + PromptOps + citations flow.

Extra architecture guidance (for the “JEPA landscape” path):
- Prefer a DAG-style batch pipeline: ingest -> normalize -> fan-out to model workers -> postprocess -> persist canonical model records -> build landscape index.
- Run OCR/VLM/LLM/embedding models as long-lived localhost servers (vLLM where appropriate) and treat them as stateless workers behind the scheduler.
- Standardize model outputs into a canonical record:
  - `{sample_id, modality, model_id, prompt_hash, output_json, emb_vectors[], metrics, provenance}`
- Store derived facts in Parquet/Arrow (durable) and embeddings in a neighborhood index (vector DB).
- Pin dataset/model/prompt/decoder params and provenance hashes for deterministic rebuilds.

Key constraints:
- Capture/ingest is out of scope in this repo; sidecar writes evidence.
- Foreground gating: when user is active, only capture+kernel runs; heavy processing must pause.
- Localhost-only and no deletion constraints must remain enforced.

Approach:
- Treat `/mnt/d/autocapture` as the **shared DataRoot** (`storage.data_dir`).
- Make the runtime conductor and any processing entrypoints use the **sidecar activity signal** when `tracking.input` is not available.
- Add a processor-facing **“worker” command** to start the conductor in processing-only mode on WSL.
- Add a deterministic **one-shot “process once” command** for CI/golden verification without running a daemon.
- Add a golden fixture + test that proves: evidence frame -> derived SST/state -> retrieval -> query returns citable claims.

## Prerequisites

- Sidecar Mode B contract implemented:
  - Plaintext `metadata.db` schema (`metadata(id, payload, record_type, ts_utc, run_id)`).
  - Canonical `media/*.blob` layout keyed by `record_id` (not `.png`).
  - `activity/activity_signal.json` present and updated atomically.
  - Reference: `docs/windows-sidecar-capture-interface.md`.
- Processor config can safely write derived artifacts and indexes under the shared DataRoot (append-only for evidence; derived allowed).
- WSL environment has required libs for OCR/VLM stages (or they are explicitly disabled in config).

## Clarifications (Need User Confirmation)

1. Should derived artifacts and indexes be written into the shared DataRoot (`/mnt/d/autocapture`) or into a separate processor-owned directory (with only reads from `/mnt/d/autocapture`)?
2. For “golden workflow”, is OCR-only acceptable initially (VLM disabled on WSL), or is VLM required on day 1?
3. Should the long-running worker be the primary workflow, or do you want a strict “batch once per N minutes” job model?

Assumptions if unanswered:
- Processor writes derived + indexes into the shared DataRoot.
- OCR is required, VLM optional (disabled by default on WSL unless configured).
- Provide both worker and one-shot modes.

## Sprint 1: Mode B Processor Profile (WSL)
**Goal**: a single explicit processor profile that points the repo at the shared DataRoot and disables capture.

**Demo/Validation**:
- Boot kernel on WSL with `AUTOCAPTURE_DATA_DIR=/mnt/d/autocapture` and the profile applied.
- `autocapture doctor --self-test` passes without attempting capture.

### Task 1.1: Add A Mode B Processor Profile
- **Location**: `config/` (new file), `autocapture_nx/kernel/paths.py`, `autocapture_nx/kernel/loader.py`
- **Description**:
  - Add a user-facing profile (e.g. `profile=mode_b_processor_wsl`) that:
    - sets `paths.data_dir` / `storage.data_dir` to `/mnt/d/autocapture` via env or config
    - overrides `storage.metadata_path` to `metadata.db` (flat root)
    - overrides `storage.media_dir` to `media` (flat root)
    - disables encryption (`storage.encryption_enabled=false`, `storage.encryption_required=false`) for cross-platform Mode B
    - disables capture defaults (no capture plugins auto-start)
  - Keep all other derived/index paths under a processor-owned subdir to avoid ambiguity (either `data/` under DataRoot or `processor/`).
- **Complexity**: 7
- **Dependencies**: None
- **Acceptance Criteria**:
  - Profile is documented and does not rely on manual path edits.
  - Loading config yields correct absolute paths for metadata/media.
- **Validation**:
  - New unit test asserting path normalization under Mode B.

### Task 1.2: Document The “WSL Processor Only” Golden Setup
- **Location**: `docs/` (new doc, single source of truth)
- **Description**:
  - Write an operator-focused doc that explains:
    - required sidecar outputs
    - how to point the processor at `/mnt/d/autocapture`
    - what “success” looks like (doctor checks + minimal query)
- **Complexity**: 3
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - A single doc can onboard a new machine without tribal knowledge.
- **Validation**:
  - Manual review against `tools/sidecar_contract_validate.py` output.

## Sprint 2: Make Runtime Conductor Mode-B Aware (Activity Signal)
**Goal**: idle processing, research, and background tasks respect sidecar-provided activity signals when Windows input hooks are unavailable.

**Demo/Validation**:
- With `tracking.input` absent, conductor uses `/mnt/d/autocapture/activity/activity_signal.json` to decide ACTIVE vs IDLE modes.

### Task 2.1: Add Sidecar Activity Signal Fallback To Conductor
- **Location**: `autocapture/runtime/conductor.py`
- **Description**:
  - In `_signals()`, when `_input_tracker is None`, attempt to read sidecar signal using `autocapture_nx.kernel.activity_signal.load_activity_signal(config)`.
  - Fail closed if missing unless `runtime.activity.assume_idle_when_missing=true`.
- **Complexity**: 4
- **Dependencies**: Existing `autocapture_nx/kernel/activity_signal.py`
- **Acceptance Criteria**:
  - Conductor gating matches the same logic used in query/trace_process.
- **Validation**:
  - New unit test with a temp DataRoot containing `activity_signal.json`.

### Task 2.2: Add Audit Logging For Sidecar Signal Use
- **Location**: `autocapture/runtime/conductor.py`, `autocapture_nx/kernel/audit.py`
- **Description**:
  - Append an audit event once per boot when sidecar activity signal is used for gating.
- **Complexity**: 2
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Append-only audit log entry exists and is not spammy.
- **Validation**:
  - Unit test verifies one audit append per boot.

## Sprint 3: Golden “Processor Worker” Entry Point (WSL)
**Goal**: a supported way to run processing continuously on WSL without capture plugins.

**Demo/Validation**:
- Start worker, wait for user idle, observe derived records being written and query returns citations.

### Task 3.1: Add `autocapture worker` Command (Processing-Only)
- **Location**: `autocapture_nx/cli.py`, `autocapture_nx/ux/facade.py`
- **Description**:
  - Add a CLI subcommand that boots the kernel with `start_conductor=True` and runs until Ctrl+C.
  - Ensure it does not start capture (explicitly `auto_start_capture=False`).
  - Print periodic status summaries (mode, idle_seconds, last_idle_ok, counts).
- **Complexity**: 6
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Worker runs on WSL with Mode B profile and does not require Windows-only plugins.
- **Validation**:
  - Integration test boots worker for a short duration using a fixture DataRoot and asserts no crash.

### Task 3.2: Add `autocapture process once` (Deterministic Batch)
- **Location**: `autocapture_nx/cli.py`, `autocapture_nx/processing/idle.py`
- **Description**:
  - Add a one-shot command that:
    - checks gating (sidecar activity signal)
    - runs `IdleProcessor.process_step(...)` with a fixed budget
    - runs state layer step
    - exits with status code indicating “did work / no work / blocked by active user”.
- **Complexity**: 6
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Usable by CI/golden harness; does not require daemon.
- **Validation**:
  - Unit tests for exit codes under different activity signal values.

## Sprint 4: Golden End-to-End Scenario (Evidence -> Derived -> Query)
**Goal**: prove a real Mode B dataset produces citable natural-language answers.

**Demo/Validation**:
- A scripted run (WSL) that:
  - validates DataRoot contract
  - processes a bounded set of frames
  - runs `autocapture query "..."` and gets `state=ok` with citations

### Task 4.1: Add A Minimal Mode-B Fixture DataRoot
- **Location**: `tests/fixtures/mode_b_dataroot/` (new)
- **Description**:
  - Build a tiny DataRoot fixture that includes:
    - 1-3 `evidence.capture.frame` records + matching `.blob` files
    - `derived.input.summary` record(s)
    - `activity/activity_signal.json`
    - minimal journal/ledger lines (or omit if tests mock writers)
- **Complexity**: 7
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Fixture is small, deterministic, and checked into repo.
- **Validation**:
  - Test suite can run offline.

### Task 4.2: Add A Golden E2E Test
- **Location**: `tests/test_mode_b_golden_workflow.py` (new)
- **Description**:
  - Boot system pointing at the fixture DataRoot.
  - Run one-shot processing command (or call IdleProcessor directly).
  - Run `run_query()` with a query that should hit the derived text.
  - Assert:
    - derived records exist (`derived.sst.*` and/or `derived.text.ocr`)
    - query result includes at least 1 claim with at least 1 resolved citation.
- **Complexity**: 8
- **Dependencies**: Task 4.1, Sprint 2/3
- **Acceptance Criteria**:
  - Test fails if processing pipeline breaks, citations break, or retrieval breaks.
- **Validation**:
  - Included in MOD-021 gate.

## Sprint 5: JEPA Training/Approval Workflow (Operator-Usable)
**Goal**: make “JEPA and etc” explicitly runnable and observable.

**Demo/Validation**:
- After processing, list training runs and approve/promote a model, then re-query.

### Task 5.1: Document The JEPA Lifecycle Commands As Part Of Golden Workflow
- **Location**: `docs/` (append to Sprint 1 doc)
- **Description**:
  - Add steps for:
    - `state jepa list`
    - `state jepa approve latest`
    - `state jepa promote`
    - `state jepa report`
- **Complexity**: 3
- **Dependencies**: Sprint 3/4
- **Acceptance Criteria**:
  - Clear operator instructions and expected outputs.
- **Validation**:
  - Manual run on a real Mode B dataset.

### Task 5.2: Add A “Training Disabled” Fallback Mode
- **Location**: `config/default.json`, `autocapture_nx/state_layer/*`
- **Description**:
  - Ensure queries work even if training is disabled or no model is approved.
  - Make fallback deterministic and logged.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Query returns citable answers even without approved models (may be lower quality).
- **Validation**:
  - Unit test toggling `processing.state_layer.features.training_enabled`.

## Testing Strategy

- Unit tests:
  - Conductor gating uses sidecar activity signal.
  - Mode B profile path normalization.
  - One-shot processing exit codes.
- Integration:
  - Worker boots on WSL and stays alive briefly.
- Golden E2E:
  - Fixture DataRoot -> processing -> query -> citations.
- Gate:
  - `tools/run_mod021_low_resource.sh`

## Potential Risks & Gotchas

- **Shared DataRoot write contention**: sidecar writing evidence while processor writes derived/indexes; mitigate with atomic writes and append-only semantics.
- **Keyring/crypto side effects**: processor must not require DPAPI/Windows-only keys; Mode B should keep encryption disabled.
- **Path normalization**: defaults like `data/media` break flat DataRoot; Mode B profile must override.
- **Resource budgets**: idle processor must honor CPU/RAM thresholds; integrate governor lease budgeting.
- **GPU on WSL**: VLM may not be available; ensure VLM stages are auto-disabled when GPU is unavailable.

## Rollback Plan

- Keep Mode B profile additive; default behavior unchanged.
- If worker/process commands cause issues, gate them behind explicit subcommands and leave existing CLI unchanged.
- Revert conductor sidecar signal fallback if it causes mis-gating; keep query/trace_process fallback as-is.
