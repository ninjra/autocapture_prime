# Plan: Four Pillars Optimization (Spec + Plan Implementation)

**Generated**: 2026-01-31
**Estimated Complexity**: High

## Overview
Implement all requirements in `docs/four-pillars-optimization-spec.txt` and replace the previous plan with a complete, testable, four-pillars implementation roadmap. Work is additive, config-gated, deterministic, and produces durable artifacts. Non-negotiables (localhost-only, no deletion/retention pruning, raw-first local store, foreground gating, idle budgets, citations required) are enforced alongside the spec.

## Prerequisites
- Python >= 3.10; `cryptography` already present for AES-GCM/KDF use.
- Target runtime: Windows 11, 64GB RAM, RTX 4090; CUDA available and should be used aggressively.
- WSL2 + CUDA optional for GPU-heavy routing validation and cross-OS integration test.
- ffmpeg available on PATH (or configured path) for NVENC path; MSS/PIL for fallback.
- SQLCipher dependency available when running SQLCipher tests (skip with explicit rationale otherwise).
- Disk space under `artifacts/` for new reports, archives, and benchmarks; ample storage for 60+ days of data/media (no retention pruning).

## Sprint 1: Pillar Gates & Reporting Baseline (MOD-001..MOD-004)
**Goal**: Deterministic pillar gate reporting, CLI integration, and test-plan wiring.
**Demo/Validation**:
- `python3 -m autocapture_nx codex pillar-gates --deterministic-fixtures`
- `python3 tools/gate_pillars.py`
- `python3 tools/run_all_tests.py` (smoke)

### Task 1.1: Pillar report writer contract (MOD-004)
- **Location**: `autocapture/pillars/reporting.py`, `tests/test_pillar_reporting.py`
- **Description**: Implement `CheckResult`/`PillarResult` dataclasses and deterministic JSON writer (sorted keys, ordered pillars/checks, lexicographic artifacts). Ensure combined + per-pillar files.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Combined report and per-pillar files written deterministically under `artifacts/pillar_reports/`.
  - Files include `pillar_gates.json`, `p1_performant.json`, `p2_accurate.json`, `p3_secure.json`, `p4_citable.json`.
  - Existing reports are not deleted; files are overwritten deterministically by name.
  - Output ordering stable across repeated runs with identical inputs.
- **Validation**:
  - `python3 -m unittest tests/test_pillar_reporting.py -q`

### Task 1.2: Pillar gates runner (MOD-002 + MOD-004)
- **Location**: `autocapture/tools/pillar_gate.py`, `autocapture/pillars/reporting.py`, `tests/test_pillar_gates_report.py`
- **Description**: Replace existing gate list with P1–P4 checks per spec; create artifacts directories; emit combined + per-pillar reports; implement run_id format `YYYYMMDD-HHMMSSZ-<8hex>` where the 8 hex is sha256(timestamp+pid).
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - P1 runs `tools/gate_perf.py`; P2 runs retrieval golden + sanitizer NER cases; P3 runs `tools/gate_security.py` + keyring/sandbox checks; P4 runs provenance chain + doctor check + verify CLI tests.
  - Overall status fails on any failing check; error status on unexpected exception.
  - Artifacts created under `artifacts/perf`, `artifacts/retrieval`, `artifacts/security`, `artifacts/provenance`.
- **Validation**:
  - `python3 -m autocapture_nx codex pillar-gates --deterministic-fixtures`

### Task 1.3: codex pillar-gates CLI integration (MOD-002)
- **Location**: `autocapture/codex/cli.py`
- **Description**: Add argparse flags `--artifacts-dir`, `--config`, `--deterministic-fixtures` and wire to new gate runner.
- **Complexity**: 3
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - `python3 -m autocapture_nx codex pillar-gates` exits 0/1/2 per spec.
- **Validation**:
  - `python3 -m autocapture_nx codex pillar-gates --deterministic-fixtures`

### Task 1.4: Gate wrapper script (MOD-001)
- **Location**: `tools/gate_pillars.py`
- **Description**: Create wrapper that runs the CLI command, sets cwd to repo root, sets env allowlist (`PATH`, `PYTHONPATH`, `PYTHONUTF8`, plus harness vars discovered in `dev.sh`/`dev.ps1`), writes `artifacts/pillar_reports/gate_pillars.log`, returns subprocess exit code.
- **Complexity**: 3
- **Dependencies**: Task 1.3
- **Acceptance Criteria**:
  - `artifacts/pillar_reports/` exists and log is written.
  - Exit code mirrors underlying CLI command.
- **Validation**:
  - `python3 tools/gate_pillars.py`

### Task 1.5: Test plan integration (MOD-003)
- **Location**: `tools/run_all_tests.py`
- **Description**: Insert `python3 tools/gate_pillars.py` into `_commands` after `gate_perf` and before `gate_static`; ensure report includes the step.
- **Complexity**: 2
- **Dependencies**: Task 1.4
- **Acceptance Criteria**:
  - `tools/run_all_tests_report.json` includes a pillar gate step with exit code.
- **Validation**:
  - `python3 tools/run_all_tests.py`

## Sprint 2: P1 Performant — Capture Backend + Throughput Gate (MOD-005, MOD-006)
**Goal**: Desktop Duplication + NVENC backend with robust fallback and a stable throughput benchmark.
**Demo/Validation**:
- `python3 tools/gate_perf.py --backend auto` (Windows)
- `python3 -m unittest tests/test_capture_backend_fallback.py -q` (new)

### Task 2.1: Implement NVENC + MSS/JPEG backend selection (MOD-005)
- **Location**: `autocapture_nx/windows/win_capture.py`, `plugins/builtin/capture_windows/plugin.py`, `autocapture_nx/capture/pipeline.py` (as needed)
- **Description**: Add `CaptureBackend` interface, implement `dd_nvenc` and `mss_jpeg` backends, `create_capture_backend()` and `capture_once()` API, deterministic artifact naming and base dir handling, config-driven fallback logic.
- **Complexity**: 7
- **Dependencies**: None
- **Acceptance Criteria**:
  - `capture.video.backend` selects NVENC or MSS/JPEG correctly.
  - NVENC unavailable -> auto fallback to MSS/JPEG.
  - Explicit `dd_nvenc` respects `allow_fallback` config: either fails with explicit error and then falls back if allowed, or degrades to MSS/JPEG with warning recorded in perf artifacts.
  - Artifact paths are under configurable base dir; filenames deterministic via timestamp + monotonic counter persisted locally.
- **Validation**:
  - Windows integration test in Task 2.4

### Task 2.2: Config defaults + schema for capture backend (MOD-005)
- **Location**: `config/default.json`, `contracts/config_schema.json`, `tests/test_config_defaults.py` (or new)
- **Description**: Add `capture.video.backend`, `capture.video.dd_nvenc.*`, and `capture.image.mss_jpeg.quality` with enums/ranges; preserve legacy defaults and fallback flags.
- **Complexity**: 5
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Default config validates against schema.
  - Legacy path still works when backend set to MSS/JPEG explicitly.
- **Validation**:
  - `python3 -m unittest tests/test_config_defaults.py -q`

### Task 2.3: Throughput benchmark in `gate_perf` (MOD-006)
- **Location**: `tools/gate_perf.py`, `tests/test_perf_regression.py` (new)
- **Description**: Add capture throughput benchmark with median latency, artifacts/sec, baseline tracking, `--update-baseline`, `--backend` override; emit artifacts under `artifacts/perf/`. Use default `max_regression_pct=0.25` and `sample_count=50` when config missing.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Baseline created on first run; regression > 25% fails gate.
  - JSON artifacts include machine fingerprint (non-secret) and metrics.
- **Validation**:
  - `python3 -m unittest tests/test_perf_regression.py -q`
  - `python3 tools/gate_perf.py --backend auto`

### Task 2.4: Windows capture fallback integration test (MOD-005)
- **Location**: `tests/test_capture_backend_fallback.py`
- **Description**: Windows-only test that forces auto backend, simulates NVENC unavailable, asserts fallback to MSS/JPEG, and verifies explicit skip rationale on non-Windows.
- **Complexity**: 4
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Test passes on Windows; skips with explicit rationale elsewhere.
- **Validation**:
  - `python3 -m unittest tests/test_capture_backend_fallback.py -q`

## Sprint 3: P1 Performant — Runtime Enforcement + WSL2 Routing (MOD-007..MOD-009)
**Goal**: Enforce active/idle budgets with deadlines and VRAM release; route GPU-heavy work to WSL2 via file-queue IPC.
**Demo/Validation**:
- `python3 -m unittest tests/test_governor_gating.py -q`
- `python3 -m unittest tests/test_runtime_conductor.py -q`
- `python3 -m unittest tests/test_wsl2_routing_integration.py -q`

### Task 3.1: Governor enforcement + worker control protocol (MOD-007)
- **Location**: `autocapture/runtime/governor.py`, `autocapture/runtime/conductor.py`, `autocapture/runtime/scheduler.py`, `autocapture/runtime/gpu.py` (or new `gpu_resources.py`), `tests/test_governor_gating.py`, `tests/test_runtime_conductor.py`
- **Description**: Implement suspend/resume deadlines, worker ACK handling, force-stop on missed deadlines, and explicit VRAM release hook. Ensure ACTIVE suspends heavy work within deadline and IDLE resumes within budget.
- **Complexity**: 7
- **Dependencies**: None
- **Acceptance Criteria**:
  - ACTIVE triggers suspend with deadline enforcement; IDLE resumes within budget.
  - VRAM release called and failures recorded in artifacts/runtime or perf.
  - Default deadlines: `active_suspend_deadline_ms=500`, `idle_resume_budget_ms=3000` when config missing.
- **Validation**:
  - `python3 -m unittest tests/test_governor_gating.py -q`
  - `python3 -m unittest tests/test_runtime_conductor.py -q`

### Task 3.2: Foreground gating + idle CPU/RAM budgets (Non-negotiable)
- **Location**: `autocapture/runtime/conductor.py`, `autocapture/runtime/budgets.py`, `config/default.json`, `contracts/config_schema.json`, `tests/test_runtime_budgets.py` (new)
- **Description**: Enforce CPU <= 50% and RAM <= 50% during idle processing (GPU unconstrained). When user ACTIVE, allow GPU‑only tasks to run if they do not introduce user lag (measured via capture latency and system responsiveness); otherwise pause all non-capture processing. Add config keys for thresholds and deterministic defaults (50% CPU/RAM), plus GPU lag guard thresholds.
- **Complexity**: 6
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Background processing halts when user active or budgets exceeded, except GPU‑only tasks that pass lag guard.
  - GPU lag guard uses deterministic thresholds (e.g., capture latency p95 and UI heartbeat timeout) and logs decisions to audit.
  - Budget checks are deterministic and logged for audit.
- **Validation**:
  - `python3 -m unittest tests/test_runtime_budgets.py -q`

### Task 3.5: Fullscreen detection halt (User requirement)
- **Location**: `autocapture/runtime/conductor.py`, `autocapture_nx/windows/win_capture.py`, `autocapture_nx/windows/win_cursor.py` (if needed), `config/default.json`, `contracts/config_schema.json`, `tests/test_fullscreen_halt.py` (new)
- **Description**: When any fullscreen app is detected, stop all processing and capture (fail closed). Detection should be Windows-native, deterministic, and not rely on game-specific heuristics. Add config keys to enable/disable (default enabled) and logging/audit of halt events.
- **Complexity**: 6
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Fullscreen detected -> capture and all processing stop immediately; resume when fullscreen exits.
  - Behavior is deterministic and logged to audit with window/process metadata (no sensitive payloads).
- **Validation**:
  - `python3 -m unittest tests/test_fullscreen_halt.py -q`

### Task 3.6: CUDA utilization optimization (User requirement)
- **Location**: `autocapture/runtime/conductor.py`, `autocapture/runtime/gpu.py`, `autocapture/runtime/gpu_monitor.py` (new), `config/default.json`, `contracts/config_schema.json`, `tests/test_gpu_lag_guard.py` (new)
- **Description**: Add GPU utilization/latency monitor (prefer NVML via `pynvml` or `nvidia-ml-py`; fallback to conservative behavior if unavailable). Use monitor to maximize CUDA usage while respecting lag guard thresholds when user active. GPU-only tasks are permitted during active sessions if monitor indicates no lag risk.
- **Complexity**: 6
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - GPU-only tasks can run during active sessions when lag guard passes; otherwise they pause.
  - If GPU monitor unavailable, system defaults to safe mode (pause GPU-only tasks on active).
  - Decisions are logged to audit with utilization/latency snapshots (no sensitive payloads).
  - Defaults tuned for RTX 4090: prefer native CUDA, allow GPU saturation while idle, and use conservative lag guard thresholds when active.
- **Validation**:
  - `python3 -m unittest tests/test_gpu_lag_guard.py -q`

### Task 3.3: WSL2 routing via file-queue IPC (MOD-008)
- **Location**: `autocapture/runtime/scheduler.py`, `autocapture/runtime/wsl2_queue.py` (new), `config/default.json`, `contracts/config_schema.json`
- **Description**: Implement WSL2 routing with file queue protocol, protocol version gate, atomic file writes, and fallback to native when configured. Defaults: protocol_version=1, shared_queue_dir=`artifacts/wsl2_queue`, distro empty string (default distro). Default target remains `native` on Windows to fully utilize local CUDA; WSL2 is opt-in. Ensure routing does not block capture/tray on Windows.
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Protocol version mismatch refuses dispatch with explicit error and optional fallback.
  - When WSL2 unavailable and target is native, processing continues locally.
  - When target is explicitly `wsl2` and WSL2 is unavailable, error is explicit and P1 gate records failure (no silent fallback unless config allows).
- **Validation**:
  - `python3 -m unittest tests/test_wsl2_routing_integration.py -q`

### Task 3.4: Cross-OS routing integration test (MOD-009)
- **Location**: `tests/test_wsl2_routing_integration.py`
- **Description**: Windows-only integration test for WSL2 routing and protocol gates; explicit skip messaging when WSL2 unavailable. Include a minimal WSL2-side responder (test helper) to complete a file-queue roundtrip without network services.
- **Complexity**: 4
- **Dependencies**: Task 3.3
- **Acceptance Criteria**:
  - WSL2 available -> roundtrip OK and protocol version enforced.
  - Mismatch -> explicit error and refusal.
- **Validation**:
  - `python3 -m unittest tests/test_wsl2_routing_integration.py -q`

## Sprint 4: P2 Accurate — Retrieval + Sanitizer Hybrid (MOD-010..MOD-015 + ADR-008)
**Goal**: Deterministic embedding, reranking, vector index persistence, retrieval fusion, golden tests, and hybrid NER sanitizer.
**Demo/Validation**:
- `python3 -m unittest tests/test_vector_index_roundtrip.py -q`
- `python3 -m unittest tests/test_rrf_fusion_determinism.py -q`
- `python3 -m unittest tests/test_retrieval_golden.py -q`
- `python3 -m unittest tests/test_sanitizer_ner_cases.py -q`

### Task 4.1: Bundle manager for local models (MOD-015)
- **Location**: `autocapture/models/bundles.py`, `tests/fixtures/bundles/`, `tests/test_bundle_manager.py` (new)
- **Description**: Implement deterministic bundle discovery and selection; default paths (Windows `D:\autocapture\bundles\`), fixture-only selection in tests; clean fallback on load failure.
- **Complexity**: 6
- **Dependencies**: None
- **Acceptance Criteria**:
  - Only deterministic bundles selected by default.
  - Bundle selection stable: bundle_id asc, version desc.
- **Validation**:
  - `python3 -m unittest tests/test_bundle_manager.py -q`

### Task 4.2: Deterministic embedder implementation (MOD-012)
- **Location**: `autocapture/indexing/vector.py`, `plugins/builtin/embedder_stub/plugin.py`, `tests/test_embedder_determinism.py` (new)
- **Description**: Replace external-download behavior with deterministic hash-based embedding (dim 384 default) and optional bundle override.
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Embedding algorithm matches spec tokenization and hashing rules.
  - Bundle override used when available; fallback otherwise.
- **Validation**:
  - `python3 -m unittest tests/test_embedder_determinism.py -q`

### Task 4.3: Deterministic reranker implementation (MOD-013)
- **Location**: `plugins/builtin/reranker_stub/plugin.py`, `autocapture/retrieval/rerank.py`, `tests/test_reranker_determinism.py` (new)
- **Description**: Implement deterministic reranker scoring (base_score + overlap + phrase bonus), stable tie-break by doc_id, bundle override support.
- **Complexity**: 5
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Deterministic ordering with tie-break rules.
- **Validation**:
  - `python3 -m unittest tests/test_reranker_determinism.py -q`

### Task 4.4: Vector index persistence (MOD-010)
- **Location**: `autocapture/indexing/vector.py`, `tests/test_vector_index_roundtrip.py`
- **Description**: Implement build/save/load for deterministic JSON with int16 quantization; remove machine-dependent serialization.
- **Complexity**: 6
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Roundtrip preserves doc_ids and quantized vectors exactly.
- **Validation**:
  - `python3 -m unittest tests/test_vector_index_roundtrip.py -q`

### Task 4.5: Retrieval tiers + deterministic fusion (MOD-011)
- **Location**: `autocapture/retrieval/tiers.py`, `autocapture/retrieval/fusion.py`, `tests/test_rrf_fusion_determinism.py`
- **Description**: Implement Candidate model, lexical/vector/rerank tiers, RRF fusion with tie-break by doc_id; use default `rrf_k=60` unless config specifies.
- **Complexity**: 5
- **Dependencies**: Task 4.4, Task 4.3
- **Acceptance Criteria**:
  - RRF fusion deterministic with ties resolved by doc_id.
- **Validation**:
  - `python3 -m unittest tests/test_rrf_fusion_determinism.py -q`

### Task 4.6: Golden retrieval suite (MOD-014)
- **Location**: `tests/test_retrieval_golden.py`
- **Description**: Add deterministic corpus, recall/precision thresholds, and explicit threshold rationale in test file.
- **Complexity**: 4
- **Dependencies**: Task 4.5
- **Acceptance Criteria**:
  - Test passes consistently and fails on ranking regressions.
- **Validation**:
  - `python3 -m unittest tests/test_retrieval_golden.py -q`

### Task 4.7: Hybrid sanitizer name detection (ADR-008)
- **Location**: `plugins/builtin/egress_sanitizer/plugin.py`, `autocapture/memory/entities.py`, `tests/test_sanitizer_ner_cases.py`
- **Description**: Implement deterministic rule-based name detection + optional NER bundle union with stable span ordering; ensure sanitization occurs only on explicit export/egress (raw-first local store).
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Hybrid detection passes name cases and is deterministic.
  - Local storage remains unredacted; sanitizer applies only on explicit export/egress.
- **Validation**:
  - `python3 -m unittest tests/test_sanitizer_ner_cases.py -q`

## Sprint 5: P3 Secure — Keyring, Sandbox, SQLCipher, Gate Security (MOD-016..MOD-018, MOD-017, MOD-023)
**Goal**: Secure key storage with portability, OS sandboxing for plugins, SQLCipher validation, and security gate reporting.
**Demo/Validation**:
- `python3 tools/gate_security.py`
- `python3 -m unittest tests/test_sqlcipher_roundtrip.py -q`

### Task 5.1: Root key storage + migration (MOD-016)
- **Location**: `autocapture_nx/kernel/keyring.py`, `autocapture_nx/kernel/key_rotation.py`, `plugins/builtin/storage_encrypted/plugin.py`, `tests/test_keyring_migration_windows.py` (new)
- **Description**: Add `windows_credential_manager` and `portable_file` backends; implement export/import bundle with AES-GCM + KDF; enforce default Windows key storage; add migration test and audit log entries for key export/import.
- **Complexity**: 8
- **Dependencies**: None
- **Acceptance Criteria**:
  - Root keys not stored plaintext on Windows defaults.
  - Export/import bundle transfers key to another machine backend.
  - Tamper detection enforced in bundle decryption.
- **Validation**:
  - `python3 -m unittest tests/test_keyring_migration_windows.py -q` (Windows only, skip elsewhere)

### Task 5.2: Key rotation rewrap + rollback safety (MOD-016)
- **Location**: `autocapture_nx/kernel/key_rotation.py`
- **Description**: Implement `rotate_root_key()` that rewraps storage keys, keeps previous key until rewrap complete, and logs audit event.
- **Complexity**: 5
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Rotation does not leave system in unusable state when interrupted.
- **Validation**:
  - Extend existing key rotation tests or add `tests/test_key_rotation.py`.

### Task 5.3: Plugin sandbox + IPC hardening (MOD-017)
- **Location**: `autocapture_nx/plugin_system/sandbox.py` (new), `autocapture_nx/plugin_system/host.py`, `autocapture/plugins/manager.py`, `tests/test_plugin_sandbox.py` (new)
- **Description**: Implement sandbox policy facade with restricted token + JobObject limits on Windows; enforce IPC allowlist/schema/size limits; ensure PolicyGate remains enforced for external inputs; record audit artifact `artifacts/security/plugin_sandbox_report.json` and append to audit log.
- **Complexity**: 8
- **Dependencies**: None
- **Acceptance Criteria**:
  - Plugin hosts run with reduced privileges on Windows.
  - IPC rejects unknown/oversized messages and logs audit record.
- **Validation**:
  - `python3 -m unittest tests/test_plugin_sandbox.py -q`

### Task 5.4: SQLCipher roundtrip test with explicit skip rationale (MOD-018)
- **Location**: `plugins/builtin/storage_sqlcipher/plugin.py`, `tests/test_sqlcipher_roundtrip.py`
- **Description**: Add SQLCipher roundtrip test with OS/dependency skip messaging; ensure deterministic temp paths and fixtures.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Skip message includes OS name, missing dependency, and remediation hint.
- **Validation**:
  - `python3 -m unittest tests/test_sqlcipher_roundtrip.py -q`

### Task 5.5: Security gate artifact summary (MOD-023)
- **Location**: `tools/gate_security.py`
- **Description**: Run keyring/sandbox/SQLCipher tests where applicable, emit `artifacts/security/gate_security.json` summary, exit non-zero on failures.
- **Complexity**: 4
- **Dependencies**: Task 5.1, Task 5.3, Task 5.4
- **Acceptance Criteria**:
  - Gate emits summary with per-check status and skip rationale.
- **Validation**:
  - `python3 tools/gate_security.py`

### Task 5.6: Append-only audit log for privileged actions (Non-negotiable)
- **Location**: `autocapture_nx/kernel/audit.py` (new), call sites in keyring export/import, sandbox spawn, WSL2 routing, deletion-blocks
- **Description**: Create append-only JSONL audit log writer under `artifacts/audit/` with deterministic schema (schema_version, ts_utc, action, actor, outcome, details); wire into privileged actions (key export/import, sandbox spawn, WSL2 dispatch, denied delete attempts).
- **Complexity**: 5
- **Dependencies**: Task 5.1, Task 5.3, Task 3.3, Task 6.5
- **Acceptance Criteria**:
  - Audit log appends without truncation or mutation.
  - Privileged actions emit audit events with action, actor, timestamp, and outcome.
- **Validation**:
  - Add unit test `tests/test_audit_log.py` for append-only behavior.

## Sprint 6: P4 Citable — Provenance, Verify CLI, Citations + Compliance (MOD-019..MOD-022, MOD-020..MOD-021)
**Goal**: Enforce anchor trust boundary, implement portable archive verification, and surface citations end-to-end with compliance checks.
**Demo/Validation**:
- `python3 -m unittest tests/test_provenance_chain.py -q`
- `python3 -m autocapture_nx verify-archive --archive <path> --json`

### Task 6.1: Anchor trust boundary doctor validation (MOD-019)
- **Location**: `autocapture_nx/kernel/loader.py`, `config/default.json`, `contracts/config_schema.json`, `tests/test_doctor_anchor_boundary.py` (new)
- **Description**: Add doctor check for anchors vs data_dir separation; update defaults (`artifacts/datastore`, `artifacts/anchors`); test failure/success cases.
- **Complexity**: 5
- **Dependencies**: None
- **Acceptance Criteria**:
  - Doctor fails when anchors and data store co-located or nested.
- **Validation**:
  - `python3 -m unittest tests/test_doctor_anchor_boundary.py -q`

### Task 6.2: Provenance archive export/import (MOD-020)
- **Location**: `autocapture/storage/archive.py`, `autocapture/pillars/citable.py`
- **Description**: Implement deterministic zip archive with manifest, ledger hash, evidence hashes, and anchor files; no absolute paths; lexicographic entry order and fixed timestamps (00:00:00 UTC).
- **Complexity**: 6
- **Dependencies**: None
- **Acceptance Criteria**:
  - Archive is self-contained, deterministic, and portable across machines.
- **Validation**:
  - Covered by Task 6.3 tests.

### Task 6.3: Verify-archive CLI + tests (MOD-021)
- **Location**: `autocapture_nx/cli.py`, `autocapture/pillars/citable.py`, `tests/test_provenance_chain.py`
- **Description**: Add `verify-archive` CLI command with JSON output, tamper detection, and evidence/ledger/anchors verification per spec; include evidence span identifiers and ledger refs in failure output where available.
- **Complexity**: 6
- **Dependencies**: Task 6.2
- **Acceptance Criteria**:
  - Tampering yields non-zero exit; OK yields zero.
- **Validation**:
  - `python3 -m unittest tests/test_provenance_chain.py -q`

### Task 6.4: Citations schema end-to-end (MOD-022)
- **Location**: `autocapture/memory/citations.py`, `autocapture/ux/facade.py`, `autocapture/web/routes/query.py`, `autocapture/web/ui/`
- **Description**: Extend citations to include evidence spans + ledger refs; ensure facade and API always emit citations; when uncitable, emit explicit “uncitable/indeterminate” responses instead of fabricated citations; add minimal UI rendering; add facade/API tests.
- **Complexity**: 5
- **Dependencies**: None
- **Acceptance Criteria**:
  - CLI, API, and UI show citation metadata with stable ordering.
- **Validation**:
  - `python3 -m unittest tests/test_citations_schema.py -q` (new)

### Task 6.5: Localhost-only binding + no-deletion enforcement (Non-negotiable)
- **Location**: `autocapture_nx/tray.py`, `autocapture/web/api.py`, `autocapture_nx/cli.py`, `tests/test_localhost_only.py` (new)
- **Description**: Enforce bind host == `127.0.0.1` regardless of env/config; hard-disable delete/cleanup actions and retention pruning; audit tray/menu to ensure no capture pause or deletion actions; add tests to ensure fail-closed behavior.
- **Complexity**: 5
- **Dependencies**: None
- **Acceptance Criteria**:
  - Any non-local bind attempt (env or config) fails closed with explicit error.
  - Deletion endpoints/commands (including `storage cleanup` and `compact-derived`) return disabled status even if config toggled.
  - Retention/pruning jobs are disabled or converted to archive/migrate-only operations.
- **Validation**:
  - `python3 -m unittest tests/test_localhost_only.py -q`

## Sprint 7: CI Workflow (ADR-012)
**Goal**: Reduce cross-platform regression risk with a minimal CI matrix.
### Task 7.1: Add CI workflow
- **Location**: `.github/workflows/ci.yml` (new)
- **Description**: Add Linux job running `python3 tools/run_all_tests.py`; add Windows job running Windows-only gates where feasible; mark external checks out of scope.
- **Complexity**: 3
- **Dependencies**: None
- **Acceptance Criteria**:
  - CI runs on pull requests and reports failures clearly.
- **Validation**:
  - Manual PR run in GitHub Actions.

## Testing Strategy
- Primary: `./dev.sh test` or `dev.ps1 test` (full harness)
- Pillar gates: `python3 -m autocapture_nx codex pillar-gates` and `python3 tools/gate_pillars.py`
- Targeted gates: `python3 tools/gate_perf.py`, `python3 tools/gate_security.py`, `python3 tools/gate_static.py`
- Unit tests: `python3 -m unittest discover -s tests -q`
- Windows-only tests: capture backend, keyring migration, SQLCipher, WSL2 routing (skip with explicit rationale when unavailable)

## Potential Risks & Gotchas
- NVENC/ffmpeg availability varies by host; ensure fallback paths and explicit skip messaging.
- WSL2 availability or protocol mismatch may cause routing failures; must fall back to native where configured.
- SQLCipher dependency and Windows Credential Manager integration may require platform-specific APIs; ensure clear skips on unsupported hosts.
- Deterministic bundle selection must avoid accidental local model downloads; tests must pin fixture paths.
- UI citation surfacing must remain minimal to avoid UI regressions in the existing web console.

## Rollback Plan
- Keep new features behind config flags and preserve legacy fallbacks.
- Remove `tools/gate_pillars.py` from `tools/run_all_tests.py` if gates block unrelated work.
- Disable WSL2 routing by default (`runtime.routing.gpu_heavy.target = native`).
- Revert archive/verify CLI changes independently from UI citation changes if needed.

## SRC Implementation Map
- SRC-001: Section 1.Architectural_Hard_Rules; Section 2 (all MOD-### implementation detail level)
- SRC-002: Section 1.Architectural_Hard_Rules; ADR-002/ADR-005/ADR-006 ensure non-stub fallbacks
- SRC-003: Section 1.Architectural_Hard_Rules; Section 3 (all ADRs rationale)
- SRC-004: Section 1.Constraints_And_Resolved_Ambiguities; ADR-001
- SRC-005: Section 1.Options_Selection_Policy; ADR-002..ADR-011
- SRC-006: Section 1.Architectural_Hard_Rules; ADR-002; MOD-016/MOD-020/MOD-021
- SRC-007: ADR-003
- SRC-008: ADR-004
- SRC-009: ADR-004/ADR-005/ADR-006
- SRC-010: ADR-007; MOD-015
- SRC-011: ADR-008; MOD-014
- SRC-012: Section 1.Repo_Inspection_Protocol; MOD-002/MOD-021
- SRC-013: ADR-010; MOD-022
- SRC-014: Section 1.Architectural_Hard_Rules; ADR-001
- SRC-015: Section 1.Architectural_Hard_Rules; MOD-003
- SRC-016: Section 1.Environment_Standards.Language_Runtime
- SRC-017: Section 1.Environment_Standards.Test_Entry_Points
- SRC-018: MOD-003
- SRC-019: Section 1.Environment_Standards.Platforms; MOD-005/MOD-016/MOD-017
- SRC-020: MOD-008; MOD-009; ADR-011
- SRC-021: MOD-005; MOD-018
- SRC-022: ADR-007; MOD-015
- SRC-023: MOD-001/MOD-002/MOD-003
- SRC-024: MOD-002
- SRC-025: MOD-001
- SRC-026: MOD-001
- SRC-027: MOD-001/MOD-002
- SRC-028: MOD-002
- SRC-029: MOD-003
- SRC-030: MOD-003
- SRC-031: MOD-005/MOD-006/MOD-007/MOD-008
- SRC-032: MOD-006
- SRC-033: MOD-005; ADR-003
- SRC-034: MOD-005; ADR-004
- SRC-035: MOD-005; ADR-004
- SRC-036: MOD-005
- SRC-037: MOD-008; ADR-011
- SRC-038: MOD-007
- SRC-039: MOD-007; ADR-005
- SRC-040: MOD-007; ADR-005
- SRC-041: MOD-007
- SRC-042: MOD-006
- SRC-043: MOD-006; ADR-005
- SRC-044: MOD-008; ADR-011
- SRC-045: MOD-008; ADR-004
- SRC-046: MOD-008
- SRC-047: MOD-009
- SRC-048: MOD-009..MOD-014
- SRC-049: MOD-009..MOD-013; ADR-006; ADR-007
- SRC-050: MOD-010; ADR-006
- SRC-051: MOD-015; ADR-007
- SRC-052: MOD-009
- SRC-053: MOD-010
- SRC-054: MOD-013
- SRC-055: MOD-013; ADR-006
- SRC-056: MOD-013
- SRC-057: MOD-014; ADR-008
- SRC-058: MOD-015; ADR-008
- SRC-059: MOD-014
- SRC-060: MOD-014; ADR-008
- SRC-061: MOD-014
- SRC-062: MOD-014
- SRC-063: MOD-016..MOD-019
- SRC-064: MOD-023
- SRC-065: ADR-002; MOD-016
- SRC-066: ADR-002; MOD-016
- SRC-067: ADR-002; MOD-016
- SRC-068: MOD-016
- SRC-069: ADR-009; MOD-017
- SRC-070: MOD-017
- SRC-071: MOD-017; ADR-009
- SRC-072: MOD-017
- SRC-073: MOD-018
- SRC-074: MOD-018; (COULD) ADR-012
- SRC-075: MOD-018
- SRC-076: MOD-019..MOD-022
- SRC-077: MOD-019
- SRC-078: MOD-019
- SRC-079: MOD-020/MOD-021
- SRC-080: MOD-020
- SRC-081: MOD-021
- SRC-082: MOD-022
- SRC-083: MOD-021/MOD-022
- SRC-084: MOD-020/MOD-021/MOD-022
- SRC-085: Section 1.Environment_Standards.Test_Entry_Points; MOD-003
- SRC-086: Section 1.Environment_Standards.Test_Entry_Points; MOD-006/MOD-023
- SRC-087: MOD-001/MOD-002/MOD-003
- SRC-088: ADR-001; MOD-016/MOD-018/MOD-017 (skip design)
- SRC-089: ADR-012
- SRC-090: ADR-007; MOD-015; MOD-013 tests enforce deterministic fixture bundles
- SRC-091: ADR-011; MOD-008/MOD-009
- SRC-092: ADR-001; ADR-004; MOD-005/MOD-008/MOD-017 feature flags
- SRC-093: ADR-001 (Rollback_Strategy)
- SRC-094: ADR-001 (Change_Strategy)
- SRC-095: Section 1.Source_Index only
- SRC-096: Section 1.Source_Index only
