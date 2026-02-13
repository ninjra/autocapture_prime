# Plan: Mode B Full Processing Workflow (WSL Processor, Sidecar Evidence)

**Generated**: 2026-02-10
**Estimated Complexity**: High

## Overview

Goal: make `autocapture_prime` (WSL side) reliably run **full processing** end-to-end using evidence produced by a Windows sidecar (capture/ingest out of scope here), including:

- Evidence discovery (frames + window/input context)
- SST pipeline (OCR + VLM) and derived artifacts
- State layer (JEPA-style tape + retrieval embeddings)
- PromptOps-assisted query path that returns **natural-language answers with citations**

Architecture note (recommended next evolution, optimizing the 4 pillars):
- Prefer a DAG-style batch pipeline: ingest -> normalize -> fan-out model workers -> postprocess -> persist derived + embeddings -> build JEPA landscape (joint embedding + neighborhood index).
- Run each OCR/VLM/LLM/embedding model as a long-lived local server (vLLM where appropriate) and treat it as a stateless worker behind a scheduler (Ray Data is a good fit for batch + vLLM/VLM).
- Standardize every model output into one canonical record:
  - `{sample_id, modality, model_id, prompt_hash, output_json, emb_vectors[], metrics, provenance}`
- Store derived facts in two tiers:
  - Columnar Parquet/Arrow for durable, replayable facts.
  - Vector index (SQLite baseline now; Qdrant/Faiss optional later) for neighborhood/landscape queries.
- Make the landscape reproducible by pinning: dataset version, model version, prompt templates, decoder params, embedding normalization, and provenance hashes.

Hard constraints to preserve:

- Localhost-only; fail closed on network.
- No deletion endpoints; no retention pruning; archive/migrate only.
- Raw-first local store; sanitization only on explicit export.
- Foreground gating: when the user is ACTIVE, only capture+kernel runs; pause heavy processing.
- Idle budgets enforced: CPU <= 50% and RAM <= 50% (GPU may saturate).
- Treat sidecar/external inputs as untrusted; enforce PolicyGate and sandbox permissions.

Assumptions (chosen to optimize Performance/Accuracy/Security/Citeability):

- Mode B shared DataRoot is `D:\autocapture` (WSL: `/mnt/d/autocapture`) with `media/**/*.blob`.
- Sidecar provides an activity signal at `<DataRoot>/activity/activity_signal.json`.
- VLM is required (not “OCR-only”), so the golden workflow must run at least one VLM stage successfully.
- Default VLM model for WSL is `qwen2-vl-2b` (smallest high-utility option present in `plugins/builtin/`), configured offline with `network=false`.

## Prerequisites

- A shared DataRoot accessible from WSL (example):
  - `/mnt/d/autocapture/media/.../*.blob`
  - `/mnt/d/autocapture/activity/activity_signal.json`
  - `/mnt/d/autocapture/metadata.db` (SQLite, metadata+records; see Sprint 1)
- WSL GPU access if VLM runs on GPU (recommended).
- Python deps available in the venv for VLM plugins (`torch`, `transformers`) or explicitly handled as optional with a clear “VLM unavailable” diagnostic.

## Sprint 1: Mode B DataRoot Interop (Storage + Layout)

**Goal**: The processor can read evidence records and locate frame bytes in `.blob` media store under a Mode B DataRoot, regardless of sidecar’s DB layout variant.

**Demo/Validation**:
- `tools/sidecar_contract_validate.py --dataroot /mnt/d/autocapture` returns `ok=true`.
- The processor can load `evidence.capture.frame` records and read frame bytes for at least one record id.

### Task 1.1: Declare The Canonical Mode B Layout + Variants
- **Location**: `docs/windows-sidecar-capture-interface.md`
- **Description**:
  - Keep “flat DataRoot” as canonical (`/mnt/d/autocapture/{metadata.db,media/,activity/...}`).
  - Explicitly document *accepted metadata DB variants*:
    - Variant A: plaintext `metadata(payload, record_type, ts_utc, run_id)` table
    - Variant B: `records(record_type, ts_utc, json)` table + optional encrypted `metadata(...)` table
  - State the processor’s selection rules (prefer Variant A, fall back to Variant B).
- **Complexity**: 3
- **Dependencies**: None
- **Acceptance Criteria**:
  - The sidecar contract doc unblocks implementation without ambiguity.
- **Validation**:
  - Manual review + ensure `tools/sidecar_contract_validate.py` checks align.

### Task 1.2: Add Metadata Store Compatibility For `records` Table
- **Location**: `plugins/builtin/storage_sqlcipher/plugin.py` (and any shared store abstraction used by `autocapture_nx/kernel/metadata_store.py`)
- **Description**:
  - Detect DB schema at open:
    - If plaintext `metadata` table exists with expected columns: use existing path.
    - Else if a `records` table exists with JSON payload: expose it through the same metadata-store interface (`get/keys/latest/put_*`), treating `records.json` as canonical payload.
  - Ensure writes of derived records are append-only / replace-only semantics consistent with current metadata store behavior.
  - Add a config flag to force one mode (`storage.metadata_backend = "metadata_table"|"records_table"|"auto"`).
- **Complexity**: 8
- **Dependencies**: None
- **Acceptance Criteria**:
  - Processor can read existing sidecar records without “encrypted db” failures.
  - Derived records can be written without corrupting sidecar-owned tables.
- **Validation**:
  - Unit test with a temp SQLite DB in both layouts.

### Task 1.3: Resolve Mode B Journal/Ledger Discovery
- **Location**: `tools/sidecar_contract_validate.py`, `docs/windows-sidecar-capture-interface.md`
- **Description**:
  - Teach validator (and docs) to accept journal/ledger in either:
    - `<DataRoot>/journal.ndjson` and `<DataRoot>/ledger.ndjson`
    - or nested legacy sidecar location (if still present) while recommending canonical root paths.
- **Complexity**: 4
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Validator correctly finds the active journal/ledger and reports one canonical path.
- **Validation**:
  - Fixture test using a minimal directory tree.

## Sprint 2: Foreground Gating + Idle Budgets (Runtime Conductor)

**Goal**: Full processing is safe: it pauses heavy work when `user_active=true` and enforces CPU/RAM budgets during idle processing.

**Demo/Validation**:
- With `user_active=true`, processing steps return “blocked by active user” and do not run VLM/SST/state steps.
- With `user_active=false`, processing steps run and produce derived records.

### Task 2.1: Conductor Uses Sidecar Activity Signal When Input Tracker Missing
- **Location**: `autocapture/runtime/conductor.py`
- **Description**:
  - In `_signals()`: if `_input_tracker` is missing/unavailable, read `autocapture_nx/kernel/activity_signal.load_activity_signal(...)`.
  - Fail closed by default when signal is missing (config escape hatch allowed).
- **Complexity**: 4
- **Dependencies**: Existing `autocapture_nx/kernel/activity_signal.py` and tests.
- **Acceptance Criteria**:
  - Same gating semantics apply to worker and one-shot processing entrypoints.
- **Validation**:
  - Deterministic unit test using a temp DataRoot signal file.

### Task 2.2: Enforce CPU/RAM Idle Budgets In Processing Entry Points
- **Location**: `autocapture/runtime/governor.py`, `autocapture/runtime/conductor.py`, `autocapture_nx/processing/idle.py`
- **Description**:
  - Ensure the governor lease is used by:
    - one-shot processing
    - long-running worker processing
  - Explicitly cap CPU/RAM at 50% during idle, with clear metrics/log lines when throttling occurs.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Measured CPU/RAM stays within configured budgets during idle processing loops.
- **Validation**:
  - Add a synthetic budget-enforcement test (short runtime, asserts throttling path is hit).

## Sprint 3: WSL Processing-Only “Golden” Entry Points

**Goal**: Provide deterministic + operator-friendly commands to run the WSL processor against Mode B evidence without any capture plugins.

**Demo/Validation**:
- A single one-line command runs: validate -> process -> query, and returns an answer with citations.

### Task 3.1: Add One-Shot `process once` Command
- **Location**: `autocapture_nx/cli.py`, `autocapture_nx/ux/facade.py`
- **Description**:
  - Add a CLI command that:
    - validates DataRoot contract (calls `tools/sidecar_contract_validate` logic or shared helper)
    - checks gating (activity signal)
    - runs `IdleProcessor.process_step(...)` + state layer step
    - exits with distinct status codes:
      - `0` success (did work)
      - `2` nothing to do
      - `3` blocked by active user
      - `4` contract invalid
- **Complexity**: 7
- **Dependencies**: Sprint 1 and Sprint 2
- **Acceptance Criteria**:
  - Command is CI-usable (deterministic).
- **Validation**:
  - Unit tests for exit code matrix.

### Task 3.2: Add Long-Running `worker` Command (Processing Only)
- **Location**: `autocapture_nx/cli.py`, `autocapture/runtime/conductor.py`
- **Description**:
  - Starts the kernel + conductor for idle processing but does not start capture.
  - Logs periodic status (idle_seconds, gating source, items processed, VLM ok/errors).
- **Complexity**: 6
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Safe to run “always on” in WSL while sidecar produces evidence.

## Sprint 6: DAG Batch + Canonical Model Records + JEPA Landscape

**Goal**: introduce a batch-first DAG pipeline that scales processing while keeping outputs deterministic, citable, and queryable.

**Demo/Validation**:
- Given a bounded slice of evidence frames, the DAG produces canonical model output records for OCR/VLM/JEPA embeddings and persists them deterministically.
- A JEPA “landscape” (joint embedding space + neighborhood index) can be rebuilt from pinned inputs and matches hashes.

### Task 6.1: Define Canonical Model Output Record Contract
- **Location**: `contracts/` (new schema), `autocapture_nx/kernel/derived_records.py`
- **Description**:
  - Add a JSON schema for the canonical record:
    - `sample_id` (evidence id), `modality` (`ocr|vlm|state|embed|...`), `model_id`, `prompt_hash`,
      `output_json`, `emb_vectors[]`, `metrics`, `provenance` (including config/model digests).
  - Update derived record builders to emit compatible payloads and include stable hashing fields.
- **Complexity**: 6
- **Dependencies**: None
- **Acceptance Criteria**:
  - Every model stage can produce at least one canonical record without lossy transformation.
- **Validation**:
  - Schema validation tests for each stage output.

### Task 6.2: Add Columnar “Facts” Sink (Parquet/Arrow) For Derived Records
- **Location**: `autocapture_nx/storage/` (new), `autocapture/runtime/conductor.py` integration point
- **Description**:
  - Implement an append-only Parquet/Arrow writer for canonical model output records.
  - Partition by `run_id` and day/hour (ts_utc) to keep scans efficient and deterministic.
  - Ensure raw-first: do not sanitize locally; sanitization only on explicit export paths.
- **Complexity**: 7
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Replaying the same inputs yields byte-stable Parquet rows (or stable per-row hashes).
- **Validation**:
  - Deterministic replay test compares stored `provenance_hash` per record.

### Task 6.3: Add Batch Scheduler For Model Workers (Optional Ray Data)
- **Location**: `autocapture/runtime/scheduler.py` or new `autocapture/batch/`
- **Description**:
  - Add a batch job type that:
    - loads evidence ids
    - normalizes frames
    - fans out to long-lived model servers (OCR/VLM/embeddings)
    - postprocesses into canonical records
    - persists Parquet facts + updates lexical/vector indexes
  - If Ray is used, keep it localhost-only and fail closed when user is active.
- **Complexity**: 9
- **Dependencies**: Task 6.1, Task 6.2
- **Acceptance Criteria**:
  - Batch runs can be paused/preempted by foreground gating and resume safely.
- **Validation**:
  - Budget + gating tests simulate `user_active=true` and assert no heavy work is performed.

### Task 6.4: Build JEPA Landscape Index
- **Location**: `autocapture_nx/state_layer/` (new module) + `docs/`
- **Description**:
  - Define “landscape” artifacts:
    - joint embedding vectors per state/span
    - neighborhood index (baseline: sqlite-backed vector index; optional: Qdrant local)
  - Pin all reproducibility inputs and persist a landscape manifest (hashes + versions).
- **Complexity**: 8
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Landscape can be rebuilt deterministically from evidence + canonical records.
- **Validation**:
  - Golden test that rebuilds landscape and checks manifest hash stability.
- **Validation**:
  - Integration test boots worker briefly with a fixture DataRoot.

## Sprint 4: VLM Enablement (Offline, Citable)

**Goal**: VLM processing runs on WSL for at least one frame and produces `derived.text.vlm` and/or SST VLM-derived artifacts, feeding retrieval and citations.

**Demo/Validation**:
- After one-shot processing, the metadata store contains derived VLM records for at least one `evidence.capture.frame`.

### Task 4.1: Add A Mode B Processor Profile With VLM Enabled
- **Location**: `config/` (new profile), `autocapture_nx/ux/settings_schema.py` (if needed)
- **Description**:
  - Create a profile that:
    - points `storage.data_dir` at `/mnt/d/autocapture`
    - disables capture plugins by default
    - enables `builtin.vlm.qwen2_vl_2b` plugin (and disables `builtin.vlm.stub`)
    - sets `models.vlm_path` to the shared model directory (example: `/mnt/d/autocapture/models/qwen2-vl-2b-instruct`)
    - sets `processing.idle.max_concurrency_gpu` to 1, batch size small by default
    - enables SST pipeline + state layer
- **Complexity**: 5
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - On WSL, no network is required; plugin permissions remain `network=false`.
- **Validation**:
  - Config load test + a smoke run in fixture mode.

### Task 4.2: Add “VLM Not Available” Diagnostics That Fail The Golden Workflow
- **Location**: `autocapture_nx/processing/idle.py`, `autocapture_nx/processing/sst/pipeline.py`
- **Description**:
  - If VLM is required by profile and optional deps are missing, emit a single clear diagnostic:
    - missing torch/transformers
    - model path missing
    - GPU not available (if configured required)
  - Ensure golden workflow fails fast and explains what to install/configure.
- **Complexity**: 4
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - No “silent OCR-only” runs when user expects full VLM processing.
- **Validation**:
  - Unit tests for each missing-dependency scenario.

## Sprint 5: State Layer (JEPA) Integration In Golden Workflow

**Goal**: State tape and JEPA-style retrieval are part of the default workflow, and have an operator-usable lifecycle (train/approve/promote/report) with citations preserved.

**Demo/Validation**:
- After processing, `state` commands list training runs and the query path uses state retrieval.

### Task 5.1: Turn On State Layer Processing In Mode B Profile
- **Location**: `config/` (profile), `autocapture_nx/state_layer/processor.py`
- **Description**:
  - Ensure `processing.state_layer.enabled=true` in the Mode B profile.
  - Ensure the state layer reads from derived SST artifacts and writes state DBs under DataRoot (append-only / migrate-only semantics where applicable).
- **Complexity**: 4
- **Dependencies**: Sprint 3 and Sprint 4
- **Acceptance Criteria**:
  - State layer step runs without requiring capture plugins.
- **Validation**:
  - One-shot run produces state DB updates.

### Task 5.2: Golden “JEPA Lifecycle” Doc + Minimal Test
- **Location**: `docs/runbook.md` (or new focused doc under `docs/runbook/`), `tests/`
- **Description**:
  - Document and test:
    - `state jepa list`
    - `state jepa approve-latest`
    - `state jepa promote`
    - `state jepa report --latest`
  - Add a minimal unit/integration test that verifies the commands execute and return structured output (even if training is mocked/deterministic).
- **Complexity**: 6
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Operators can make JEPA active/inactive without breaking citations.
- **Validation**:
  - Test added to MOD-021 gate.

## Sprint 6: Golden End-to-End Workflow (Real DataRoot + Fixture)

**Goal**: Provide a “golden workflow” that works against both:
1) a small checked-in fixture DataRoot (deterministic tests), and
2) a real sidecar DataRoot at `/mnt/d/autocapture` (operator validation).

**Demo/Validation**:
- Running the golden workflow produces:
  - derived records (OCR + VLM + SST)
  - state layer updates
  - a natural-language answer with at least one resolved citation

### Task 6.1: Add A Minimal Checked-In Mode B Fixture DataRoot
- **Location**: `tests/fixtures/mode_b_dataroot/` (new)
- **Description**:
  - Include:
    - 1 `evidence.capture.frame` record with a matching `.blob`
    - minimal `activity/activity_signal.json`
    - minimal window/input context records if required by SST stage plugins
  - Keep files small; avoid large media.
- **Complexity**: 7
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Test fixture is deterministic and offline.
- **Validation**:
  - Unit test reads the blob and processes it.

### Task 6.2: Add Golden E2E Test For “Process Once -> Query With Citations”
- **Location**: `tests/test_mode_b_full_processing_golden.py` (new)
- **Description**:
  - Point config at the fixture DataRoot.
  - Run one-shot processing.
  - Run query via `autocapture_nx/kernel/query.py`.
  - Assert:
    - VLM-derived record exists (`derived.text.vlm` or SST `vision.vlm` artifacts)
    - State layer ran (state DB updated or expected record types written)
    - Result contains citations and they resolve to known record ids.
- **Complexity**: 9
- **Dependencies**: Sprint 3/4/5
- **Acceptance Criteria**:
  - Breaks if any part of “full processing” regresses.
- **Validation**:
  - Included in MOD-021.

### Task 6.3: Add Operator-Facing Golden Workflow Script (WSL)
- **Location**: `tools/` (new script)
- **Description**:
  - A single script that:
    - validates sidecar contract
    - runs one-shot processing with bounded budgets
    - runs a sample query
    - prints a short summary (items processed, citations count, gating source)
  - Script must be safe (no deletion, no network).
- **Complexity**: 5
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - One-line command runs end-to-end on WSL.
- **Validation**:
  - Manual run against real `/mnt/d/autocapture` during idle.

## Testing Strategy

- Primary gate: MOD-021 plus the new Mode B golden E2E test.
- Determinism:
  - Fixture mode uses a tiny DataRoot fixture.
  - Real Mode B runs are validated via script, but not required for CI.
- Security:
  - Ensure all VLM plugins have `network=false` and PolicyGate enforcement remains intact.

## Potential Risks & Gotchas

- Sidecar DB schema drift:
  - If the sidecar swaps between `metadata` vs `records` table layouts, the processor must auto-detect and fail with a clear recommendation.
- Cross-NTFS partial writes:
  - Mode B requires atomic replace. Missing atomicity can produce corrupt `.blob` reads and nondeterministic processing.
- GPU/torch/transformers variance:
  - “Works on my machine” risk is high; golden workflow must fail fast with explicit missing-dep diagnostics.
- Budget enforcement correctness:
  - Governor must apply to both SST and VLM (and state layer) to prevent runaway resource use.
- Citeability:
  - Derived records must include stable source references (`source_id`, `source_record_id`, and blob linkage) so citations can resolve.

## Rollback Plan

- Compatibility code paths are additive; default behavior remains unchanged unless Mode B profile is selected.
- If `records`-table compatibility causes regressions, gate it behind `storage.metadata_backend=auto|...` and default to existing behavior.
