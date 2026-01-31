# Plan: Blueprint + Updates Full Implementation (Four Pillars)

**Generated**: 2026-01-30
**Estimated Complexity**: High

## Overview
Implement 100% of the requirements in `docs/1-30-26 blueprint.md` and `docs/1-30-26 updates.md` with no partials. The plan is phased to deliver demoable increments while optimizing for the four pillars: Performance, Accuracy, Security, Citeability. Each sprint includes schema/config updates, UI/UX alignment, and tests to keep behavior deterministic and auditable.

## Prerequisites
- Windows 11 x64 environment with RTX 4090 drivers and Desktop Duplication support.
- Vendor binaries available at configured paths (`vendor/qdrant.exe`, `ffmpeg`) with SHA256 manifests for verification.
- Ability to install Windows firewall rules and Windows Service via existing ops/install workflow (no sudo/admin commands in repo).
- Local LLM runtime available (default: Ollama per SRC-147) with offline operation.
- Dev harness available: `./dev.sh test` or `python3 tools/run_all_tests.py`.

## Sprint 1: Phase 0 Guardrails and Status Visibility
**Goal**: Establish non-negotiable constraints, Phase 0 requirements, and visible capture/processing state.
**Demo/Validation**:
- Capture runs; processing pauses when user active.
- No delete endpoints or retention pruning paths exist.
- UI + tray show live capture status and pause reasons.

### Task 1.1: Author required docs and coverage map
- **Location**: `AGENTS.md`, `SPEC.md`, `docs/implementation_coverage_map.md`
- **Description**: Create/replace `AGENTS.md` and `SPEC.md` per blueprint templates; add implementation coverage map that links each SRC to code/tests and update it as work lands.
- **Complexity**: 3
- **Dependencies**: None
- **Acceptance Criteria**:
  - `AGENTS.md` and `SPEC.md` match templates verbatim.
  - Coverage map lists all SRC IDs with implementation/test references.
- **Validation**:
  - Manual diff against blueprint template.

### Task 1.2: Enforce No-Deletion Mode (routes + retention + UI)
- **Location**: `autocapture/storage/retention.py`, `autocapture_nx/kernel/metadata_store.py`, `autocapture_nx/ux/facade.py`, `autocapture/web/ui/app.js`, `autocapture_nx/windows/tray.py`, `autocapture/gateway/router.py`
- **Description**: Remove/disable delete endpoints and retention pruning paths; replace with archive/migrate flows only. Remove delete actions from UI/tray.
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - `/api/delete_range` and `/api/delete_all` are absent.
  - Retention worker never unlinks files in no-deletion mode.
  - UI/tray show no delete actions.
- **Validation**:
  - Add/extend tests to assert delete routes absent and retention is inert.

### Task 1.3: Add Memory Replacement (Raw) preset
- **Location**: `config/default.json`, `contracts/config_schema.json`, `autocapture_nx/kernel/config.py`, `autocapture_nx/capture/pipeline.py`, `autocapture/web/ui/app.js`
- **Description**: Introduce preset enforcing `diff_epsilon=0`, exact-only dedupe, full-res storage, `block_fullscreen=false`, HID-triggered checks, and 0.5s active hash interval.
- **Complexity**: 5
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Selecting preset yields strict change-driven capture.
  - Config exposes preset and derived parameters in UI.
- **Validation**:
  - Unit test for preset config merge; manual capture check on minute tick.

### Task 1.4: Foreground gating for processing
- **Location**: `autocapture/runtime/governor.py`, `autocapture/runtime/conductor.py`, `autocapture_nx/processing/idle.py`, `autocapture_nx/kernel/loader.py`
- **Description**: Ensure non-capture workers scale to 0 while user active; resume when idle; surface pause reason. Use Windows display power status as a primary activity signal (display on = active) and define idle once display off for 300s.
- **Complexity**: 6
- **Dependencies**: Task 1.3
- **Acceptance Criteria**:
  - Processing stops within configured window on HID input.
  - Idle resumes processing without manual intervention.
- **Validation**:
  - New unit tests for governor mode transitions.

### Task 1.6: HID activity + display power sessioning
- **Location**: `autocapture/runtime/activity.py`, `autocapture_nx/windows/win_window.py`, `autocapture_nx/kernel/telemetry.py`
- **Description**: Integrate Windows display power status into activity tracking. Set `idle_threshold_seconds=300` and `session_gap_seconds=300` so sessions align to display on/off boundaries and the 5-minute idle window.
- **Complexity**: 5
- **Dependencies**: Task 1.4
- **Acceptance Criteria**:
  - Display on immediately marks ACTIVE; display off drives IDLE after 300s.
  - Sessions split after 300s inactivity with rollups recorded.
- **Validation**:
  - Unit test with simulated display power events.

### Task 1.5: Capture status API and tray/UI parity
- **Location**: `autocapture_nx/ux/facade.py`, `autocapture_nx/kernel/loader.py`, `autocapture/web/ui/index.html`, `autocapture/web/ui/app.js`, `autocapture_nx/windows/tray.py`
- **Description**: Expose `get_capture_status` (last capture age, disk, queue depth, drop counters, pause reason) and render in UI top bar + tray.
- **Complexity**: 6
- **Dependencies**: Task 1.4
- **Acceptance Criteria**:
  - Status panel shows capture freshness, disk state, drops, and pause reason.
  - Tray mirrors status and does not provide capture pause.
- **Validation**:
  - Manual UI inspection; add API response shape tests.

## Sprint 2: Capture Integrity, Storage, and Change-Driven Semantics
**Goal**: Crash-safe capture with strict change-driven semantics, disk safety, and verifiable hashes.
**Demo/Validation**:
- Crash during capture recovers with journal replay.
- Disk low triggers hard halt banner.
- HID-triggered capture + 0.5s active checks work; unavailable markers recorded.

### Task 2.1: Append-only Capture Journal + reconciler
- **Location**: `autocapture_nx/kernel/event_builder.py`, `autocapture_nx/kernel/loader.py`, `contracts/journal_schema.json`, `autocapture_nx/kernel/metadata_store.py`
- **Description**: Implement capture journal with staging/commit events and startup reconciliation that repairs or marks broken evidence.
- **Complexity**: 7
- **Dependencies**: Task 1.5
- **Acceptance Criteria**:
  - Journal is append-only and includes staging/commit states.
  - Startup reconcile handles orphaned staging safely.
- **Validation**:
  - Chaos test: kill during write and verify recovery.

### Task 2.2: Two-tier disk watermarks and hard halt
- **Location**: `autocapture/storage/pressure.py`, `autocapture_nx/capture/pipeline.py`, `autocapture_nx/kernel/alerts.py`, `autocapture/web/ui/app.js`, `contracts/config_schema.json`, `config/default.json`
- **Description**: Add soft backpressure and hard halt thresholds with explicit “CAPTURE HALTED: DISK LOW” alerts. Default values: `watermark_soft_mb=102400` and `watermark_hard_mb=51200` (aligned with disk_pressure soft/critical in GB).
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Soft watermark increases backpressure; hard watermark halts capture with visible banner.
- **Validation**:
  - Simulated disk low test; alert appears in UI/tray.

### Task 2.3: Startup integrity sweep + stale evidence marking
- **Location**: `autocapture_nx/kernel/loader.py`, `autocapture_nx/kernel/evidence.py`, `autocapture_nx/kernel/query.py`
- **Description**: Verify DB↔media existence and hash consistency on startup; mark stale answers when evidence missing.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Missing/mismatched media flagged; affected answers marked stale.
- **Validation**:
  - Unit test with missing media file triggers stale flag.

### Task 2.4: Change-driven capture + HID-triggered checks
- **Location**: `autocapture_nx/windows/win_capture.py`, `autocapture_nx/capture/pipeline.py`, `autocapture_nx/windows/win_window.py`
- **Description**: Use Desktop Duplication dirty-rect capture where possible; enforce HID-triggered capture and 0.5s active hash checks; record “unavailable” markers for DRM/fullscreen failures.
- **Complexity**: 8
- **Dependencies**: Task 1.3
- **Acceptance Criteria**:
  - Any visible change results in stored frame (hash differs -> saved).
  - Fullscreen/DRM failures produce explicit unavailable markers.
- **Validation**:
  - Windows integration test for dirty-rect capture + HID.

### Task 2.5: Dual-hash capture proof (raw pixels + encoded bytes)
- **Location**: `autocapture_nx/kernel/hashing.py`, `autocapture_nx/capture/pipeline.py`, `contracts/evidence.schema.json`, `autocapture/web/ui/app.js`
- **Description**: Compute BLAKE3 raw_pixels_hash pre-encode and SHA256 encoded_bytes_hash post-encode; store and surface in UI.
- **Complexity**: 6
- **Dependencies**: Task 2.4
- **Acceptance Criteria**:
  - Each frame stores both hashes and exposes them in UI detail view.
- **Validation**:
  - Unit test for hash stability and dual-hash storage.

### Task 2.6: MediaStore v2 with sharded paths + segment store option
- **Location**: `autocapture/storage/media_store.py`, `autocapture_nx/kernel/paths.py`, `autocapture/storage/blob_store.py`, `contracts/config_schema.json`, `config/default.json`
- **Description**: Default to standalone per-frame files with hash-prefix sharding; implement segment store as optional backend with identical read/verify interface.
- **Complexity**: 8
- **Dependencies**: Task 2.5
- **Acceptance Criteria**:
  - Standalone storage remains default; segment store selectable by config.
  - Verify/read works for both modes.
- **Validation**:
  - Storage integration tests for both backends.

### Task 2.7: Audio capture plugin compliance
- **Location**: `plugins/builtin/audio_windows/plugin.py`, `autocapture_nx/plugin_system/registry.py`, `autocapture_nx/kernel/loader.py`
- **Description**: Ensure audio capture runs as a separate plugin, uses audit/journal events, and remains enabled in the default capture pipeline.
- **Complexity**: 4
- **Dependencies**: Task 1.3
- **Acceptance Criteria**:
  - Audio capture plugin loads via plugin system and writes journal events.
- **Validation**:
  - Integration test that audio artifacts are recorded with timestamps.

## Sprint 3: Canonical Data Model, Lineage, and Trust Signals
**Goal**: Establish Frame v2 as single source of truth and make processing provenance auditable.
**Demo/Validation**:
- New frames stored as Frame v2; JobRun records show inputs/outputs.
- Ledger head and daily freeze visible.

### Task 3.1: Frame v2 schema + migrations + DB constraints
- **Location**: `autocapture_nx/kernel/metadata_store.py`, `autocapture_nx/kernel/evidence.py`, `contracts/evidence.schema.json`, `autocapture/storage/database.py`
- **Description**: Define canonical Frame v2 schema, migrate existing records, and enforce FK/NOT NULL constraints.
- **Complexity**: 7
- **Dependencies**: Task 2.6
- **Acceptance Criteria**:
  - All frames map to Frame v2 fields; constraints prevent invalid records.
- **Validation**:
  - Migration test verifies counts and FK integrity.

### Task 3.2: JobRun model + DAG support
- **Location**: `autocapture_nx/kernel/derived_records.py`, `autocapture_nx/processing/sst/persist.py`, `autocapture_nx/kernel/query.py`
- **Description**: Introduce JobRun model with inputs/outputs and integrate into processing pipeline; expose API for UI DAG rendering.
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Every artifact references a job_id and is linked to JobRun graph.
- **Validation**:
  - Unit tests for JobRun creation and linkage.

### Task 3.3: Standardize artifact metadata + dedupe_key uniqueness
- **Location**: `autocapture_nx/kernel/derived_records.py`, `autocapture_nx/processing/sst/persist.py`, `autocapture/storage/database.py`
- **Description**: Enforce artifact fields (engine, engine_version, attempts, last_error, timings) and unique dedupe_key.
- **Complexity**: 6
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Duplicate processing runs do not create duplicate artifacts.
- **Validation**:
  - Idempotency test on repeated OCR job.

### Task 3.4: Persist config snapshots and plugin versions per session
- **Location**: `autocapture_nx/kernel/loader.py`, `autocapture_nx/plugin_system/registry.py`, `autocapture_nx/kernel/config.py`
- **Description**: Store immutable config snapshot and plugin versions per session_id at startup.
- **Complexity**: 4
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Each session has config snapshot + plugin version records.
- **Validation**:
  - Unit test confirms snapshot persistence.

### Task 3.5: Provenance ledger head + daily freeze
- **Location**: `autocapture_nx/kernel/proof_bundle.py`, `contracts/ledger_schema.json`, `autocapture_nx/kernel/loader.py`
- **Description**: Maintain append-only ledger, store head hash in DB, and generate daily freeze checkpoints.
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Ledger chain verifies; daily freeze entry created idempotently.
  - Ledger head hash is visible in UI and included in exports.
- **Validation**:
  - Tamper-detection test fails on modified entry.

### Task 3.6: HID session rollups + trust_level computation
- **Location**: `autocapture/runtime/activity.py`, `autocapture_nx/kernel/telemetry.py`, `autocapture_nx/kernel/query.py`
- **Description**: Compute per-session rollups and trust_level (green/yellow/red) for sessions and answers based on drops/processing gaps.
- **Complexity**: 5
- **Dependencies**: Task 1.4
- **Acceptance Criteria**:
  - UI/API surfaces trust_level and reasons for downgrade.
- **Validation**:
  - Unit tests for trust level transitions.

### Task 3.7: Local-only entity hash map storage
- **Location**: `autocapture_nx/kernel/key_rotation.py`, `autocapture_nx/kernel/egress_approvals.py`, `autocapture/storage/keys.py`
- **Description**: Implement salted, rotatable entity map stored locally (encrypted) for export-only sanitization.
- **Complexity**: 6
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Entity map is stored locally and never exported.
- **Validation**:
  - Unit test for hash rotation and lookup.

## Sprint 4: Processing Correctness, Replay, and Retrieval Trace
**Goal**: Make processing idempotent, debuggable, and citation-first.
**Demo/Validation**:
- Replays produce diff reports.
- Citations required by default; missing evidence surfaced.

### Task 4.1: Idempotent workers with dedupe_key
- **Location**: `autocapture_nx/processing/idle.py`, `autocapture_nx/processing/sst/persist.py`, `autocapture/storage/database.py`
- **Description**: Enforce dedupe_key on all workers to prevent duplicate artifacts.
- **Complexity**: 6
- **Dependencies**: Task 3.3
- **Acceptance Criteria**:
  - Re-run processing does not create duplicates; status updates instead.
- **Validation**:
  - Idempotency test with repeated input.

### Task 4.2: Processing watchdog + heartbeats + retries
- **Location**: `autocapture/runtime/scheduler.py`, `autocapture_nx/processing/idle.py`, `autocapture_nx/kernel/telemetry.py`
- **Description**: Add watchdog to detect stalled jobs; implement retry policy and visible status. Default stall rule: mark stalled after 3 missed heartbeats or 120s without progress (whichever is longer), retry up to 3 times with exponential backoff.
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Stalled jobs are marked and retried automatically; UI shows status.
- **Validation**:
  - Forced hang test triggers watchdog.

### Task 4.3: Deterministic replay engine + diff reports
- **Location**: `autocapture_nx/kernel/replay.py`, `autocapture_nx/kernel/query.py`, `autocapture_nx/ux/facade.py`
- **Description**: Implement replay by time range or frame hash and record diffs against prior artifacts.
- **Complexity**: 7
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Replay produces new job_id and diff report for changed outputs.
- **Validation**:
  - Replay test validates diff entries.

### Task 4.4: Citations-required default answers
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/kernel/query.py`, `autocapture_nx/ux/facade.py`
- **Description**: Make citations required by default; return conservative response with diagnostics if uncitable.
- **Complexity**: 5
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Answer API fails/soft-fails when citations missing and states when evidence is indeterminate.
- **Validation**:
  - Unit test for uncitable queries.

### Task 4.5: Summaries as artifacts with inputs + model hash
- **Location**: `autocapture_nx/processing/sst/persist.py`, `autocapture_nx/kernel/derived_records.py`
- **Description**: Persist summaries as artifacts with prompt/model hash and input list; enable daily digest generation.
- **Complexity**: 6
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Summary artifacts show inputs and model hashes.
- **Validation**:
  - Test summary record includes provenance.

### Task 4.6: Per-job debug bundle export (no raw media)
- **Location**: `autocapture_nx/kernel/proof_bundle.py`, `autocapture_nx/ux/facade.py`, `autocapture_nx/windows/tray.py`
- **Description**: Export per-job debug bundle with inputs/hashes/versions/logs; exclude raw media by default.
- **Complexity**: 5
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Bundle includes required diagnostics and no raw media.
- **Validation**:
  - Debug bundle contents test.

### Task 4.7: Nightly idle-only DB↔index consistency sweeps
- **Location**: `autocapture_nx/processing/idle.py`, `autocapture/indexing/factory.py`, `autocapture_nx/kernel/query.py`
- **Description**: Implement idle-only consistency sweeps and repairs for lexical/vector indexes plus orphan cleanup and vector sidecar checks.
- **Complexity**: 5
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Sweep repairs missing index entries; does not run while user active.
- **Validation**:
  - Integration test with removed index entries.

### Task 4.8: Retrieval strategy + trace
- **Location**: `autocapture/indexing/factory.py`, `autocapture_nx/kernel/query.py`
- **Description**: Add lexical-first fallback, vector sidecar usage, and retrieval trace output for explain panel.
- **Complexity**: 6
- **Dependencies**: Task 4.4
- **Acceptance Criteria**:
  - Retrieval trace includes strategy and top spans.
- **Validation**:
  - Unit tests for lexical-first fallback behavior.

## Sprint 5: UI/UX for Memory Replacement
**Goal**: Q&A-first UI with provenance, proof, and accessibility.
**Demo/Validation**:
- Home page shows Q&A, proof chips, and citations.
- Timeline groups sessions with gap markers.

### Task 5.1: Home/Today omnibox + “What happened today”
- **Location**: `autocapture/web/ui/index.html`, `autocapture/web/ui/app.js`, `autocapture/web/ui/styles.css`
- **Description**: Redesign home to be Q&A-first with omnibox and suggested queries; integrate daily digest results.
- **Complexity**: 6
- **Dependencies**: Task 4.4
- **Acceptance Criteria**:
  - Home opens with Q&A input and cited answer response.
- **Validation**:
  - Manual UI walkthrough.

### Task 5.2: Session-grouped timeline with gaps
- **Location**: `autocapture/web/ui/app.js`, `autocapture_nx/ux/facade.py`
- **Description**: Group timeline by HID sessions + app focus; show gaps with reasons.
- **Complexity**: 5
- **Dependencies**: Task 3.6
- **Acceptance Criteria**:
  - Timeline shows sessions, durations, and gap markers.
- **Validation**:
  - UI snapshot tests or manual verification.

### Task 5.3: Item detail view with core metadata at top
- **Location**: `autocapture/web/ui/index.html`, `autocapture/web/ui/app.js`
- **Description**: Show hashes, timestamps, monitor, app/window, trigger, trust at top with processing status below.
- **Complexity**: 5
- **Dependencies**: Task 2.5
- **Acceptance Criteria**:
  - Item detail surfaces required metadata without scrolling.
- **Validation**:
  - Manual UI validation.

### Task 5.4: Explain-answer panel + proof chips
- **Location**: `autocapture/web/ui/app.js`, `autocapture_nx/ux/facade.py`
- **Description**: Add explain panel with retrieval trace, top spans, and proof chips (Captured/OCR/Embed/Summary).
- **Complexity**: 6
- **Dependencies**: Task 4.8
- **Acceptance Criteria**:
  - Proof chips display job_id + hashes and open underlying artifacts and inputs.
- **Validation**:
  - UI interaction tests.

### Task 5.5: Capture status panel everywhere + pipeline state machine
- **Location**: `autocapture/web/ui/app.js`, `autocapture/web/ui/index.html`, `autocapture_nx/ux/facade.py`
- **Description**: Display capture/processing state and pause reasons on all pages; include pipeline state machine labels.
- **Complexity**: 4
- **Dependencies**: Task 1.5
- **Acceptance Criteria**:
  - All views show capture status and processing state.
- **Validation**:
  - Manual UI check across tabs.

### Task 5.6: Cognitive accessibility mode
- **Location**: `autocapture/web/ui/styles.css`, `autocapture/web/ui/app.js`
- **Description**: Add low-choice UI mode, large targets, keyboard-first navigation, reduced-motion toggle.
- **Complexity**: 5
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Keyboard navigation works; reduced-motion honored.
- **Validation**:
  - Accessibility test suite (IX-10).

### Task 5.7: Fast recall templates and trust indicators
- **Location**: `autocapture/web/ui/app.js`, `autocapture_nx/ux/facade.py`
- **Description**: Add one-click time/app/person templates and show trust indicators near answers.
- **Complexity**: 4
- **Dependencies**: Task 3.6
- **Acceptance Criteria**:
  - Templates insert queries and return cited answers.
- **Validation**:
  - UI sanity check.

### Task 5.8: Runbook and diagnostics entry points
- **Location**: `autocapture/web/ui/index.html`, `autocapture/web/ui/app.js`
- **Description**: Integrate runbook into UI with diagnostics bundle action and safe mode guidance.
- **Complexity**: 4
- **Dependencies**: Task 4.6
- **Acceptance Criteria**:
  - Help page links to diagnostics export and safe mode instructions.
- **Validation**:
  - Manual UI check.

### Task 5.9: Tray companion update (no capture pause)
- **Location**: `autocapture_nx/windows/tray.py`, `autocapture_nx/tray.py`
- **Description**: Ensure tray offers processing pause, safe mode, diagnostics, and status only; no capture pause or delete actions.
- **Complexity**: 4
- **Dependencies**: Task 1.5
- **Acceptance Criteria**:
  - Tray contains status and safe mode/diagnostics actions only.
- **Validation**:
  - Manual tray menu validation.

## Sprint 6: Plugin Manager Hardening and Sandbox
**Goal**: Robust plugin lifecycle with permissions, sandboxing, and health visibility.
**Demo/Validation**:
- Install/update/rollback is atomic.
- Conflicting plugins are blocked until resolved.

### Task 6.1: Plugin IA redesign (Installed/Catalog/Updates/Permissions/Health)
- **Location**: `autocapture/web/ui/index.html`, `autocapture/web/ui/app.js`, `autocapture_nx/plugin_system/manager.py`
- **Description**: Implement plugin manager UI and API for the new information architecture.
- **Complexity**: 6
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - User can navigate all plugin tabs and see status summaries.
- **Validation**:
  - Manual UI walkthrough.

### Task 6.2: Atomic install/update/rollback with staging
- **Location**: `autocapture_nx/plugin_system/registry.py`, `autocapture_nx/plugin_system/manager.py`, `contracts/plugin_manifest.schema.json`
- **Description**: Stage plugin changes, verify hashes, run self-tests, and atomically swap with rollback points; support explicit pip/git installs.
- **Complexity**: 7
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Interrupted updates leave previous version intact; rollback works.
- **Validation**:
  - Plugin update interruption test.

### Task 6.3: Compatibility gating and manifest constraints
- **Location**: `autocapture_nx/plugin_system/manifest.py`, `contracts/plugin_manifest.schema.json`
- **Description**: Enforce OS/app/schema/python/GPU compatibility checks before enable.
- **Complexity**: 5
- **Dependencies**: Task 6.2
- **Acceptance Criteria**:
  - Incompatible plugin enable is blocked with explicit reason.
- **Validation**:
  - Unit tests for compatibility rules.

### Task 6.4: Two-phase enable with health check
- **Location**: `autocapture_nx/plugin_system/runtime.py`, `autocapture_nx/plugin_system/host.py`
- **Description**: Implement sandbox load -> health check -> enable flow; capture failures without crashing.
- **Complexity**: 6
- **Dependencies**: Task 6.2
- **Acceptance Criteria**:
  - Plugin import failures never crash core; enable fails safely.
- **Validation**:
  - Faulty plugin enable test.

### Task 6.5: Permission UX + PolicyGate tightening
- **Location**: `autocapture/plugins/policy_gate.py`, `autocapture_nx/plugin_system/runtime.py`, `autocapture/web/ui/app.js`
- **Description**: Deny-by-default permissions with explicit UI approval per plugin; maintain allowlists.
- **Complexity**: 5
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Network/shell access denied unless explicitly approved; denials logged.
- **Validation**:
  - PolicyGate unit tests.

### Task 6.6: Out-of-process sandbox + JobObject caps
- **Location**: `autocapture_nx/plugin_system/host.py`, `autocapture_nx/windows/win_sandbox.py`, `autocapture_nx/plugin_system/runtime.py`
- **Description**: Default untrusted plugins to subprocess with IPC and JobObject CPU/RAM limits.
- **Complexity**: 8
- **Dependencies**: Task 6.4
- **Acceptance Criteria**:
  - Misbehaving plugin cannot exceed caps; core remains stable.
- **Validation**:
  - Resource cap integration test.

### Task 6.7: Plugin health dashboard + logs/traces
- **Location**: `autocapture_nx/plugin_system/runtime.py`, `autocapture_nx/kernel/telemetry.py`, `autocapture/web/ui/app.js`
- **Description**: Track plugin errors, latency, memory, denials, restarts; expose per-plugin log tail.
- **Complexity**: 6
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Health panel shows last error and resource usage.
- **Validation**:
  - Unit test for health metrics emission.

### Task 6.8: Safe mode recovery wizard + conflict resolution UI
- **Location**: `autocapture_nx/kernel/loader.py`, `autocapture_nx/windows/tray.py`, `autocapture/web/ui/app.js`
- **Description**: Add safe mode wizard and conflict resolution UI; block enable until conflicts resolved.
- **Complexity**: 6
- **Dependencies**: Task 6.2
- **Acceptance Criteria**:
  - Conflict detection blocks enable; safe mode allows stepwise re-enable.
- **Validation**:
  - UI flow tests for conflict resolution.

### Task 6.9: Optional plugin signing + trust levels
- **Location**: `autocapture_nx/plugin_system/registry.py`, `autocapture_nx/plugin_system/manifest.py`
- **Description**: Add signing verification and trust levels (untrusted/trusted/signed) with optional enforcement.
- **Complexity**: 5
- **Dependencies**: Task 6.2
- **Acceptance Criteria**:
  - Unsigned plugin blocked when signing required.
- **Validation**:
  - Signing verification tests.

## Sprint 7: Security, Export, Backup/Migration, and Service Split
**Goal**: Localhost-only security, encrypted storage, sanitized export, and robust service architecture.
**Demo/Validation**:
- Non-loopback bind fails closed.
- Export creates sanitized bundle with audit entry.
- Kernel service survives UI crash; safe mode triggers on crash loop.

### Task 7.1: Enforce loopback-only bind + firewall rule
- **Location**: `autocapture_nx/kernel/system.py`, `autocapture_nx/kernel/loader.py`, `autocapture/gateway/app.py`
- **Description**: Reject non-loopback binds at runtime; install firewall rule for loopback-only access.
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Non-loopback bind causes startup failure with explicit audit log entry.
- **Validation**:
  - Localhost security regression test (IX-8).

### Task 7.2: Session unlock (Windows Hello) + remove URL token
- **Location**: `autocapture_nx/kernel/auth.py`, `autocapture/web/ui/app.js`, `autocapture/web/ui/index.html`
- **Description**: Use in-memory session tokens with short TTL; remove unlock tokens from URLs.
- **Complexity**: 6
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Refresh never exposes token; session expires and requires re-unlock.
- **Validation**:
  - Auth flow unit test.

### Task 7.3: Default-on at-rest encryption + key escrow
- **Location**: `autocapture_nx/kernel/keyring.py`, `autocapture/storage/sqlcipher.py`, `autocapture/storage/media_store.py`, `autocapture_nx/windows/dpapi.py`
- **Description**: Enable encryption for DB and media; unlock via Windows Hello; escrow keys for backup/migration.
- **Complexity**: 8
- **Dependencies**: Task 7.2
- **Acceptance Criteria**:
  - Locked state denies protected endpoints; unlock restores access.
- **Validation**:
  - Encryption smoke test with lock/unlock.

### Task 7.4: Append-only audit log for privileged actions
- **Location**: `autocapture_nx/kernel/proof_bundle.py`, `autocapture_nx/kernel/event_builder.py`, `autocapture_nx/kernel/loader.py`
- **Description**: Record unlock/export/plugin/config actions in append-only audit log and ledger.
- **Complexity**: 5
- **Dependencies**: Task 3.5
- **Acceptance Criteria**:
  - Audit entries are chained and verifiable.
- **Validation**:
  - Audit log verification test.

### Task 7.5: Export-only sanitization pipeline
- **Location**: `autocapture_nx/kernel/egress_approvals.py`, `autocapture_nx/kernel/query.py`, `autocapture_nx/ux/facade.py`
- **Description**: Implement export flow with entity hashing, preview warnings, and audit entries; never mutate local raw store.
- **Complexity**: 7
- **Dependencies**: Task 3.7
- **Acceptance Criteria**:
  - Export bundle contains only sanitized artifacts and manifest with ledger head.
- **Validation**:
  - Export pipeline integration test.

### Task 7.6: Export review UI (local-only entity dictionary)
- **Location**: `autocapture/web/ui/app.js`, `autocapture/web/ui/index.html`, `autocapture_nx/ux/facade.py`
- **Description**: Show hashed entity dictionary locally after unlock; allow exclusions; ensure dictionary is not exported.
- **Complexity**: 5
- **Dependencies**: Task 7.5
- **Acceptance Criteria**:
  - Export UI shows entity list; exported bundle excludes dictionary.
- **Validation**:
  - UI + export content tests.

### Task 7.7: Vendor binary SHA verification
- **Location**: `autocapture_nx/kernel/system.py`, `contracts/lock.json`
- **Description**: Verify SHA256 for vendor binaries (ffmpeg/qdrant) and fail closed on mismatch.
- **Complexity**: 4
- **Dependencies**: Task 7.1
- **Acceptance Criteria**:
  - Corrupt binary hash prevents startup with explicit error.
- **Validation**:
  - Unit test for hash mismatch handling.

### Task 7.8: CSP + CSRF hardening and secrets scanning
- **Location**: `autocapture/gateway/app.py`, `autocapture/web/ui/index.html`, `tools/run_all_tests.py`
- **Description**: Add CSP/CSRF protections for localhost UI; add secret scanning and log redaction tests.
- **Complexity**: 6
- **Dependencies**: Task 7.1
- **Acceptance Criteria**:
  - CSP/CSRF headers present; CI fails on secrets in logs.
- **Validation**:
  - Localhost security tests + log redaction tests.

### Task 7.9: Encrypted backup/restore + migration workflow
- **Location**: `autocapture/storage/archive.py`, `autocapture_nx/kernel/proof_bundle.py`, `autocapture_nx/kernel/keyring.py`
- **Description**: Implement backup/restore with encrypted bundles and ledger continuity; support migration to new machine.
- **Complexity**: 7
- **Dependencies**: Task 7.3
- **Acceptance Criteria**:
  - Restore recreates data and citations; ledger verifies after restore.
- **Validation**:
  - Backup/restore integration test.

### Task 7.10: Windows Service split + supervisor + crash-loop safe mode
- **Location**: `autocapture_nx/windows`, `autocapture_nx/kernel/loader.py`, `autocapture_nx/cli.py`, `autocapture_nx/windows/tray.py`
- **Description**: Run capture+DB+journal as Windows Service; UI/processing in user space; safe mode triggers after crash loop.
- **Complexity**: 8
- **Dependencies**: Task 1.4
- **Acceptance Criteria**:
  - Service continues capture when UI crashes; safe mode starts capture-only after repeated failures (default: >3 restarts within 600s).
- **Validation**:
  - Manual crash-loop simulation on Windows runner.

## Sprint 8: Observability, Performance, and QA/Test Suites
**Goal**: Guarantee performance budgets, observability, and full automated coverage.
**Demo/Validation**:
- SLO dashboard and error budgets visible.
- CPU/RAM caps enforced; GPU preemption on activity.
- All test suites pass.

### Task 8.1: Expand metrics and correlation IDs
- **Location**: `autocapture_nx/kernel/telemetry.py`, `autocapture_nx/kernel/event_builder.py`, `autocapture_nx/capture/pipeline.py`
- **Description**: Add new metrics (latency histograms, queue depth p95, last capture age, throttle events) and correlation IDs in logs.
- **Complexity**: 6
- **Dependencies**: Task 1.5
- **Acceptance Criteria**:
  - Metrics emitted and visible in UI; logs include frame_id/job_id/plugin_id.
- **Validation**:
  - Metrics unit tests + log sampling test.

### Task 8.2: SLO dashboard + error budgets
- **Location**: `autocapture/web/ui/app.js`, `autocapture_nx/ux/facade.py`, `autocapture_nx/kernel/alerts.py`
- **Description**: Compute SLOs and error budgets and display in UI; integrate pipeline state machine.
- **Complexity**: 5
- **Dependencies**: Task 8.1
- **Acceptance Criteria**:
  - UI shows pass/fail SLOs and last 24h error budget.
- **Validation**:
  - UI validation with seeded metrics.

### Task 8.3: Silent failure detector (HID active, no captures)
- **Location**: `autocapture/runtime/activity.py`, `autocapture_nx/kernel/alerts.py`, `autocapture_nx/windows/tray.py`
- **Description**: Detect capture silence while HID active and emit alert + tray notification.
- **Complexity**: 5
- **Dependencies**: Task 1.4
- **Acceptance Criteria**:
  - Alert fires within configured window during capture failure.
- **Validation**:
  - Simulated capture stall test.

### Task 8.4: Performance enforcement and tuning
- **Location**: `autocapture_nx/capture/pipeline.py`, `autocapture_nx/kernel/hashing.py`, `autocapture_nx/windows/win_sandbox.py`, `autocapture/runtime/budgets.py`, `autocapture/storage/database.py`
- **Description**: Default GPU encoding with fallback ladder, BLAKE3 hashing parallelization, short DB transactions + batching, GPU preemption on activity (<=1s for processing workloads), JobObject CPU/RAM caps, idle GPU OCR/embedding, and latency budget tracking (p95 thresholds). Allow capture encoding to use GPU even when user active if the foreground app is not fullscreen.
- **Complexity**: 8
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - CPU/RAM remain <= 50% while idle; GPU usage allowed in idle; GPU preempted on activity.
- **Validation**:
  - Resource budget tests (IX-6) and perf checks.

### Task 8.5: QA/Test harness completion
- **Location**: `tools/run_all_tests.py`, `tests/`, `autocapture_nx/processing`, `autocapture_nx/plugin_system`
- **Description**: Implement and wire test suites: golden dataset, chaos tests, migration tests, e2e Q&A, plugin manifest fuzzing, resource budgets, Windows integration, localhost security, provenance tamper detection, accessibility suite.
- **Complexity**: 8
- **Dependencies**: Task 8.1
- **Acceptance Criteria**:
  - All IX test suites exist and pass via `python3 tools/run_all_tests.py`.
- **Validation**:
  - Run full test harness; confirm pass.

## Testing Strategy
- Use `python3 tools/run_all_tests.py` as the primary suite; keep `dev.sh test` parity.
- Add unit tests alongside modules for hashing, journaling, policy gate, and ledger verification.
- Add integration tests for capture pipeline, export sanitization, backup/restore, and plugin install/rollback.
- Add Windows-specific integration tests for Desktop Duplication capture and RawInputListener.
- Include e2e UI/Q&A tests that verify citations resolve to media/spans.

## Potential Risks & Gotchas
- Large schema migrations (Frame v2, JobRun) can invalidate old records; require backups and migration tests.
- Windows Service split and firewall rules require installer/ops coordination; verify no admin command usage in repo.
- JobObject CPU/RAM caps may conflict with Python subprocess behavior; validate on real Win11 runner.
- Segment store and sharded paths must preserve exact bytes for citeability; verify hash stability.
- Export sanitization must never mutate local raw store; guard with tests and audit logging.

## Rollback Plan
- Before migrations, create encrypted backup via new backup workflow and keep prior DB/media paths read-only.
- Keep feature flags/config toggles for new storage modes and processing policies to revert behavior without data loss.
- Preserve previous plugin versions and rollback points for any update.
- If a sprint introduces instability, revert to last passing release and re-run migration verification before retry.
