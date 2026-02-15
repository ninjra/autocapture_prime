# Plan: Screenshot Plugin Full-Run + Query Accuracy

**Generated**: 2026-02-03
**Estimated Complexity**: High

## Overview
Build a Windows-first CLI fixture pipeline that forces all available plugins to run on a known screenshot, captures multi-extractor outputs (OCR + VLM + OS metadata), and returns accurate query answers with bbox-cited evidence. The run must be human-readable end-to-end, report every plugin’s execution status, enforce foreground gating via screensaver, and keep strict security/local-only guarantees (localhost network only, no deletion, raw-first storage, CPU/RAM budgets). The plan prioritizes Performance, Accuracy, Security, and Citeability.

## Prerequisites
- Windows Python environment (no WSL required for normal runs).
- Screenshot + manifest at `D:\projects\autocapture_prime\docs\test sample`.
- Local model root at `D:\autocapture\models`.
- vLLM OpenAI-compatible server running at `http://127.0.0.1:8000` (localhost only).
- CUDA + RTX 4090 drivers; `onnxruntime-gpu` and CUDA-enabled `torch` available.
- No `BLUEPRINT.md` present today; if one appears, fold its SRC requirements into this plan.

## Sprint 1: Fixture Observability + Force-All Plugins
**Goal**: Enable all plugins, capture full execution trace, and output a complete, human-readable step/plugin report without failing the run on individual plugin failures.
**Demo/Validation**:
- Run `tools/run_fixture_pipeline.ps1` on Windows against the test screenshot and confirm `fixture_report.json` includes plugin load report, execution trace, probe results, and a human-readable summary.
- Confirm run completes even if a plugin fails, but marks that plugin as failed.

### Task 1.1: Force-enable all plugins in fixture config
- **Location**: `autocapture_nx/ux/fixture.py`, `tools/fixture_config_template.json`
- **Description**: Build user config with all plugins enabled, conflicts enforcement disabled, and multi-provider policies for OCR/VLM/stage hooks. Add filesystem policy reads for the fixture frames directory and data dir.
- **Complexity**: 4
- **Dependencies**: none
- **Acceptance Criteria**:
  - Generated `user.json` includes `plugins.enabled` for every plugin ID in the lockfile/allowlist.
  - Conflicts enforcement is off for fixture runs.
- **Validation**:
  - Inspect `artifacts/fixture_runs/*/config/user.json` and confirm settings.

### Task 1.2: Add plugin execution trace hook
- **Location**: `autocapture_nx/plugin_system/registry.py`, `autocapture_nx/kernel/loader.py`
- **Description**: Introduce a `PluginExecutionTrace` recorder and inject it into `CapabilityProxy` to record each capability call (plugin_id, capability, method, duration, ok/error). Register it as a system capability (e.g., `observability.plugin_trace`) for fixture use.
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Trace records are available during fixture runs.
  - Trace includes failures with error strings, not just successes.
- **Validation**:
  - Unit test with a stub plugin; verify trace records both success and error cases.

### Task 1.3: Probe every enabled plugin
- **Location**: `autocapture_nx/ux/fixture.py`
- **Description**: Implement a probe harness that attempts at least one call per plugin/capability and records success/failure/no-probe. Use safe, minimal method calls (e.g., `extract_tokens` for OCR, `extract` for VLM, `activity_signal` for tracking) and never crash the run on probe failures.
- **Complexity**: 7
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Every enabled plugin appears in `probe_results` with status and error info if failed.
  - No plugin is silently skipped; failures are explicit.
- **Validation**:
  - Unit test that all enabled plugins are represented even if some fail.

### Task 1.4: Fixture report expansion + failure policy
- **Location**: `tools/run_fixture_pipeline.py`, `autocapture_nx/ux/fixture.py`
- **Description**: Add plugin load report, execution trace summary, and probe results to `fixture_report.json`. Only fail the run for capture or query failures; plugin failures should mark the report as degraded but not exit non-zero.
- **Complexity**: 5
- **Dependencies**: Tasks 1.1–1.3
- **Acceptance Criteria**:
  - `fixture_report.json` includes `plugins.load_report`, `plugins.probe_results`, `plugins.execution_trace` and a human-readable summary string.
  - Load report lists loaded/failed/skipped plugins with reasons (no silent skip).
- **Validation**:
  - Update `tests/test_fixture_pipeline_cli.py` to assert these fields exist.

### Task 1.5: Windows-first PS1 preflight
- **Location**: `tools/run_fixture_pipeline.ps1`
- **Description**: Add preflight checks for vLLM availability, GPU/CUDA visibility, and model root path `D:\autocapture\models`. Print a concise preflight summary and run Python directly on Windows (no WSL by default).
- **Complexity**: 4
- **Dependencies**: Task 1.4
- **Acceptance Criteria**:
  - PS1 reports dependency status before running.
- **Validation**:
  - Manual PS1 run shows preflight results and successful pipeline invocation.

### Task 1.6: Coverage_Map + SRC implementation mapping
- **Location**: `docs/spec/autocapture_nx_blueprint_2026-01-24.md` (Coverage_Map), `docs/reports/implementation_matrix.md` (if present)
- **Description**: Add/extend Coverage_Map entries for every requirement implemented in this plan, referencing module/ADR/test. If no SRC identifiers exist for this scope, create a minimal mapping section in the implementation matrix and reference it from the spec.
- **Complexity**: 4
- **Dependencies**: Tasks 1.1–1.5
- **Acceptance Criteria**:
  - Every new requirement in this plan is traceable to module + test references.
- **Validation**:
  - `python tools/validate_blueprint_spec.py` (or equivalent spec validator) passes.

### Task 1.7: Deterministic tests for config + preflight changes
- **Location**: `tests/test_fixture_pipeline_cli.py`, new test module for config builder
- **Description**: Add deterministic tests for fixture config generation (all plugins enabled, conflict enforcement disabled) and PS1 preflight config parity (assert PS1 uses the same manifest/config paths as Python CLI).
- **Complexity**: 5
- **Dependencies**: Tasks 1.1–1.5
- **Acceptance Criteria**:
  - Config builder test validates plugin enablement + policies.
  - Preflight path expectations are asserted without running external tools.
- **Validation**:
  - `pytest tests/test_fixture_pipeline_cli.py -q` plus the new test module.

## Sprint 2: Screensaver Gating + OS Metadata Expansion
**Goal**: Switch user-activity gating to screensaver detection and capture comprehensive window/app metadata for query inference.
**Demo/Validation**:
- Toggle the blank screensaver and confirm the runtime governor blocks idle processing when screensaver is inactive and allows it when active.
- Confirm window enumeration records multiple open apps and Chrome windows.

### Task 2.1: Screensaver detection module
- **Location**: `autocapture_nx/windows/screensaver.py`
- **Description**: Add `screensaver_running()` using `SystemParametersInfoW(SPI_GETSCREENSAVERRUNNING)` via `ctypes`.
- **Complexity**: 3
- **Dependencies**: none
- **Acceptance Criteria**:
  - Returns True/False reliably on Windows with a blank screensaver.
- **Validation**:
  - Unit test with monkeypatch for ctypes return values.

### Task 2.2: Use screensaver in activity_signal
- **Location**: `plugins/builtin/input_windows/plugin.py`, `contracts/config_schema.json`, `config/default.json`, `tools/fixture_config_template.json`
- **Description**: Replace display-power gating with screensaver-based gating; add config keys `runtime.activity.screensaver_enabled`, `screensaver_poll_interval_s`, `screensaver_idle_seconds`. Expose `screensaver_on` + `screensaver_idle_seconds` in `activity_signal()`.
- **Complexity**: 4
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - When screensaver is active, `user_active` is false and idle_seconds is large.
- **Validation**:
  - Update `tests/test_fixture_runtime_gating.py` for screensaver gating.

### Task 2.3: Enumerate visible windows/apps
- **Location**: `autocapture_nx/windows/win_window.py`, `plugins/builtin/window_metadata_windows/plugin.py`
- **Description**: Add `list_windows()` using `EnumWindows` and filter to visible, non-minimized top-level windows. Include title, process path, hwnd, rect, and monitor. Update plugin to emit periodic snapshot records of visible windows/apps (no deletions). Add audit logging for the new privileged enumeration.
- **Complexity**: 6
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Metadata contains a list of visible windows with rects for bbox mapping.
- **Validation**:
  - Unit test with injected fake window list; fixture report includes window count.

### Task 2.4: Surface OS metadata to query pipeline
- **Location**: `autocapture_nx/kernel/query.py` or new query resolver module
- **Description**: Ensure query logic can access window snapshots to answer app/window counts and map window titles to screenshot regions.
- **Complexity**: 5
- **Dependencies**: Task 2.3
- **Acceptance Criteria**:
  - Query resolver can count Chrome windows and total apps from metadata.
- **Validation**:
  - Add deterministic unit tests with mocked metadata.

### Task 2.5: Foreground gating enforcement for non-capture work
- **Location**: `autocapture_nx/ux/fixture.py`, `autocapture/runtime/governor.py` (or wrapper), `autocapture_nx/kernel/query.py`
- **Description**: Enforce the non-negotiable rule: when the user is active (screensaver off), only capture + kernel are allowed. Ensure idle processing, plugin probes, and on-query extraction respect the governor decision. Add an explicit, audited fixture override if needed (opt-in only).
- **Complexity**: 6
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - With screensaver off, probes/idle processing do not execute.
  - With screensaver on, probes/idle processing proceed.
- **Validation**:
  - Add tests that simulate screensaver state and assert processing is blocked/allowed.

### Task 2.6: CPU/RAM budget enforcement for fanout work
- **Location**: `autocapture/runtime/governor.py`, `autocapture_nx/processing/idle.py`, `autocapture_nx/ux/fixture.py`
- **Description**: Ensure CPU/RAM budgets (<= 50%) are enforced for multi-provider OCR/VLM fanout and plugin probes. Add governor checks before and during heavy work.
- **Complexity**: 5
- **Dependencies**: Task 2.5
- **Acceptance Criteria**:
  - Fixture run reports budget decisions and does not exceed configured limits.
- **Validation**:
  - Unit test with mocked resource utilization to verify gating.

### Task 2.7: Time-ordered processing for out-of-order media
- **Location**: `plugins/builtin/capture_stub/plugin.py`, `autocapture_nx/processing/idle.py`, `autocapture_nx/kernel/query.py`
- **Description**: Preserve original timestamps when ingesting files (parse filename timestamps or use file mtime) and process evidence in chronological order rather than record-id order. Ensure state/retrieval time windows are correct even when media arrives out of order.
- **Complexity**: 6
- **Dependencies**: Task 2.6
- **Acceptance Criteria**:
  - Fixture pipeline respects file timestamp order; derived records use correct `span_ref` times.
- **Validation**:
  - Add tests with shuffled file inputs and assert ordering by timestamp.

## Sprint 3: Multi OCR/VLM + GPU-first Execution
**Goal**: Run multiple OCR and VLM providers in parallel, store all outputs, and prefer CUDA on RTX 4090.
**Demo/Validation**:
- Fixture run shows multiple OCR/VLM providers executed with individual results.
- GPU usage reported in fixture report when CUDA available.

### Task 3.1: RapidOCR + Tesseract plugins
- **Location**: `plugins/builtin/ocr_rapid/*`, `plugins/builtin/ocr_tesseract/*`, `autocapture/ingest/ocr_basic.py`
- **Description**: Add standalone OCR plugins for RapidOCR and Tesseract with consistent token+bbox output. Refactor `ocr_basic` to support explicit backend selection and reuse shared token conversion.
- **Complexity**: 7
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - `ocr.engine` fanout includes all three backends (basic, rapid, tesseract).
- **Validation**:
  - Unit test for provider registration and output schema.

### Task 3.2: vLLM OpenAI-compat VLM plugin (localhost-only)
- **Location**: `plugins/builtin/vlm_openai_compat/*`, `config/default.json`
- **Description**: Implement a VLM plugin calling a vLLM OpenAI-compatible image-to-text API via localhost only. Enforce localhost in code and allow network permission for this plugin ID.
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Requests are blocked if host is not 127.0.0.1.
- **Validation**:
  - Unit test for host validation and error handling.

### Task 3.3: Local multi-model VLM plugin
- **Location**: `plugins/builtin/vlm_local_multi/*`
- **Description**: Scan `D:\autocapture\models` for compatible local VLMs and run multiple models (GPU if available). Return per-model outputs.
- **Complexity**: 8
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Fixture report lists outputs per model without crashing if a model fails.
- **Validation**:
  - Unit test with a toy local model bundle fixture.

### Task 3.4: Flatten nested multi-providers
- **Location**: `autocapture_nx/processing/idle.py`, `autocapture_nx/kernel/query.py`, `autocapture_nx/ux/facade.py`, `autocapture_nx/processing/sst/extract.py`
- **Description**: Enhance provider discovery to flatten nested `items()` so local multi-model providers are fully fanned out.
- **Complexity**: 5
- **Dependencies**: Task 3.3
- **Acceptance Criteria**:
  - All nested providers appear in execution trace and derived records.
- **Validation**:
  - Unit test verifying flattening.

### Task 3.5: GPU routing + config updates
- **Location**: `tools/fixture_config_template.json`, `config/default.json`
- **Description**: Enable VLM in idle/on-query; set capability policies for multi-provider fanout; prefer GPU routing for heavy tasks. Record GPU info in fixture report.
- **Complexity**: 4
- **Dependencies**: Tasks 3.1–3.4
- **Acceptance Criteria**:
  - `fixture_report.json` includes GPU device info and per-provider backend info.
- **Validation**:
  - Manual fixture run on RTX 4090 shows CUDA usage.

### Task 3.5b: Model prep + vLLM serve/warm (Windows PS1)
- **Location**: new `tools/model_prep.ps1` (or extend `tools/run_fixture_pipeline.ps1`), new `tools/model_manifest.json`
- **Description**: Add a Windows PowerShell helper that populates `D:\\autocapture\\models\\` with required HF models (via `huggingface-cli` or `git lfs`) and verifies a local vLLM OpenAI-compatible server is running on localhost. Warm models before the fixture run. Report each model status explicitly (no silent skip).
- **Complexity**: 5
- **Dependencies**: Task 3.5
- **Acceptance Criteria**:
  - Script downloads all listed models into `D:\\autocapture\\models\\<model_id>` and validates all vLLM models are served.
  - Script validates vLLM is running and confirms models are ready.
- **Validation**:
  - Manual PS1 run shows per-model success/failure with clear reasons.

### Task 3.6: Plugin lockfile + permissions
- **Location**: `config/plugin_locks.json`, `config/default.json`
- **Description**: Add new plugin IDs to allowlist and lockfile; grant network permission to vLLM OpenAI-compatible plugin only; keep localhost-only.
- **Complexity**: 3
- **Dependencies**: Tasks 3.1–3.3
- **Acceptance Criteria**:
  - `autocapture_nx plugins approve` succeeds; no lockfile mismatch.
- **Validation**:
  - Run lockfile update and verify no load failures.

### Task 3.7: PolicyGate + sandbox enforcement for new plugins
- **Location**: `autocapture_nx/state_layer/policy_gate.py`, `autocapture_nx/plugin_system/registry.py`, new plugin manifests
- **Description**: Ensure new OCR/VLM plugins are treated as untrusted inputs and pass through PolicyGate checks. Add/verify filesystem policies and sandbox guards for each new plugin (read-only model dirs, no external network).
- **Complexity**: 5
- **Dependencies**: Tasks 3.1–3.3
- **Acceptance Criteria**:
  - PolicyGate blocks unsafe exports; plugin file/network access is constrained to allowed paths/localhost.
- **Validation**:
  - Add tests that attempt disallowed access and confirm the plugin is blocked.

### Task 3.8: Audit logging for privileged behaviors
- **Location**: `autocapture_nx/kernel/audit.py`, new plugins (`vlm_openai_compat`, `vlm_local_multi`)
- **Description**: Append audit events for network access to vLLM and for model directory scanning (privileged file reads). Ensure audit logs are append-only.
- **Complexity**: 4
- **Dependencies**: Tasks 3.2–3.3
- **Acceptance Criteria**:
  - Audit log contains entries for each privileged action during fixture runs.
- **Validation**:
  - Unit test verifies audit log entries are created.

## Sprint 4: Query Decomposition + BBox-Cited Answers
**Goal**: Break queries into promptops sub-queries, resolve answers from OCR/VLM/OS metadata, and return human-readable answers with bbox citations.
**Demo/Validation**:
- Explicit queries in the manifest return correct answers with bbox coordinates and citations.

### Task 4.1: PromptOps query decomposition
- **Location**: `promptops/prompts/*`, `autocapture/promptops/engine.py` (or `autocapture_nx/kernel/query.py`)
- **Description**: Add prompt templates and logic to decompose queries into sub-queries/filters, store decomposition output in fixture report, and use it to guide retrieval.
- **Complexity**: 6
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Fixture report includes decomposition steps.
- **Validation**:
  - Unit test for decomposition on a known query.

### Task 4.2: Implement query resolvers for required questions
- **Location**: new module e.g. `autocapture_nx/query/fixture_resolvers.py`
- **Description**: Add resolvers for:
  - song playing + time remaining
  - number of Chrome windows
  - content inside Remote Desktop window
  - number of open host apps
  - time since last message from tax accountant (inference from screen timestamps)
  Use OCR/VLM tokens, window metadata, and state-layer evidence. Return answers with bbox references.
- **Complexity**: 9
- **Dependencies**: Sprint 2 + Sprint 3 + Task 4.1
- **Acceptance Criteria**:
  - Each query returns a human-readable answer with at least one bbox citation.
- **Validation**:
  - Add deterministic tests using fixture screenshot and expected outputs.

### Task 4.2b: Multi-model adjudication layer (best-of + consensus)
- **Location**: `autocapture_nx/query/ensemble.py`, `autocapture_nx/kernel/query.py`
- **Description**: Run all OCR/VLM providers and store all outputs; add a scoring layer that selects the best evidence per query based on confidence, coverage, cross-model agreement, and alignment with OS metadata/layout. Always keep full provenance and include alternatives when the score gap is small.
- **Complexity**: 6
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Query answers cite the highest-scoring evidence while preserving all model outputs.
- **Validation**:
  - Unit test with synthetic disagreements verifying stable selection.

### Task 4.3: Preserve bbox evidence in answers
- **Location**: `autocapture_nx/kernel/derived_records.py`, `plugins/builtin/answer_basic/plugin.py`, `autocapture_nx/ux/fixture.py`
- **Description**: Extend derived records or claims to include bbox spans (pixel coords + normalized coords). Update answer builder to preserve bbox fields and update fixture evaluation to require bbox evidence for explicit queries.
- **Complexity**: 7
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Claims include bbox coordinates associated with citations.
- **Validation**:
  - Fixture query test asserts bbox fields exist.

### Task 4.4: Add explicit queries to manifest
- **Location**: `docs/test sample/fixture_manifest.json`
- **Description**: Add explicit queries for the five required questions with `match_mode: contains`, `require_citations: true`, `require_state: ok`.
- **Complexity**: 3
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Fixture run evaluates explicit queries in addition to auto queries.
- **Validation**:
  - Confirm `fixture_report.json` includes these queries and results.

### Task 4.4b: Derive ground-truth answers from the screenshot
- **Location**: `docs/test sample/fixture_manifest.json`, new test expectations file (e.g., `tests/fixtures/fixture_expected_answers.json`)
- **Description**: Determine the correct answers by inspecting the fixture screenshot (no fabricated values). Populate explicit expected answers + supporting bbox references for tests. This step is required because the user will not supply answers.
- **Complexity**: 5
- **Dependencies**: Task 4.4
- **Acceptance Criteria**:
  - Expected answers are grounded in the screenshot content and used in deterministic tests.
- **Validation**:
  - Tests fail if any answer deviates from the screenshot content.

### Task 4.5: Storage growth reporting
- **Location**: `tools/run_fixture_pipeline.py`, `autocapture_nx/ux/fixture.py`
- **Description**: Add storage growth summary and recommendations when multiple OCR/VLM outputs increase storage footprint. Recommendations must be archive/migrate only (no deletion/pruning).
- **Complexity**: 3
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Report lists per-provider storage impact and a recommendation if growth exceeds thresholds.
- **Validation**:
  - Unit test with mocked sizes.

### Task 4.6: Citeability defaults + “uncitable” state
- **Location**: `plugins/builtin/answer_basic/plugin.py`, `autocapture_nx/kernel/query.py`
- **Description**: Enforce citations by default. When evidence is missing/insufficient, return a clear “uncitable/indeterminate” answer state and avoid fabricating claims.
- **Complexity**: 4
- **Dependencies**: Task 4.3
- **Acceptance Criteria**:
  - Queries without evidence produce a deterministic uncitable state and no claims.
- **Validation**:
  - Unit test for no-evidence query path.

### Task 4.7: Raw-first storage compliance
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/state_layer/policy_gate.py`, `config/default.json`
- **Description**: Ensure local storage and query pipelines keep raw outputs unfiltered; sanitization only occurs on explicit export/egress. Add a compliance check to fixture report.
- **Complexity**: 4
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - No sanitization is applied to local derived records; export paths remain the only sanitization boundary.
- **Validation**:
  - Unit test asserting local derived records are not altered.

## Testing Strategy
- Unit tests for plugin trace/probe, screensaver gating + foreground blocking, CPU/RAM budget enforcement, multi-provider flattening, OCR/VLM providers, PolicyGate/sandbox, audit logging, and query resolvers.
- Integration tests: `tests/test_fixture_pipeline_cli.py`, `tests/test_fixture_runtime_gating.py`, new fixture query tests using the screenshot.
- Regression check: tray behavior unchanged (no capture pause/delete actions).
- Ensure MOD-021 test suites pass and Coverage_Map is satisfied.

## Potential Risks & Gotchas
- CUDA libraries not available on CI; tests must skip GPU-specific checks gracefully.
- Plugin lockfile updates can cause load failures if hashes aren’t refreshed.
- Multi-provider fanout can duplicate or conflict results; ensure deterministic ordering and clear provenance tags.
- Screenshot scaling or DPI differences may skew bbox mapping; include normalization and screen DPI handling.
- vLLM network permission must remain localhost-only or plugin load should fail closed.
- Foreground gating/fixture overrides could accidentally allow processing when user is active; keep overrides explicit and audited.

## Rollback Plan
- Revert new plugin directories and lockfile changes.
- Restore prior fixture config and remove new report fields.
- Disable multi-provider fanout and revert to single OCR/VLM provider.
