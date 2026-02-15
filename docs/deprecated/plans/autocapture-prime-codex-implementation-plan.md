# Plan: Autocapture Prime Codex Implementation

**Generated**: 2026-02-14  
**Estimated Complexity**: High

## Overview
Implement the requirements in `docs/autocapture_prime_codex_implementation.md` with strict alignment to current repo policy:
- capture remains sidecar-owned (Windows),
- this repo remains processing/index/query focused,
- localhost-only model/API networking,
- no tactical question-specific logic.

This plan explicitly resolves spec overlap with current docs:
- `docs/processing-only-plugin-stack.md`
- `docs/windows-sidecar-capture-interface.md`
- `docs/AutocapturePrime_4Pillars_Upgrade_Plan.md`

## Assumptions (Explicit)
- Sidecar continues owning capture + ingest writes on Windows.
- This repo may add a spool-session ingestion adapter for chronicle-v0 bundles, but will not reintroduce capture plugins.
- vLLM/OpenAI-compatible server is external at `127.0.0.1:8000`.
- Existing plugin architecture (`autocapture_nx` + `plugins/builtin/*`) is the primary extension surface.

## Skills Used
- `plan-harder`: phased, atomic implementation plan.
- `shell-lint-ps-wsl`: shell policy and command linting compliance.

If skill selection changes during implementation, log the change in the execution notes at the top of each implementation PR.

## Prerequisites
- Stable sidecar DataRoot contract and/or chronicle spool fixture bundle.
- `protoc` toolchain available for protobuf generation tests.
- Python deps for zstd/protobuf/parquet/duckdb/faiss available in CI/test images.
- vLLM endpoint healthable on `127.0.0.1:8000`.

## Sprint 1: Contract + Architecture Alignment
**Goal**: Introduce chronicle-v0 contract support without violating processing-only boundaries.  
**Demo/Validation**:
- Contract files exist and are pinned.
- CI fails on contract drift.
- No capture plugin re-enable regressions.

### Task 1.1: Add Chronicle Contract Artifacts
- **Location**: `contracts/chronicle/v0/chronicle.proto`, `contracts/chronicle/v0/spool_format.md`
- **Description**: Add spec-defined contract files verbatim with append-only notes.
- **Complexity**: 3
- **Dependencies**: none
- **Acceptance Criteria**:
  - Files present and referenced from docs.
  - Proto compiles in local validation.
- **Validation**:
  - New test: `tests/test_chronicle_proto_compiles.py`

### Task 1.2: Add Proto Codegen Pipeline + Generated Artifact Gate
- **Location**: `tools/chronicle_codegen.sh` (or repo-standard codegen script), generated module path, CI workflow
- **Description**: Add deterministic `protoc` codegen, package generated Python module, and gate CI on fresh codegen output.
- **Complexity**: 5
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Generated module is present before Sprint 3 ingestion work lands.
  - CI fails if generated code is stale/missing.
- **Validation**:
  - `tests/test_chronicle_proto_compiles.py` + new `tests/test_chronicle_codegen_fresh.py`

### Task 1.3: Add Contract Drift Pin Gate
- **Location**: `contracts/chronicle/v0/*.sha256`, `tools/gate_contract_pins.py`, CI test wiring
- **Description**: Pin SHA-256 for chronicle contract directory and fail on drift.
- **Complexity**: 4
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Contract edits require explicit lock refresh.
- **Validation**:
  - New test: `tests/test_chronicle_contract_pin.py`

### Task 1.4: Reconcile Spec With Sidecar-Only Capture Policy
- **Location**: `docs/windows-sidecar-capture-interface.md`, `docs/processing-only-plugin-stack.md`, `docs/plans/implementation-matrix*.md`
- **Description**: Add explicit note that chronicle spool ingest is an additional input mode; capture remains deprecated in this repo.
- **Complexity**: 2
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - No contradictory docs on capture ownership.
- **Validation**:
  - Doc consistency checklist in matrix refresh.

### Task 1.5: Add Sidecar-Only Capture Enforcement Test
- **Location**: `tests/test_capture_plugins_deprecated_enforced.py`, optional runtime guard in CLI/router
- **Description**: Add a hard regression test that fails if capture entrypoints/flags are re-enabled in this repo.
- **Complexity**: 4
- **Dependencies**: Task 1.4
- **Acceptance Criteria**:
  - CI fails if capture mode is accidentally reintroduced.
- **Validation**:
  - New policy regression test in default CI suite.

## Sprint 2: Config + Preflight + Runtime Guards
**Goal**: Add chronicle-specific config and hard runtime guardrails for 4 pillars.  
**Demo/Validation**:
- New config loads via existing schema pipeline.
- Preflight reports GPU/vLLM/spool readiness with actionable failure text.

### Task 2.1: Add Autocapture Prime Config Surface
- **Location**: `config/autocapture_prime.yaml`, `config/example.autocapture_prime.yaml`, schema wiring in config loaders
- **Description**: Add spec fields for spool ingest, OCR/layout, indexing, vLLM, API, privacy flags.
- **Complexity**: 5
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Config validates and merges with current defaults.
  - Safe defaults preserve current behavior.
- **Validation**:
  - New test: `tests/test_autocapture_prime_config_schema.py`

### Task 2.2: Add Preflight Script + Programmatic Health Hooks
- **Location**: `scripts/preflight.sh`, optional `tools/preflight_runtime.py`
- **Description**: Check `nvidia-smi`, loopback vLLM health, spool path access, and fail-closed messages.
- **Complexity**: 4
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Preflight returns non-zero on missing prerequisites with structured reason codes.
- **Validation**:
  - New test: `tests/test_preflight_runtime_checks.py`

### Task 2.3: Wire Preflight Into CI Merge Gates
- **Location**: CI workflow config, `tools/gate_phase*.py` integration
- **Description**: Add required CI stage that runs preflight checks in test mode before merge.
- **Complexity**: 3
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Merge blocked when vLLM/GPU/spool prerequisites are not satisfiable in declared environment.
- **Validation**:
  - CI job artifacts show structured preflight status codes.

### Task 2.4: Enforce Localhost-Only and Privacy Defaults
- **Location**: `autocapture_nx/inference/vllm_endpoint.py`, plugin settings defaults, policy docs
- **Description**: Keep localhost-only networking and default `privacy.allow_mm_embeds=false`.
- **Complexity**: 3
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Any non-loopback VLM/API endpoint is rejected.
- **Validation**:
  - Existing + extended tests for endpoint policy.

## Sprint 3: Chronicle Spool Ingestion Pipeline
**Goal**: Read completed spool sessions and normalize to internal evidence/derived records.  
**Demo/Validation**:
- Ingest a fixture session marked by `COMPLETE.json`.
- Emit normalized records and media references with stable IDs.

### Task 3.1: Implement SessionScanner
- **Location**: `autocapture_nx/ingest/chronicle/session_scanner.py`
- **Description**: Enumerate `session_*`, require `COMPLETE.json`, track idempotent processed state.
- **Complexity**: 5
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Incomplete sessions are ignored.
  - Re-runs are idempotent.
- **Validation**:
  - New test: `tests/test_chronicle_session_scanner.py`

### Task 3.2: Implement SessionLoader + Zstd/Proto Decoding
- **Location**: `autocapture_nx/ingest/chronicle/session_loader.py`, generated proto module location
- **Description**: Load `manifest.json`, decode `meta/*.pb.zst`, expose iterators for frames/input/detections.
- **Complexity**: 7
- **Dependencies**: Task 3.1, Task 1.2
- **Acceptance Criteria**:
  - Can parse fixture meta files and produce deterministic row counts.
- **Validation**:
  - New test: `tests/test_chronicle_session_loader.py`

### Task 3.3: Implement FrameDecoder + Time/Coordinate Normalization
- **Location**: `autocapture_nx/ingest/chronicle/frame_decoder.py`, `autocapture_nx/ingest/chronicle/normalize.py`
- **Description**: Decode PNG first, optional segment path hooks; normalize QPC-relative timestamps and desktop-space boxes.
- **Complexity**: 6
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Accurate `t_rel_s` from qpc ticks.
  - DPI metadata retained.
- **Validation**:
  - New test: `tests/test_chronicle_time_normalization.py`

## Sprint 4: OCR + Layout + Temporal Linking (Generic IR Path)
**Goal**: Produce high-quality frame IR and persistent cross-frame tracks.  
**Demo/Validation**:
- UI IR and links generated from fixture session.
- Small-text regions improved with ROI policy.

### Task 4.1: OcrEngine Interface + Paddle Primary Backend
- **Location**: `autocapture_nx/processing/ocr/engine.py`, `autocapture_nx/processing/ocr/paddle_engine.py`
- **Description**: Add two-pass OCR with cache key `(frame_hash, roi, config_hash)` and ROI strategies from config.
- **Complexity**: 8
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Deterministic OCR outputs for fixture.
- **Validation**:
  - New test: `tests/test_ocr_roi_cache_determinism.py`

### Task 4.2: LayoutEngine Adapter Layer (UIED first, OmniParser gated)
- **Location**: `autocapture_nx/processing/layout/*`, plugin wrappers under `plugins/builtin/*`
- **Description**: Implement `LayoutEngine` abstraction and AGPL gate for OmniParser; default to non-AGPL backend.
- **Complexity**: 8
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - No AGPL code path unless explicit opt-in.
  - Layout output normalized to IR schema.
- **Validation**:
  - New test: `tests/test_layout_license_gate.py`

### Task 4.3: Temporal Linking Across Frames
- **Location**: `autocapture_nx/processing/link/temporal_linker.py`
- **Description**: IOU + type + text similarity + click-anchor boost for stable `track_id`.
- **Complexity**: 7
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Linker emits stable IDs with measurable switch metric.
- **Validation**:
  - New test: `tests/test_temporal_linker_id_switches.py`

## Sprint 5: Storage + Indexing + Retrieval Surface
**Goal**: Persist normalized facts and support retrieval for NL answering.  
**Demo/Validation**:
- Parquet datasets produced and queryable.
- Optional FAISS path is switchable and safe by default.

### Task 5.1: Parquet Writers + DuckDB Attach Flow
- **Location**: `autocapture_nx/storage/chronicle_store.py`, CLI helpers in `autocapture_nx/cli.py`
- **Description**: Write spec datasets (`frames`, `events_input`, `ocr_spans`, `elements`, `tracks`) with zstd.
- **Complexity**: 6
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - Partitioned output by session.
- **Validation**:
  - New test: `tests/test_chronicle_parquet_layout.py`

### Task 5.2: Vector Index Abstraction + Optional FAISS Adapter
- **Location**: `autocapture_nx/indexing/retrieval_backend.py`, `autocapture_nx/indexing/faiss_backend.py`
- **Description**: Add `add/search` abstraction, map vectors to spans, and gate multimodal embeds by privacy flag.
- **Complexity**: 7
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Dense retrieval works without FAISS.
  - FAISS path optional and deterministic on fixture corpus.
- **Validation**:
  - New test: `tests/test_retrieval_backend_switch.py`

## Sprint 6: Chronicle API (Talk Layer) + CLI Integration
**Goal**: Expose retrieval-augmented answering over localhost API and repo CLI.  
**Demo/Validation**:
- `/health`, `/sessions`, `/ingest/scan`, `/v1/chat/completions` operational on localhost.

### Task 6.1: Add Chronicle API Service
- **Location**: `services/chronicle_api/app.py`, `services/chronicle_api/routes/*.py`
- **Description**: Implement endpoints, retrieval pipeline, vLLM forwarding, extension metadata.
- **Complexity**: 8
- **Dependencies**: Sprint 5
- **Acceptance Criteria**:
  - OpenAI-compatible request/response shape accepted.
  - Loopback-only bind default.
- **Validation**:
  - New integration test: `tests/test_chronicle_api_chat_completions.py`

### Task 6.2: Add CLI Entrypoints
- **Location**: `autocapture_nx/cli.py`
- **Description**: Add `ingest`, `build-index`, `serve` commands mapped to new modules.
- **Complexity**: 4
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Single-command ingest and serve path documented.
- **Validation**:
  - New test: `tests/test_cli_chronicle_commands.py`

## Sprint 7: Evaluation + Release Gates (4 Pillars)
**Goal**: Hard gate quality, security, and citeability before shipping.  
**Demo/Validation**:
- Golden fixture pass with stable metrics.
- Regression gates fail on quality drop.

### Task 7.1: Add End-to-End Fixture Suite
- **Location**: `tests/integration/test_chronicle_fixture_pipeline.py`, fixture under `tools/fixtures/chronicle_v0/`
- **Description**: Validate ingest completion marker semantics, table creation, and grounded QA.
- **Complexity**: 7
- **Dependencies**: Sprint 6
- **Acceptance Criteria**:
  - Fixture run produces deterministic artifacts and expected answer tokens.
- **Validation**:
  - CI integration gate.

### Task 7.2: Metrics and SLO Tracking
- **Location**: `tools/query_effectiveness_report.py`, `tools/gate_advanced_eval.py`, new chronicle eval gate script
- **Description**: Track OCR proxy accuracy, linker switch rate, QA p50/p95, retrieval correctness.
- **Complexity**: 5
- **Dependencies**: Task 7.1
- **Acceptance Criteria**:
  - `ANY_REGRESS => DO_NOT_SHIP` enforced in CI.
- **Validation**:
  - Gate outputs explicit failing metric classes.

## Testing Strategy
- Unit: proto decode, zstd handling, config/schema, OCR/layout/linker primitives.
- Integration: complete spool session ingest and chronicle API QA.
- Determinism: repeated fixture runs compare stable hashes/metrics.
- Security: localhost-only checks, AGPL gate checks, privacy flag checks.

## Potential Risks & Gotchas
- **Spec conflict risk**: new spool ingest may be misread as capture reintroduction.  
  Mitigation: explicit docs + policy tests ensuring capture plugins remain deprecated.
- **Model drift risk**: configured VLM model IDs can drift from served models.  
  Mitigation: runtime model auto-resolution and startup health gate.
- **License risk (OmniParser path)**: accidental AGPL execution.  
  Mitigation: hard config gate + import/runtime tests.
- **Data integrity risk**: partial sidecar writes in shared mode.  
  Mitigation: `COMPLETE.json` gating + append-only ledger/journal checks.
- **Performance risk on 7680x2160**: full-frame OCR/VLM may exceed budgets.  
  Mitigation: ROI policy, cache, bounded batch parameters, GPU preflight.

## Rollback Plan
- Keep all new features behind config flags defaulting to safe/off where needed.
- Revert contract additions and disable chronicle ingest commands if integration destabilizes.
- Restore previous plugin lock set and profile lock hashes.
- Keep golden eval artifacts for before/after comparison.
