# Plan: Adaptive Screenshot Capture (Ultralight, Dedupe, Idle-Aware)

**Generated**: 2026-02-08
**Estimated Complexity**: Medium

## Overview
Make screenshot capture the primary always-on capture stream:
- When user is **ACTIVE**: attempt capture every **0.5s** (2 fps) and **discard duplicates**.
- When user is **IDLE**: capture at **1 per 60s** (even if duplicate, to ensure time-series continuity).
- Keep CPU/RAM overhead low enough for 24/7 operation and never interfere with UX.
- Disable MP4/video capture by default for now, but keep the architecture compatible with future MP4 plugins.

This work optimizes for the 4 pillars:
- **Performance**: avoid full-frame hashing and expensive work on frames that will be dropped as duplicates.
- **Accuracy**: use a small, robust, deterministic fingerprint (downscaled thumbnail) for duplicate detection.
- **Security**: no new deletion pathways; store raw-first locally; keep sandbox and policy gates unchanged.
- **Citeability**: every saved screenshot has stable content hashes + metadata + evidence IDs and can be cited without reprocessing.

## Prerequisites
- Windows host for live screenshot capture plugins (`builtin.capture.screenshot.windows` is Windows-only).
- Existing `tracking.input` capability available in normal runs (for active/idle signals). If missing, fall back safely.

## Assumptions (Explicit)
- Define **ACTIVE** as `idle_seconds < 3.0` (same window as existing capture/video `active_window_s` default).
- If input tracking is unavailable, treat the user as **ACTIVE** (fail-open on capture frequency, fail-closed on processing elsewhere).
  - Rationale: screenshots are always relevant; dedupe keeps storage bounded; still low overhead.

## Sprint 1: Screenshot Capture Policy + Low Overhead Dedupe
**Goal**: Implement idle-aware screenshot frequency with deterministic dedupe that does not hash full frames.
**Demo/Validation**:
- Unit tests pass deterministically.
- Telemetry shows stable encode/write times and reduced per-iteration CPU.

### Task 1.1: Add Screenshot Activity Config (Active/Idle Rates)
- **Location**:
  - `contracts/config_schema.json`
  - `config/default.json`
  - `plugins/builtin/capture_screenshot_windows/plugin.py`
- **Description**:
  - Add `capture.screenshot.activity` section with:
    - `enabled` (bool)
    - `active_window_s` (number)
    - `active_interval_s` (number; default 0.5)
    - `idle_interval_s` (number; default 60)
    - `assume_active_when_missing` (bool; default true)
  - Implement policy in the capture loop:
    - In ACTIVE mode: schedule attempts at `active_interval_s`, set dedupe `force_interval_s=0`.
    - In IDLE mode: schedule attempts at `idle_interval_s`, set dedupe `force_interval_s=idle_interval_s` (store at least one per idle interval).
- **Complexity**: 6
- **Dependencies**: None
- **Acceptance Criteria**:
  - ACTIVE: attempts ~2 fps but duplicates are skipped (no writes).
  - IDLE: at least one saved screenshot every 60s even if unchanged.
- **Validation**:
  - Add `tests/test_screenshot_activity_policy.py` with a fake `tracking.input` and mocked time.

### Task 1.2: Replace Full-Frame Hashing With Thumbnail Fingerprint
- **Location**: `plugins/builtin/capture_screenshot_windows/plugin.py`, `autocapture_nx/capture/screenshot.py`
- **Description**:
  - Do not compute `sha256(img.tobytes())` every loop.
  - Compute dedupe fingerprint over a small deterministic thumbnail (e.g. 96x54 or 64x64) to keep CPU constant across resolutions.
  - Compute/record heavy hashes only when we actually store:
    - `content_hash` over the stored PNG bytes (already present).
    - Optionally record `pixel_hash` derived from the thumbnail bytes with explicit algo metadata (`thumb_sha256`), not full raw frame.
- **Complexity**: 7
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - No full-frame hashing on skipped duplicates.
  - Duplicate detection remains stable on the fixture screenshots.
- **Validation**:
  - Extend unit tests to assert the expensive hashing function is not called when `should_store` is false (use monkeypatch/mocks).

### Task 1.3: Dedupe Defaults Tuned For Ultralight Operation
- **Location**: `config/default.json`
- **Description**:
  - Keep dedupe enabled.
  - Remove/avoid `sample_bytes=0` for raw frames (should not matter after Task 1.2).
  - Ensure the policy always allows a forced store at idle cadence.
- **Complexity**: 3
- **Dependencies**: Task 1.2
- **Validation**:
  - Run `python3 -m json.tool config/default.json` and config validation tests.

## Sprint 2: Disable MP4 By Default (Keep Future Compatibility)
**Goal**: Screenshots-only capture by default; preserve a clean upgrade path to MP4.
**Demo/Validation**:
- Default config does not start video capture.
- Fixtures and query flows still work via screenshots.

### Task 2.1: Disable Video Capture In Default Config
- **Location**: `config/default.json`
- **Description**:
  - Set `capture.video.enabled=false` in defaults.
  - Keep existing video settings in schema and code so enabling later is a config flip, not a rewrite.
- **Complexity**: 2
- **Dependencies**: None
- **Validation**:
  - Add `tests/test_default_config_disables_video.py` to assert default config disables video capture.

### Task 2.2: Preserve Segment Flush Support For Future MP4
- **Location**: `autocapture_nx/capture/pipeline.py`
- **Description**:
  - Keep `FLUSH_SENTINEL` support (already implemented) to make active/idle transitions safe for future MP4.
  - Ensure it is covered by unit test and does not affect screenshot-only mode.
- **Complexity**: 2
- **Dependencies**: None
- **Validation**:
  - Existing `tests/test_capture_flush_sentinel.py` remains green.

## Testing Strategy
- Unit tests only (deterministic, low-resource):
  - Screenshot activity policy scheduling (mock time + fake tracker).
  - Dedupe fingerprint behavior and “no heavy hashing when skipping”.
  - Default config disables video capture.
- Integration fixtures (later, after Sprint 1-2):
  - Screenshot-only fixture pipeline uses `docs/test sample/*.png` and answers via metadata-only query.

## Potential Risks & Gotchas
- If input tracking is missing, ACTIVE-by-default could increase capture overhead.
  - Mitigation: thumbnail fingerprint + dedupe make it bounded; add a config toggle to assume idle instead.
- Per-monitor capture differences: multi-monitor layouts can cause small cursor/notification changes.
  - Mitigation: dedupe thumbnail is robust; forced idle saves ensure periodic samples regardless.
- “Never fail saving” vs dedupe: forced saves guarantee periodic snapshots even for static screens.

## Rollback Plan
- All changes are additive behind config defaults and tests.
- Revert by `git revert` of the commits that touch:
  - `plugins/builtin/capture_screenshot_windows/plugin.py`
  - `contracts/config_schema.json`
  - `config/default.json`
  - New tests.

