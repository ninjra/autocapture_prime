# Plan: Fixture CLI Multi-Extractor Accuracy (OCR + VLM + SST)

**Generated**: 2026-02-02
**Estimated Complexity**: High

## Overview
Build a CLI-only fixture pipeline that runs the known screenshot through capture, idle processing, and query flow using multi-OCR + VLM + SST UI/state + state_layer + OS window metadata. Ensure answers are accurate with citations that include bbox coordinates, fail closed on missing evidence, enforce foreground gating/budgets, and keep all processing local/offline with PolicyGate enforcement.

## Prerequisites
- Windows PowerShell execution for primary workflow (WSL only for dev/troubleshoot).
- Local Python 3.x available on Windows (venv allowed; use `py -3` or `python` on Windows).
- OCR deps: `pillow` + `rapidocr-onnxruntime` + `onnxruntime` (preferred), optional `pytesseract` for fallback.
- VLM deps: local offline model path (preferred) or toy VLM bundle file path.
- Local model cache under `D:\autocapture` (PS1 will probe for models and optional vLLM; only 127.0.0.1 allowed).
- Confirm screenshot path (e.g., `D:\projects\autocapture_prime\docs\test sample\...`).
- GPU optional; CPU-only must remain within 50% budget.

## Sprint 1: Fixture Spec + Config for VLM/SST/state_layer/OS
**Goal**: Make the fixture spec explicit and ensure VLM + SST UI/state + state_layer + OS metadata extraction are enabled in the CLI pipeline.
**Demo/Validation**:
- `python3 tools/validate_fixture_manifest.py --path "docs/test sample/fixture_manifest.json"`
- `python3 tools/run_fixture_pipeline.py --manifest "docs/test sample/fixture_manifest.json"`
- Verify report includes OCR + VLM + SST derived counts and queries w/ citations.

### Task 1.0: Lock the extraction set (SST + state_layer + OS metadata)
- **Location**: `docs/test sample/fixture_manifest.json`, `tools/fixture_config_template.json`
- **Description**: Confirm all three non-OCR/VLM methods are enabled: SST UI/state, state_layer, and OS window metadata. Document the set and update config/queries accordingly.
- **Complexity**: 3
- **Dependencies**: None
- **Acceptance Criteria**:
  - Extraction set (SST + state_layer + OS metadata) is reflected in config + queries.
- **Validation**:
  - Plan review + manifest/config diff.

### Task 1.1: Define explicit query expectations (required questions)
- **Location**: `docs/test sample/fixture_manifest.json`
- **Description**: Add explicit queries for: song playing + time left, Chrome window count, remote desktop content, host app count, and time since last tax accountant contact. Set `match_mode: contains` and require bbox coordinates per citation. Preserve auto mode to catch additional tokens.
- **Complexity**: 4
- **Dependencies**: Task 1.0
- **Acceptance Criteria**:
  - Manifest includes explicit query list with expected matches.
  - Queries target OCR text, VLM caption/layout, SST UI/state, state_layer, and OS metadata.
  - Queries specify bbox citation requirement and `match_mode: contains`.
  - `tools/validate_fixture_manifest.py` passes.
- **Validation**:
  - Run manifest validation; review query list for coverage.

### Task 1.2: Enable all plugins + VLM/SST/state_layer/OS in fixture config
- **Location**: `tools/fixture_config_template.json`
- **Description**: Enable all available plugins (no silent skips) and turn on VLM extraction for idle/on_query, SST UI parsing (VLM JSON + detector fallback), state_layer processing, and OS window metadata capture. Explicitly enable core plugins (`builtin.vlm.basic`, `builtin.sst.ui.parse` or `builtin.processing.sst.ui_vlm`, `builtin.window.metadata.windows`, state_layer plugins) and ensure stage providers allow VLM. Keep `raw_first_local: true`, localhost-only bind, and lossless capture.
- **Complexity**: 5
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - `processing.idle.extractors.vlm: true` and `processing.on_query.extractors.vlm: true` in overlay.
  - SST UI parse configured (`processing.sst.ui_parse.mode: vlm_json` or stage hook enabled).
  - state_layer + OS metadata enabled in overlay and plugin set.
  - All enabled plugins are included in the config for probe coverage.
  - No network egress; budgets remain at 0.5 CPU/RAM.
- **Validation**:
  - Run fixture pipeline; report shows `derived.sst.state` and `derived.sst.text` records.

### Task 1.3: Extend fixture report for VLM/SST coverage
- **Location**: `tools/run_fixture_pipeline.py`, `autocapture_nx/ux/fixture.py`
- **Description**: Add VLM availability report (model path, backend, errors) and SST coverage counts (derived.sst.state/text, ui elements, tables/spreadsheets/charts). Include audit events for extractor availability, policy exceptions, and config.
- **Complexity**: 6
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Report JSON includes `vlm` and `sst` coverage sections.
  - Audit log captures extractor availability and config hash.
- **Validation**:
  - Run pipeline and inspect `fixture_report.json` for new sections.

### Task 1.4: Define bbox citation contract for answers
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/ux/facade.py`, `tools/run_fixture_pipeline.py`
- **Description**: Specify how answers surface bbox coordinates per claim and citation (single or multiple boxes). Ensure the fixture report enforces bbox presence for all required queries.
- **Complexity**: 5
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Each answer claim includes bbox coordinates tied to citations.
  - Fixture pipeline fails if bbox coordinates are missing.
- **Validation**:
  - Run pipeline and verify bbox entries in answers.

### Task 1.5: Plugin execution trace + coverage enforcement
- **Location**: `autocapture_nx/plugin_system/registry.py`, `autocapture_nx/ux/fixture.py`, `tools/run_fixture_pipeline.py`
- **Description**: Instrument capability calls to emit a per-plugin execution log (plugin_id, capability, method, status, duration, diagnostics). Require that every enabled plugin is invoked at least once; failures are recorded per-plugin but do not abort the run. Output a complete, human-readable listing of steps/plugins/results in `fixture_report.json`.
- **Complexity**: 7
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - `fixture_report.json` includes a full list of plugin runs and their results (success/failure + reason).
  - Fixture run continues even if plugins fail; failures are surfaced in a human-readable summary.
- **Validation**:
  - Run pipeline and inspect report for plugin run listings.

### Task 1.6: Storage growth reporting + archive recommendations
- **Location**: `tools/run_fixture_pipeline.py`, `autocapture_nx/ux/fixture.py`, `docs/reports/*`
- **Description**: Track storage growth per provider (OCR/VLM/SST/state_layer) and include a recommendations section in the fixture report for archive/migrate strategies (no deletion) if growth exceeds thresholds.
- **Complexity**: 4
- **Dependencies**: Task 1.5
- **Acceptance Criteria**:
  - Fixture report includes per-provider storage deltas and archive/migrate recommendations when needed.
- **Validation**:
  - Run pipeline and verify storage section in report.

### Task 1.7: Plugin probe harness (force every plugin to run)
- **Location**: `tools/run_fixture_pipeline.py`, `autocapture_nx/plugin_system/*`, `docs/reports/*`
- **Description**: Add a deterministic probe registry that defines how to safely invoke each enabled plugin at least once (e.g., start/stop capture, extract on sample frame, validate configs). If a plugin lacks a safe probe, record a failure with a human-readable reason. Never silently skip.
- **Complexity**: 7
- **Dependencies**: Task 1.5
- **Acceptance Criteria**:
  - Every enabled plugin has a probe attempt recorded.
  - Missing probes are reported as failures (not silent).
- **Validation**:
  - Run pipeline and confirm all enabled plugins have probe entries.

### Task 1.8: Screensaver-based user activity gating
- **Location**: `plugins/builtin/input_windows/plugin.py`, `autocapture_nx/windows/*`, `autocapture_nx/ux/fixture.py`
- **Description**: Replace display power checks with screensaver state for user activity detection (blank screensaver supported). When screensaver is active, treat the user as idle; when inactive, treat as active. Add config flags for screensaver polling and include state in activity signals and fixture report.
- **Complexity**: 6
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Activity gating uses screensaver state (blank screensaver supported).
  - Fixture report includes screensaver status and derived idle/active decisions.
- **Validation**:
  - Simulate screensaver on/off and verify gating behavior.

## Sprint 2: OCR Backend (RapidOCR/ONNX) Reliability
**Goal**: Run multiple OCR backends in parallel (RapidOCR + Tesseract + basic), store all outputs, and preserve deterministic offline fallback.
**Demo/Validation**:
- `python3 tools/run_fixture_pipeline.py --manifest "docs/test sample/fixture_manifest.json"`
- Report shows multiple OCR providers active (RapidOCR + Tesseract + basic) with non-zero OCR tokens per provider.

### Task 2.0: Wire multiple OCR providers (store all results)
- **Location**: `autocapture_nx/kernel/loader.py`, `config/default.json`, `tools/fixture_config_template.json`
- **Description**: Ensure the system can register multiple `ocr.engine` providers simultaneously (basic + tesseract + rapidocr) and persist per-provider outputs. Use MultiCapabilityProxy or equivalent so all providers run and store derived records.
- **Complexity**: 6
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Each OCR provider yields its own `derived.text.ocr` record(s).
  - Provider IDs are preserved for citations/diagnostics.
- **Validation**:
  - Run pipeline and confirm multiple OCR provider records.

### Task 2.1: Implement OCR backend selection with RapidOCR
- **Location**: `autocapture/ingest/ocr_basic.py`, `plugins/builtin/ocr_stub/plugin.py`, `autocapture/ingest/normalizer.py`
- **Description**: Add a RapidOCR path (onnxruntime) that returns tokens with bboxes. Prefer RapidOCR when available; fall back to Tesseract if configured; then fallback to basic PIL OCR. Keep offline-only behavior and ensure outputs are stored per-provider.
- **Complexity**: 7
- **Dependencies**: Task 2.0
- **Acceptance Criteria**:
  - OCR tokens produced with bboxes when RapidOCR installed.
  - Fallback path remains deterministic.
  - No network calls introduced.
- **Validation**:
  - Unit test new backend selection and token shapes.

### Task 2.2: Windows PowerShell bootstrap for OCR/VLM deps
- **Location**: `tools/run_fixture_pipeline.ps1` (or new `tools/setup_fixture_deps.ps1`)
- **Description**: Provide PS1 to create/activate venv, probe `D:\autocapture` for local model artifacts, check for vLLM vision models, and install required OCR deps. Do not require WSL. Include optional step for Tesseract path.
- **Complexity**: 5
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Running PS1 results in usable OCR deps on Windows.
  - Script fails closed if install fails.
- **Validation**:
  - Run PS1 and confirm `python -c "import PIL, rapidocr_onnxruntime"` succeeds.

### Task 2.3: PolicyGate + audit for new OCR capability
- **Location**: `plugins` policy config (`tools/fixture_config_template.json`), `autocapture_nx/kernel/audit`
- **Description**: Ensure filesystem policies allow read-only access to fixture frames and local model files; no network. Append audit event for each OCR backend used.
- **Complexity**: 4
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - PolicyGate allows only minimal read access.
  - Audit log records OCR backend selection.
- **Validation**:
  - Run pipeline; verify no PolicyGate denials and audit event presence.

### Task 2.4: GPU/CUDA utilization for OCR
- **Location**: `tools/run_fixture_pipeline.ps1`, `autocapture/ingest/ocr_basic.py`
- **Description**: Install/use GPU-capable runtimes (`onnxruntime-gpu`, CUDA libs) and configure OCR providers to prefer GPU. Capture GPU availability, device name (RTX 4090), and utilization snapshot in the fixture report. Enforce CPU/RAM budgets while allowing GPU saturation.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - OCR pipeline reports GPU availability and backend device.
  - GPU usage is preferred when available without violating CPU/RAM caps.
- **Validation**:
  - Run pipeline and confirm GPU info in report.

## Sprint 3: VLM + SST UI/State + state_layer + OS Metadata
**Goal**: Add VLM extraction plus SST UI/state, state_layer retrieval, and OS window metadata for robust queries.
**Demo/Validation**:
- Run fixture pipeline and confirm `derived.text.vlm` + `derived.sst.state` + OS metadata + state_layer records exist.
- Queries for UI elements/windows return accurate, cited answers with bboxes.

### Task 3.0: OS window metadata ingestion
- **Location**: `tools/fixture_config_template.json`, `plugins/builtin/window_metadata_windows/*`, `autocapture_nx/kernel/query.py`
- **Description**: Enable OS window metadata capture (window list, app names, counts) and store as queryable derived records. Tie OS metadata to the screenshot run_id and timestamps for citation, and implement title-to-OCR matching to map OS metadata to screenshot bboxes where possible.
- **Complexity**: 6
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - OS window/app count records are persisted and queryable.
  - Citations can reference OS metadata evidence with mapped screenshot bboxes when possible.
- **Validation**:
  - Run pipeline and verify OS metadata records exist.

### Task 3.1: VLM backend selection (offline)
- **Location**: `plugins/builtin/vlm_stub/plugin.py`, `tools/fixture_config_template.json`
- **Description**: Enable VLM model path via config/env and keep offline mode. Validate model path exists and optionally checksum it. If no model is provided, ensure deterministic heuristic fallback is flagged in report.
- **Complexity**: 6
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - VLM backend/availability reported.
  - Offline-only behavior enforced (HF offline envs set).
- **Validation**:
  - Run pipeline; report includes VLM backend and errors if missing.

### Task 3.1b: Optional vLLM OpenAI-compat VLM provider (localhost-only)
- **Location**: `plugins/builtin/vlm_openai_compat/*`, `tools/fixture_config_template.json`, `tools/run_fixture_pipeline.ps1`
- **Description**: Add a localhost-only VLM provider that calls a vLLM OpenAI-compatible endpoint for image-to-text if a vision model is installed. Enforce 127.0.0.1 binding, no remote egress, and deterministic settings. Use PS1 probe results to wire this provider when available.
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - vLLM VLM provider is selectable only when local and healthy.
  - Fail closed if endpoint is non-localhost or unavailable.
- **Validation**:
  - Run pipeline with vLLM installed; report shows `vlm.backend: vllm`.

### Task 3.1c: Run all VLM providers (multi-mode)
- **Location**: `contracts/config_schema.json`, `tools/fixture_config_template.json`, `autocapture_nx/kernel/loader.py`
- **Description**: Configure `plugins.capabilities` to run `vision.extractor` in multi/fanout mode so all available VLM providers execute (local model + vLLM + heuristic + any additional local models discovered under `D:\autocapture\models`). Persist per-provider outputs with provider_id and include them in retrieval.
- **Complexity**: 6
- **Dependencies**: Task 3.1b
- **Acceptance Criteria**:
  - Each VLM provider yields its own `derived.text.vlm` record(s).
  - Provider IDs are preserved for citations/diagnostics.
- **Validation**:
  - Run pipeline and confirm multiple VLM provider records.

### Task 3.1d: Local multi-model VLM plugin (D:\autocapture\models)
- **Location**: `plugins/builtin/vlm_local_multi/*`, `tools/run_fixture_pipeline.ps1`, `tools/fixture_config_template.json`
- **Description**: Add a local VLM plugin that enumerates multiple model folders under `D:\autocapture\models` and exposes each as a distinct provider_id within `vision.extractor`. Ensure deterministic settings and offline-only behavior.
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Each discovered local model yields separate VLM outputs.
  - Provider IDs map to model names in report.
- **Validation**:
  - Run pipeline and verify per-model VLM outputs.

### Task 3.1e: GPU/CUDA utilization for VLM
- **Location**: `plugins/builtin/vlm_stub/plugin.py`, `plugins/builtin/vlm_local_multi/*`, `tools/run_fixture_pipeline.ps1`
- **Description**: Ensure VLM providers prefer GPU execution when available (RTX 4090), with deterministic settings and offline-only enforcement. Record device and GPU usage in the fixture report.
- **Complexity**: 6
- **Dependencies**: Task 3.1d
- **Acceptance Criteria**:
  - VLM providers report device backend (cuda) when available.
  - Fixture report includes VLM GPU utilization details.
- **Validation**:
  - Run pipeline and confirm VLM GPU info in report.

### Task 3.2: Enable SST UI parse + structure extractors
- **Location**: `tools/fixture_config_template.json`, `config/default.json` (if needed), plugin enablement
- **Description**: Ensure `builtin.sst.ui.parse` (or `builtin.processing.sst.ui_vlm`) is enabled and `processing.sst.ui_parse.mode` set to use VLM JSON with fallback detector. Enable extract.table/spreadsheet/chart stage plugins if required for queries.
- **Complexity**: 5
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - `derived.sst.state` includes element graph and visible apps.
  - UI element count > 0 for the test screenshot.
- **Validation**:
  - Inspect `derived.sst.state` record(s) in metadata.

### Task 3.3: Enable state_layer for historical queries
- **Location**: `autocapture_nx/processing/state_layer/*`, `tools/fixture_config_template.json`
- **Description**: Enable state_layer processing to support historical queries (e.g., time since last tax accountant contact). Ensure outputs are queryable, bounded, and linked to evidence.
- **Complexity**: 6
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - state_layer produces queryable artifacts beyond OCR/VLM/SST.
  - Budget/gating still enforced.
- **Validation**:
  - Pipeline report shows non-zero artifacts for the third method.

## Sprint 4: Query Accuracy + Validation Loop
**Goal**: Ensure queries are accurate, citable, and enforced via tests.
**Demo/Validation**:
- Run pipeline; `fixture_report.json` shows zero query failures.
- `pytest tests/test_fixture_* -q` passes (or skips only due to optional deps).

### Task 4.0: PromptOps query decomposition + evidence aggregation
- **Location**: `promptops/prompts/*`, `autocapture/promptops/*`, `autocapture_nx/kernel/query.py`
- **Description**: Implement PromptOps templates that decompose each required question into sub-queries and retrieval actions across metadata stores (OCR/VLM/SST/state_layer/OS). Ensure promptops is applied for all fixture queries and produces a deterministic decomposition log in the report.
- **Complexity**: 7
- **Dependencies**: Sprint 1-3
- **Acceptance Criteria**:
  - PromptOps runs for every fixture query and emits sub-queries/actions in the report.
  - Query flow uses PromptOps output to drive retrieval across all metadata stores.
- **Validation**:
  - Run pipeline and verify promptops decomposition output in `fixture_report.json`.

### Task 4.1: Implement query resolvers for required questions
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/ux/facade.py`, `autocapture_nx/processing/*`
- **Description**: Implement resolver logic driven by PromptOps decomposition for: song playing + time left, Chrome window count, remote desktop contents, host app count, and time since last tax accountant contact. Use multi-source evidence (OCR + VLM + SST + OS metadata + state_layer) and return screenshot bbox coordinates for all cited claims; if only OS metadata is available and no bbox match exists, fail closed as indeterminate.
- **Complexity**: 7
- **Dependencies**: Task 4.0
- **Acceptance Criteria**:
  - Each required query returns an answer with bbox-cited evidence or fails closed as indeterminate when evidence is missing or non-local evidence cannot be mapped to a bbox.
  - `match_mode: contains` is respected across sources.
- **Validation**:
  - Run pipeline and verify each required query’s answer with bbox citations.

### Task 4.2: Expand query evaluation and coverage checks

- **Location**: `autocapture_nx/ux/fixture.py`, `tools/run_fixture_pipeline.py`
- **Description**: Fail the run if any explicit query misses, citations or bbox coordinates are missing, or OCR/VLM/SST coverage is below thresholds. Plugin failures only mark the run as degraded (reported) but do not abort. Report which extractor supplied each answer.
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Failures are actionable with extractor diagnostics.
  - All passing answers have citations.
- **Validation**:
  - Run pipeline and verify failure/success behavior.

### Task 4.3: Add deterministic tests for extractor coverage
- **Location**: `tests/test_fixture_*`, new tests as needed
- **Description**: Add tests for VLM availability reporting, OCR backend selection, SST UI parse outputs, required query resolvers, bbox citations, and negative cases (missing model, PolicyGate denial, missing citations, network/bind violations, foreground gating).
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Tests cover OCR/VLM/SST paths deterministically.
- **Validation**:
  - `pytest tests/test_fixture_* -q`

### Task 4.4: Update implementation matrix + coverage map
- **Location**: `docs/reports/implementation_matrix.md`, Coverage_Map docs
- **Description**: Map each requirement to code/test locations (especially VLM + third method + accuracy validation). Ensure MOD-021 test suite alignment.
- **Complexity**: 4
- **Dependencies**: Task 4.3
- **Acceptance Criteria**:
  - Matrix lists modules/tests for each requirement.
- **Validation**:
  - Manual review; MOD-021 test run.

## Testing Strategy
- `python3 tools/validate_fixture_manifest.py --path "docs/test sample/fixture_manifest.json"`
- `python3 tools/run_fixture_pipeline.py --manifest "docs/test sample/fixture_manifest.json"`
- `pytest tests/test_fixture_* -q`
- On Windows PowerShell, use `py -3` (or `python`) instead of `python3`.
- Negative tests: simulate missing OCR/VLM deps, PolicyGate denies, outbound network/bind attempts, missing citations.
- Required queries: validate each required question returns bbox-cited answers (or indeterminate when evidence absent).
- Plugin coverage: verify every enabled plugin ran at least once and report per-plugin results.
- Budget verification: assert CPU/RAM stays ≤50% during fixture run.
- GPU verification: confirm RTX 4090 is used by OCR + VLM providers when available.
- Screensaver gating: verify idle/active decisions track screensaver state (blank screensaver supported).
- Full MOD-021 suite before declaring done.

## Potential Risks & Gotchas
- Missing PIL/RapidOCR on Windows causes empty OCR tokens -> no queries.
- VLM model not available offline; heuristic fallback may be too weak for accuracy.
- UI parse mode misconfigured (detector vs VLM JSON) yields empty element graph.
- PolicyGate denies model/frames access if filesystem policies not updated.
- Localhost-only enforcement not validated (accidental non-127.0.0.1 bind).
- Budgets/gating may block VLM if GPU concurrency set to 0.
- Citations missing if derived artifacts aren’t persisted or indexed.
- Some required queries (e.g., time since tax accountant contact) may be indeterminate from a single screenshot without historical/state_layer evidence.
- Running every plugin may be impossible when dependencies or OS features are missing; fixture should fail closed with explicit diagnostics rather than silently skipping.
- Screensaver detection may be unreliable on some Windows configurations; ensure fallback behavior is explicit and logged.

## Rollback Plan
- Revert fixture config and manifest changes.
- Disable VLM/UI parse plugins and return to OCR-only path.
- Archive/disable new dependency scripts and restore previous plugin locks.
