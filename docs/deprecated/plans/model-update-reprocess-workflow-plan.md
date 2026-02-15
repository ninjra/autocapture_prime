# Plan: Model Update + Reprocess Workflow

**Generated**: 2026-02-03  
**Estimated Complexity**: High

## Overview
Add a first-class workflow to (1) update/add VLM/OCR/LLM models in `D:\autocapture\models`, and (2) reprocess stored raw evidence to generate new derived metadata without deletion. The workflow must maximize the 4 pillars (Performance, Accuracy, Security, Citeability), enforce localhost-only access, preserve raw-first storage, and produce a human-readable plugin-by-plugin report (no silent skips). Reprocessing must respect ordering by capture time and tag results with model metadata for selection/traceability.

## 4 Pillar Acceptance Criteria
- **Performance**: CPU/RAM utilization caps enforced (<=50%); GPU may saturate; reprocess runtime + batch sizes recorded.
- **Accuracy**: Multi-model outputs retained; best-result selection is deterministic and test-covered; no silent plugin skips.
- **Security**: Localhost-only bindings enforced; PolicyGate/sandbox checks required; all privileged overrides audited.
- **Citeability**: Model lock file + per-record model metadata; query results include bounding boxes/citations.

## Prerequisites
- Confirm whether existing blueprint/coverage mapping requirements remain mandatory (AGENTS.md says yes, user said “no blueprint needed”).
- Confirm whether model downloads are allowed to use network during explicit model update runs (HF/vLLM) and whether an offline-only default is required.
- Confirm if reprocessing should include *all* historical evidence or support time windows / run-id filters.
- Confirm the exact report format expected for reprocess runs (JSON + human readable text) and whether the run should fail if any plugin is skipped without an explicit reason.

## Sprint 1: Model Catalog + Update Pipeline
**Goal**: Make model updates deterministic, auditable, and citeable; support multiple OCR/VLM providers with explicit manifests and lock files.
**Demo/Validation**:
- `tools/model_prep.ps1` downloads/warmups models into `D:\autocapture\models` and emits a structured report.
- Model manifest + lock file show deterministic IDs, revisions, and checksums.

### Task 1.1: Normalize and extend model manifest
- **Location**: `tools/model_manifest.json`
- **Description**: Clean up duplicates and expand to cover OCR (RapidOCR ONNX), VLMs, and LLMs. Add per-model metadata fields (`source`, `revision`, `files`, `sha256`, `license`, `runtime`, `gpu_ok`) to improve citeability and determinism. Ensure DeepSeek-OCR-2 remains required and mapped to `deepseek-ai/DeepSeek-OCR-2`.
- **Complexity**: 4
- **Dependencies**: none
- **Acceptance Criteria**:
  - Manifest has no duplicate entries.
  - Each model includes an explicit subdir and revision or commit hash when available.
  - OCR model files (det/rec/cls + keys) are defined in the manifest.
- **Validation**:
  - `python tools/validate_model_manifest.py --path tools/model_manifest.json` (new)

### Task 1.2: Add model lock/receipt output
- **Location**: `tools/model_prep.ps1`, `tools/model_manifest.lock.json` (new)
- **Description**: Update `model_prep.ps1` to emit a lock/receipt file with resolved model IDs, revisions, local paths, file hashes, and download timestamps. This supports citeability and reproducibility.
- **Complexity**: 5
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Lock file is written on successful prep.
  - Required model failures cause a non-zero exit code.
- **Validation**:
  - Run `tools/model_prep.ps1` and verify lock file contents.

### Task 1.3: Localhost-only + audit for model updates
- **Location**: `tools/model_prep.ps1`, `autocapture_nx/kernel/audit.py`
- **Description**: Ensure model update actions explicitly record audit entries (append-only) and confirm all network usage is limited to explicit update runs. Add a “network permitted” flag and log it for security traceability. Enforce localhost-only for vLLM calls.
- **Complexity**: 3
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Audit log contains model update events with manifest hash + lock file path.
  - vLLM calls restricted to `127.0.0.1`.
- **Validation**:
  - Inspect `artifacts/audit/audit.jsonl` entries.

## Sprint 2: Reprocess Pipeline (New Models → New Derived Metadata)
**Goal**: Reprocess existing raw evidence with updated models while preserving history and capturing per-plugin results.
**Demo/Validation**:
- `tools/reprocess_models.ps1` runs end-to-end and produces a plugin execution report + updated derived metadata.

### Task 2.1: Reprocess runner (Python)
- **Location**: `tools/reprocess_models.py` (new), `autocapture_nx/processing/idle.py`, `autocapture_nx/kernel/query.py`
- **Description**: Implement a reprocess runner that:
  - Loads a config overlay enabling all plugins.
  - Sets `runtime.run_id` for the reprocess run and disables destructive behavior.
  - Uses idle processing with `order_by=ts_utc`, `checkpoint_mode=disabled` (or per-run), and `backfill_out_of_order=true`.
  - Tags derived records with `model_id`, `model_revision`, and `run_id`.
  - Enumerates all registered plugins, attempts execution, and records a structured status (available/enabled/dependency satisfied + success/failure/skip reason). If any plugin is skipped without an explicit reason, the run fails.
  - Emits a human-readable per-plugin report plus JSON artifact.
- **Complexity**: 7
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Reprocess run adds new derived records without overwriting existing ones.
  - Report lists every plugin with success/failure reason.
  - Delete endpoints/retention pruning are disabled; stores remain append-only.
- **Validation**:
  - `python tools/reprocess_models.py --data-dir <dir> --manifest tools/model_manifest.json`

### Task 2.2: PowerShell wrapper for Windows
- **Location**: `tools/reprocess_models.ps1` (new)
- **Description**: Provide a PS1 wrapper that:
  - Optionally runs `tools/model_prep.ps1`.
  - Calls `tools/reprocess_models.py` with Windows path handling.
  - Preserves exit codes and prints a summary.
- **Complexity**: 3
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Works with `D:\` paths and spaces.
  - Outputs both JSON and human-readable summaries.
- **Validation**:
  - Manual PowerShell run on Windows host.

### Task 2.3: Reprocess config overlay
- **Location**: `tools/reprocess_config_template.json` (new), `config/default.json`, `contracts/config_schema.json`
- **Description**: Add a reprocess overlay that:
  - Enables all processing plugins (OCR, VLM, state, window metadata, etc.).
  - Enforces CPU/RAM budgets <= 50% while allowing GPU saturation.
  - Uses screensaver-based activity gating; default behavior is **pause processing while active** and resume when idle. Allow an explicit `--force-idle` override only for testing, and audit it.
  - Forces lossless handling and raw-first storage.
  - Enforces localhost-only bindings; fail closed if any plugin attempts to bind beyond 127.0.0.1.
- **Complexity**: 5
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Overlay passes schema validation.
  - Foreground gating override is auditable and optional; default pause/resume is verified.
- **Validation**:
  - `python -m autocapture_nx config show` with overlay.

### Task 2.4: Model-aware query selection
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/kernel/derived_records.py`
- **Description**: Update query selection to prefer the best available derived records (newest model run, higher confidence) while retaining citations to exact bounding boxes. Ensure multiple model outputs remain queryable.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Query responses include model metadata and citations.
  - Fallback to older model outputs is explicit when newer results are absent.
- **Validation**:
  - Unit test with two model runs; ensure selection preference.

### Task 2.5: Storage growth strategy (no deletion)
- **Location**: `docs/retention.md` (new) or `README.md`
- **Description**: Provide storage guidance for multi-model reprocessing (e.g., archive older derived runs under `derived/<model_id>/<run_id>`; compress or migrate to slower media without deletion).
- **Complexity**: 2
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Documented storage plan without any delete/prune steps.
- **Validation**:
  - Doc review.

### Task 2.6: Audit + PolicyGate coverage for reprocess
- **Location**: `autocapture_nx/kernel/audit.py`, `autocapture_nx/runtime/governor.py`, `tools/reprocess_models.py`
- **Description**: Add append-only audit events for reprocess start/finish, overlay application, plugin execution outcomes, and any forced-idle override. Ensure PolicyGate and sandbox checks are enforced for all plugins during reprocess.
- **Complexity**: 4
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Audit log includes reprocess lifecycle and per-plugin outcomes.
  - PolicyGate violations fail the reprocess run with a clear error.
- **Validation**:
  - Unit tests and manual inspection of audit log.

## Sprint 3: Tests + Coverage + Docs
**Goal**: Add deterministic tests and update coverage mapping.
**Demo/Validation**:
- `pytest tests/test_reprocess_models.py -q` passes.

### Task 3.1: Manifest + lock validation tests
- **Location**: `tests/test_model_manifest.py` (new)
- **Description**: Validate manifest schema and lock output fields; ensure duplicate IDs are rejected.
- **Complexity**: 3
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Tests fail on malformed manifest or missing required fields.
- **Validation**:
  - `pytest tests/test_model_manifest.py -q`

### Task 3.2: Reprocess integration test (deterministic)
- **Location**: `tests/test_reprocess_models.py` (new)
- **Description**: Use a synthetic PNG + stub OCR/VLM providers to simulate two model runs. Assert:
  - New derived records are appended (not overwritten).
  - Query prefers latest model run.
  - Plugin report includes all plugins and failure reasons.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Deterministic pass in CI.
- **Validation**:
  - `pytest tests/test_reprocess_models.py -q`

### Task 3.3: Audit coverage + gating tests
- **Location**: `tests/test_reprocess_audit.py` (new)
- **Description**: Verify reprocess audit events (start/finish, plugin results, overlay application) and gating behavior (pause/resume when active, explicit override audited). Confirm localhost-only enforcement for any web bindings.
- **Complexity**: 4
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Audit log entries exist with run_id and manifest hash.
- **Validation**:
  - `pytest tests/test_reprocess_audit.py -q`

### Task 3.4: Coverage map and docs
- **Location**: `docs/reports/implementation_matrix.md`, `docs/spec/autocapture_nx_blueprint_2026-01-24.md`, `docs/reports/blueprint-gap-2026-02-02.md`, `README.md`
- **Description**: Map new modules/tests to SRC requirements per protocol. Add user-facing docs on updating models and reprocessing metadata.
- **Complexity**: 3
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Coverage_Map references are updated and verifiable.
- **Validation**:
  - `pytest tests/test_blueprint_spec_validation.py -q`

## Testing Strategy
- Unit: `pytest tests/test_model_manifest.py -q`
- Integration: `pytest tests/test_reprocess_models.py -q`, `pytest tests/test_reprocess_audit.py -q`
- Full: `python tools/run_all_tests.py` (confirm MOD-021 suites pass)
- Manual: `tools/model_prep.ps1` then `tools/reprocess_models.ps1`

## Potential Risks & Gotchas
- **Network usage**: HF downloads require network; must be explicit and audited.
- **GPU memory pressure**: Multiple VLMs may exceed VRAM; plan for sequential batching or model sharding.
- **Model drift**: Without lock files, results are not citeable; lock file mandatory.
- **Ordering**: Evidence must be processed by `ts_utc` for correct temporal queries.
- **Storage growth**: Multiple runs expand derived records; use archive/migrate guidance.

## Rollback Plan
- Revert model manifest changes and remove reprocess tools/scripts.
- Keep any generated derived records and audit logs (no deletion); optionally move to an archive folder.
