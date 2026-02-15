# Plan: Screenshot CLI Fixture Pipeline

**Generated**: 2026-02-02
**Estimated Complexity**: Medium

## Overview
Build a CLI-only fixture harness that ingests a known screenshot (from `docs/test sample`), runs it through the real capture + plugin pipeline, performs idle/on-demand processing, and validates query accuracy with citations. The harness must respect non‑negotiables (localhost-only, no deletion, raw-first, foreground gating, idle budgets, citations) and enforce full‑fidelity capture. Results should be deterministic, auditable, and verifiable. No new blueprint authoring is required; only traceability updates for new modules/tests.

## Prerequisites
- Confirm which screenshot file(s) to use in `D:\projects\autocapture_prime\docs\test sample` and expected Q/A targets.
- Confirm OCR dependency expectations (Pillow required; ONNX/RapidOCR preferred; Tesseract fallback optional).
- Confirm whether WSL is available for PowerShell wrapper execution.

## Sprint 1: Fixture Definition + Config Overlay
**Goal**: Define the fixture inputs/expected outputs and a safe, deterministic config overlay for the pipeline run.
**Demo/Validation**:
- `python -m autocapture_nx config show` with overlay env vars prints expected overrides.
- Fixture manifest validates paths and expected queries.

### Task 1.1: Traceability + coverage mapping (no new blueprint authoring)
- **Location**: `docs/spec/autocapture_nx_blueprint_2026-01-24.md`, `docs/reports/implementation_matrix.md`, `docs/reports/blueprint-gap-2026-02-02.md`
- **Description**: Map the fixture pipeline coverage to SRC items (likely SRC-037/038/039/041/068/044/116) and ensure each new module/test has a traceability reference. No new blueprint file creation.
- **Complexity**: 3
- **Dependencies**: none
- **Acceptance Criteria**:
  - Coverage_Map references include new harness/test artifacts.
- **Validation**:
  - `pytest tests/test_blueprint_spec_validation.py -q`

### Task 1.2: Fixture manifest + expected queries
- **Location**: `docs/test sample/fixture_manifest.json` (new), `docs/test sample/README.md` (new)
- **Description**: Enumerate screenshot file(s) and define expected query/answer targets. Support two modes: (a) explicit expected text/app/window tokens, and (b) auto‑generated query suite from extracted tokens + window metadata. Exact match is required; if OCR noise makes this too brittle, use deterministic normalization (casefold + whitespace collapse) and document rationale.
- **Complexity**: 3
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Manifest includes screenshot path(s), queries, and expected match rules.
  - README explains how expected values were chosen.
- **Validation**:
  - `python tools/validate_fixture_manifest.py --path "docs/test sample/fixture_manifest.json"` (new tool)

### Task 1.3: Deterministic overlay config for fixture runs
- **Location**: `tools/fixture_config_template.json` (new)
- **Description**: Create a user‑config overlay that enables stub capture + OCR/VLM, disables live OS capture, sets anchor frequency to 1, forces idle eligibility (assume idle when input tracker missing), enforces CPU/RAM budgets (<=50%), and isolates `data_dir`/index paths under an artifacts run dir. Explicitly set localhost‑only web bindings and keep raw‑first local storage (no local redaction). Force full‑fidelity capture: PNG frames (or RGB) with lossless container (zip/png or ffmpeg_lossless+rgb).
- **Complexity**: 4
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Overlay passes schema validation.
  - Overlay enforces raw‑first local storage, localhost‑only binding, and no deletion semantics.
  - Overlay caps `runtime.budgets.cpu_max_utilization` and `ram_max_utilization` at 0.5.
  - Overlay forces lossless capture settings.
- **Validation**:
  - `python -m autocapture_nx config show` with `AUTOCAPTURE_CONFIG_DIR` pointing to overlay dir.

## Sprint 2: CLI Fixture Runner + PS1 Wrapper
**Goal**: Implement a CLI-only runner that ingests the fixture screenshot, runs processing, and validates query accuracy + citations.
**Demo/Validation**:
- `tools/run_fixture_pipeline.ps1 -InputDir "D:\projects\autocapture_prime\docs\test sample"` exits 0 and prints a report.

### Task 2.1: Python fixture runner (ingest → process → query)
- **Location**: `tools/run_fixture_pipeline.py` (new), `autocapture_nx/ux/fixture.py` (new helper)
- **Description**: Implement a runner that:
  - Creates a temp config dir (user.json) from the overlay template.
  - Sets `AUTOCAPTURE_CONFIG_DIR` + `AUTOCAPTURE_DATA_DIR` to run‑scoped paths.
  - Boots kernel/plugins; runs capture stub over the fixture frames (finite source).
  - Runs idle processing to create derived artifacts and indexes.
  - Executes queries from the manifest and validates: answer.state == ok, citations resolve, expected text tokens appear. In auto mode, generate a deterministic query suite from extracted tokens (min length, unique, stopword‑filtered) + window metadata and validate all queries return exact‑match hits with citations.
  - Writes a JSON report and non‑zero exit on failures.
  - Does not delete evidence/config; archives only.
- **Complexity**: 6
- **Dependencies**: Task 1.3
- **Acceptance Criteria**:
  - Runner uses real plugin system + capture pipeline (no bypass) and respects PolicyGate/sandbox constraints.
  - Failure modes are explicit (missing evidence, missing citations, OCR mismatch).
  - No automatic deletion of fixture evidence/config artifacts.
- **Validation**:
  - `python tools/run_fixture_pipeline.py --manifest "docs/test sample/fixture_manifest.json"`

### Task 2.2: PowerShell wrapper for Windows/WSL
- **Location**: `tools/run_fixture_pipeline.ps1` (new)
- **Description**: Add a PS1 wrapper that resolves Windows paths → WSL paths, calls the Python runner, and preserves exit codes. Provide flags for input dir, manifest, and output dir.
- **Complexity**: 3
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Works with `D:\...` paths and spaces (e.g., `docs\test sample`).
  - Emits a clear pass/fail summary.
- **Validation**:
  - Manual run from PowerShell.

### Task 2.3: Full‑fidelity stub frame output (default)
- **Location**: `plugins/builtin/capture_stub/plugin.py`, `config/fixture_config_template.json`
- **Description**: Make lossless output the default for stub capture. Add `capture.stub.frame_format=png` (or `lossless=true`) and align `capture.video.frame_format`/container for zip+png (or ffmpeg_lossless+rgb) to avoid lossy JPEG during fixture runs.
- **Complexity**: 4
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Stub emits PNG frames by default; pipeline accepts zip+png.
  - OCR accuracy improves or remains stable on fixture.
- **Validation**:
  - Runner executes with `frame_format=png` and produces evidence + derived text.

### Task 2.4: Audit logging for fixture runs
- **Location**: `autocapture_nx/ux/fixture.py`, `autocapture_nx/kernel/audit.py`
- **Description**: Append audit events for fixture ingest/process/query with actor `tools.fixture`, including input paths, run_id, config overlay hash, and outcome. Explicitly log any privileged behavior (config overrides, lossless stub mode changes).
- **Complexity**: 2
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Audit log contains entries for fixture actions and config override usage.
- **Validation**:
  - Inspect `artifacts/audit/audit.jsonl` for new events.

### Task 2.5: OCR provider selection (best for 4 pillars)
- **Location**: `plugins/builtin/ocr_stub/*`, `plugins/builtin/sst_ocr_onnx/*`, `tools/fixture_config_template.json`
- **Description**: Prefer ONNX/RapidOCR if available for deterministic offline OCR; otherwise fall back to `builtin.ocr.basic` (Tesseract if installed, deterministic fallback otherwise). Make the choice explicit in overlay and report. Ensure no network usage.
- **Complexity**: 4
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - OCR provider selection is deterministic and recorded in the report.
  - No network access required for OCR.
- **Validation**:
  - Fixture runner report includes OCR provider and model details.

## Sprint 3: Tests + Coverage + Docs
**Goal**: Add deterministic tests and update blueprint coverage/Docs.
**Demo/Validation**:
- `pytest tests/test_fixture_pipeline_cli.py -q`

### Task 3.1: Deterministic integration test
- **Location**: `tests/test_fixture_pipeline_cli.py` (new)
- **Description**: Generate a small PNG with known text using Pillow, run the fixture runner in‑process (or via subprocess), and assert:
  - derived text exists,
  - query returns `state=ok`,
  - citations resolve and include anchor.
- **Complexity**: 5
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Test passes deterministically without external services.
- **Validation**:
  - `pytest tests/test_fixture_pipeline_cli.py -q`

### Task 3.2: Citation/anchor verification test
- **Location**: `tests/test_fixture_citations_anchor.py` (new)
- **Description**: Ensure fixture queries fail if anchors are missing and pass when `anchor.every_entries=1` is set in the overlay.
- **Complexity**: 4
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Explicit test for citation failure modes and success path.
- **Validation**:
  - `pytest tests/test_fixture_citations_anchor.py -q`

### Task 3.3: Foreground gating + raw‑first validation tests
- **Location**: `tests/test_fixture_runtime_gating.py` (new)
- **Description**: Add a test that simulates an active user signal and asserts scheduler mode `ACTIVE_CAPTURE_ONLY` (no idle processing). Also assert raw‑first local storage disables compliance redaction for fixture runs.
- **Complexity**: 4
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Active-user path blocks idle processing.
  - Raw‑first local storage keeps derived text unredacted.
- **Validation**:
  - `pytest tests/test_fixture_runtime_gating.py -q`

### Task 3.4: Auto‑query coverage test
- **Location**: `tests/test_fixture_query_coverage.py` (new)
- **Description**: Use a generated PNG with multiple distinct tokens and window metadata, run auto‑query mode, and assert each token query returns an exact‑match hit with citations.
- **Complexity**: 4
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Auto‑query mode detects coverage gaps deterministically.
- **Validation**:
  - `pytest tests/test_fixture_query_coverage.py -q`

### Task 3.5: Update coverage map and docs
- **Location**: `docs/reports/implementation_matrix.md`, `docs/spec/autocapture_nx_blueprint_2026-01-24.md`, `docs/reports/blueprint-gap-2026-02-02.md`, `README.md`
- **Description**: Map new harness/tests to SRC items (candidate‑first extraction, derived records, citations/anchors, foreground gating, budgets, auto‑query coverage). Include per‑module/test SRC references per protocol. Document CLI usage and expected outputs.
- **Complexity**: 3
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Coverage_Map updated with module/test references.
  - README includes a CLI fixture example.
- **Validation**:
  - `pytest tests/test_blueprint_spec_validation.py -q`

## Testing Strategy
- Unit/integration: `pytest tests/test_fixture_pipeline_cli.py -q`, `pytest tests/test_fixture_citations_anchor.py -q`, `pytest tests/test_fixture_runtime_gating.py -q`, `pytest tests/test_fixture_query_coverage.py -q`.
- Gate: `python tools/run_all_tests.py` (or `tools/run_all_tests.ps1` on Windows); confirm MOD-021 suites (lexical index tests) pass.
- Manual: `tools/run_fixture_pipeline.ps1 -InputDir "D:\projects\autocapture_prime\docs\test sample"` and verify JSON report + citations.

## Potential Risks & Gotchas
- **Citations missing**: Anchor frequency too low; set `storage.anchor.every_entries=1` for fixture runs.
- **OCR accuracy**: Ensure ONNX/RapidOCR is preferred; if unavailable, fallback may reduce accuracy—report gaps and trigger plugin work.
- **Foreground gating**: If input tracker reports activity, idle processing will not run; set `runtime.activity.assume_idle_when_missing=true` and disable tracking plugins for fixture runs.
- **Localhost-only**: Ensure `web.bind_host=127.0.0.1` and `web.allow_remote=false` in overlay even if web is unused.
- **Raw-first local**: Verify compliance redaction remains disabled for fixture runs.
- **Path translation**: Spaces in `docs\test sample` require careful quoting; use PS1 wrapper to normalize.
- **Plugin enablement**: Stub capture/OCR/VLM must be enabled in overlay or pipeline will silently skip.

## Rollback Plan
- Revert new tools/scripts/tests and remove overlay template.
- Leave any generated fixture data under `artifacts/` (do not delete evidence); optionally archive by moving to a dated subfolder.
