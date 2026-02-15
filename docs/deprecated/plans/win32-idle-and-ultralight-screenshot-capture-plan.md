# Plan: Win32 Idle + Ultralight No-Loss Screenshot Capture

**Generated**: 2026-02-09
**Estimated Complexity**: High

## Overview
Improve always-on screenshot capture to be reliable for 24/7 operation without degrading UX:

- Replace pynput-based idle detection (event listeners) with **Win32 `GetLastInputInfo` polling** for low overhead and deterministic idle time.
- Keep **full-fidelity PNG evidence** persistence, but remove **PNG encoding from the capture thread** on backpressure: capture must prioritize sampling cadence and never block on CPU-heavy compression.
- Maintain the existing architectural separation:
  - capture (ultralight, foreground safe)
  - ingestion (durable raw-first stores)
  - processing (idle-time only, batched)
  - query (metadata-only, citation-first)
- Add a repo-wide functional scan + recommendations aligned to the 4 pillars: Performance, Accuracy, Security, Citeability.

## One Round Of Questions (If You Reply, These Override Assumptions)
1. Should `tracking.input` continue to record derived input activity counts (no raw keys/mouse), or should it become *idle-only* by default?
2. For the 24h soak that includes *live* screenshots, should the soak runner be Windows (recommended) or WSL (processor-only, using fixtures/ingest)?
3. For overflow spooling under backpressure, do you prefer:
   - A) spool raw RGB frames (fast CPU, high disk bandwidth), or
   - B) spool PNG at compression level 0/1 (some CPU, lower disk bandwidth)?

If unanswered, I will assume:
- derived-only input tracking is acceptable (no raw key logging by default),
- live capture soak should run on Windows,
- prefer option B (PNG level 0/1) as the best CPU/disk tradeoff for most machines.

## Prerequisites
- Windows host available for live capture plugins:
  - `builtin.capture.screenshot.windows`
  - `builtin.tracking.input.windows` (will be extended for Win32 idle)
- WSL remains the preferred environment for deterministic unit tests and most processing flows.

## Sprint 1: Win32 Idle Detection (Replace pynput-as-idle)
**Goal**: `idle_seconds` uses Win32 polling (low overhead), while keeping `activity_signal()` API stable.
**Demo/Validation**:
- Capture scheduling flips active/idle correctly without pynput listeners.
- Unit tests pass in WSL by mocking Win32 calls (no Windows dependency in tests).

### Task 1.1: Add Win32 Idle Helper
- **Location**: `autocapture_nx/windows/win_idle.py` (new)
- **Description**:
  - Implement `idle_seconds()` using:
    - `GetLastInputInfo` + `GetTickCount64` (or `GetTickCount` with wrap handling).
  - Return `None` when unavailable; never throw on non-Windows.
- **Complexity**: 5
- **Dependencies**: None
- **Acceptance Criteria**:
  - On Windows: stable idle seconds that matches OS idle time.
  - On non-Windows: safe `None`.
- **Validation**:
  - New unit tests that patch helper functions and validate wrap logic.

### Task 1.2: Extend `builtin.tracking.input.windows` To Support `mode=win32_idle`
- **Location**:
  - `plugins/builtin/input_windows/plugin.py`
  - `contracts/config_schema.json` (enumeration doc)
  - `config/default.json` (default mode selection)
- **Description**:
  - Add mode `win32_idle`:
    - does **not** import or start `pynput` listeners
    - uses `autocapture_nx.windows.win_idle.idle_seconds()` for idle time
    - preserves display/screen-saver heuristics already present
  - Keep existing modes:
    - `raw` (pynput + raw event payloads)
    - `activity` (pynput but no raw key content; derived only)
    - `off`
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - With `mode=win32_idle`, the plugin is usable without pynput installed.
  - `activity_signal()` still returns `idle_seconds`, `user_active`, `activity_score`.
- **Validation**:
  - Unit tests: patch `win_idle.idle_seconds()` and assert `activity_signal()` outputs.

### Task 1.3: Capture Policy Uses Win32 Idle by Default
- **Location**: `config/default.json`
- **Description**:
  - Switch default `capture.input_tracking.mode` to `win32_idle` (or keep `activity` if richer input tracking is required).
- **Complexity**: 2
- **Dependencies**: Task 1.2
- **Validation**:
  - Deterministic config tests and `doctor --self-test`.

## Sprint 2: No-Loss Backpressure Without Encoding In Capture Thread
**Goal**: capture loop never does PNG encoding on queue-full; it either enqueues or spools a lightweight representation quickly.
**Demo/Validation**:
- Under simulated slow storage, capture loop continues scheduling at target cadence.
- No evidence loss: all scheduled frames eventually persist to `storage.media` and `storage.metadata`.

### Task 2.1: Introduce “Spool Payload” Format For Screenshot Overflow
- **Location**:
  - `autocapture_nx/capture/overflow_spool.py`
  - `plugins/builtin/capture_screenshot_windows/plugin.py`
- **Description**:
  - Define a versioned spool record for screenshots that supports:
    - `encoding: png_fast` (compression 0/1) OR `encoding: raw_rgb`
    - required metadata (width/height/monitor/ts_utc/fingerprint)
  - Ensure spool records remain raw-first and deterministic (no pickle).
- **Complexity**: 7
- **Dependencies**: None
- **Acceptance Criteria**:
  - Backpressure path writes quickly and deterministically.
  - Drain converts spool records into canonical persisted PNG evidence.
- **Validation**:
  - Unit test writes N spooled items, drains them, and asserts metadata correctness.

### Task 2.2: Capture Thread Spools Without Full PNG Encode
- **Location**: `plugins/builtin/capture_screenshot_windows/plugin.py`
- **Description**:
  - Replace `_spool()` closure so it does not call the slow `_encode_and_build()` path.
  - Prefer:
    - `png_fast` using compression 0/1 (best tradeoff), OR
    - raw RGB with later encode in worker/drain.
- **Complexity**: 8
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - In queue-full, capture loop avoids heavy CPU and does not block longer than a bounded threshold.
- **Validation**:
  - Deterministic test with a full queue + mocked slow writer; assert spool path is used and loop continues.

### Task 2.3: Drain Path Encodes And Persists Canonical PNG
- **Location**: `plugins/builtin/capture_screenshot_windows/plugin.py`
- **Description**:
  - Implement drain handler for new spool formats:
    - if `png_fast`, store bytes directly but record correct hashes/metadata
    - if `raw_rgb`, reconstruct PIL image and encode PNG in the worker/drain (not capture loop)
- **Complexity**: 7
- **Dependencies**: Task 2.1
- **Validation**:
  - Drain test asserts stored blob is PNG and `content_hash` matches blob bytes.

### Task 2.4: Telemetry: Capture Loop Stall Budget
- **Location**:
  - `plugins/builtin/capture_screenshot_windows/plugin.py`
  - `autocapture_nx/kernel/telemetry.py` (if needed)
- **Description**:
  - Add explicit telemetry counters:
    - `capture.screenshot.loop_ms`
    - `capture.screenshot.queue_full`
    - `capture.screenshot.spooled_bytes`
    - `capture.screenshot.spooled_count`
  - These enable the orchestrator (and humans) to tune thresholds.
- **Complexity**: 4
- **Dependencies**: Sprint 2 tasks
- **Validation**:
  - Unit tests validate telemetry emission shape (not wall clock).

## Sprint 3: Soak Runner Correctness (Windows Capture vs WSL Processing)
**Goal**: avoid “soak appears to run but captures nothing” by making the runner environment-explicit.
**Demo/Validation**:
- A capture soak on Windows produces evidence IDs and non-zero frame counts.
- A processing soak on WSL can read the same data dir and run idle processing safely.

### Task 3.1: Add Soak Preflight That Asserts Evidence Is Being Produced
- **Location**: `tools/soak/run_24h_soak.sh`
- **Description**:
  - After startup, wait up to N seconds and verify:
    - a) screenshot frames counter increases, or
    - b) metadata store contains at least one new `evidence.capture.frame`
  - If not, exit with a clear message (e.g., “Windows-only capture plugin not running on this OS”).
- **Complexity**: 4
- **Dependencies**: None
- **Validation**:
  - Add a deterministic unit test for the preflight function (no 24h run in CI).

### Task 3.2: Add Windows Soak Script Wrapper
- **Location**: `tools/soak/run_24h_soak.ps1` (new) or `ops/dev/run_screenshot_soak_24h.ps1` integration
- **Description**:
  - Provide a Windows one-liner that runs the same kernel with:
    - a shared `AUTOCAPTURE_DATA_DIR` on `D:\...`
    - consent preflight/accept guidance
    - stable status output
- **Complexity**: 5
- **Dependencies**: Task 3.1
- **Validation**:
  - Manual smoke: confirm screenshot frames are being written.

## Sprint 4: Repo-Wide Functional Scan + 4-Pillar Recommendations
**Goal**: produce an actionable list of remaining optimizations and any unfinished implementations that matter for production.

### Task 4.1: Deterministic “Unfinished Work” Scanner
- **Location**: `tools/scan_unfinished.py` (new)
- **Description**:
  - Scan tracked code for: `TODO`, `FIXME`, `NotImplementedError`, placeholder stubs.
  - Default-ignore `docs/implemented-ignore/` and any user-declared ignore paths.
  - Output stable markdown report under `docs/reports/`.
- **Complexity**: 5
- **Validation**:
  - CI unit tests for stable output ordering.

### Task 4.2: Performance/Accuracy/Security/Citeability Recommendations Report
- **Location**: `docs/reports/four-pillars-recommendations.md` (new)
- **Description**:
  - Summarize findings from:
    - plugin timing telemetry
    - resource usage
    - evidence chain integrity
    - sandbox policy and hosting mode
  - Provide prioritized next actions.
- **Complexity**: 4

## Testing Strategy (Deterministic)
- Unit tests (WSL-safe):
  - Win32 idle code tested via mocks.
  - Screenshot scheduling policy tests (already deterministic).
  - Backpressure spool format encode/decode logic tested without real Windows APIs.
- Optional Windows-only integration smoke tests:
  - gated behind an env var (not run in CI).

## Potential Risks & Gotchas
- **WSL soak vs Windows-only capture**: must be explicit; otherwise soak may “run” with zero capture.
- **Spooling raw RGB** can saturate disk bandwidth under sustained backpressure. Mitigation: use `png_fast` default; keep overflow on a separate volume.
- **Consent** must remain fail-closed; reuse only previously accepted consent files in user-owned data roots.

## Rollback Plan
- Keep `mode=activity` available for `tracking.input` and keep the old spool path behind a config switch until soak is stable.
- Revert default config changes first if issues arise; keep new codepaths behind config toggles.

