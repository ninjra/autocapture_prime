# Plan: Preset Config Response Validation

**Generated**: 2026-02-02
**Estimated Complexity**: Low

## Overview
Fix the Settings UI preset flow so it only reports “Preset applied” when `/api/config` succeeds. The current `applyPreset` calls `postConfigPatch`, which doesn’t inspect the HTTP response; the plan adds explicit response validation and error propagation, with minimal surface area changes and deterministic tests.

## Prerequisites
- **Decision (four-pillars optimized)**: Make `postConfigPatch` validate the HTTP response and return a structured result `{ok, status, data, error}`. Callers must handle the result and always surface user-facing error feedback. This avoids unhandled exceptions (stability), preserves accurate UI state (accuracy), and keeps processing lightweight (performance).
- **Decision**: Always show user-facing error feedback for quick toggles (privacy/fidelity) and presets; no silent failures.
- **Decision**: Include HTTP status codes in error messages when available (improves accuracy and debuggability without leaking secrets).

## Sprint 1: Response Validation + UI Feedback
**Goal**: Preset status reflects actual `/api/config` outcomes.
**Demo/Validation**:
- Manually trigger a failing patch (invalid config) and confirm UI shows “Preset failed …” instead of “Preset applied.”

### Task 1.1: Inspect shared config patch helper
- **Location**: `autocapture/web/ui/app.js`
- **Description**: Review `postConfigPatch` callers (`applyPreset`, quick privacy/fidelity toggles) to choose the least disruptive error propagation pattern.
- **Complexity**: 2
- **Dependencies**: None
- **Acceptance Criteria**:
  - Decision captured (Option A/B) and reflected in code changes.
- **Validation**:
  - Manual review of call sites in `app.js`.

### Task 1.2: Add response validation to `postConfigPatch`
- **Location**: `autocapture/web/ui/app.js:1419-1438`
- **Description**: Update `postConfigPatch` to inspect `resp.ok` and `data.error`, returning `{ok, status, data, error}`. Parse JSON defensively; if JSON parsing fails, fall back to `resp.statusText` or a safe string. Do not treat a non-OK response as success.
- **Complexity**: 3
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Preset success is only shown on HTTP OK with no API error payload.
  - Failure yields a useful message that includes status code when available.
- **Validation**:
  - Manual simulation with invalid patch or 401/403.

### Task 1.3: Update preset and quick-toggle call sites to surface errors
- **Location**: `autocapture/web/ui/app.js:1428-1438`, `autocapture/web/ui/app.js:2797-2885`
- **Description**: Make `applyPreset` inspect the structured result and only report success on `ok`. For quick privacy/fidelity toggles, display user-facing error feedback (e.g., reuse `quickPauseStatus` or introduce a small shared status banner) when the patch fails. Ensure no silent failure paths remain.
- **Complexity**: 3
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - No unhandled promise rejections in console during quick-toggle usage.
  - Every failed config patch surfaces visible feedback to the user.
- **Validation**:
  - Manual toggle of quick privacy/fidelity controls.

## Sprint 2: Deterministic Tests + Documentation
**Goal**: Lock in the new behavior with stable tests.
**Demo/Validation**:
- `python -m pytest tests/test_settings_ui_contract.py -q` passes.

### Task 2.1: Update UI contract test to enforce response checks
- **Location**: `tests/test_settings_ui_contract.py`
- **Description**: Add assertions that `postConfigPatch` or `applyPreset` inspects `resp.ok` and/or `data.error` and that preset success is gated on `ok`.
- **Complexity**: 2
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Test fails if response validation is removed.
- **Validation**:
  - Run the updated test.

### Task 2.2: Optional: add a small doc note
- **Location**: `README.md` or internal UI notes (if any)
- **Description**: Briefly note that presets report failure on invalid/unauthorized config patches.
- **Complexity**: 1
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Doc mention is concise and accurate.
- **Validation**:
  - Visual check.

## Testing Strategy
- Primary: `python -m pytest tests/test_settings_ui_contract.py -q`.
- Manual: Use a deliberately invalid patch or expired auth token to confirm error status.

## Potential Risks & Gotchas
- `postConfigPatch` is reused by quick privacy/fidelity toggles; switching it to throw could introduce unhandled rejections unless those call sites are updated.
- `readJson` may throw on non-JSON error responses; ensure error handling covers that.
- Avoid leaking auth token details in error strings.
- Ensure success messages are only shown after the response check; avoid overwriting errors with follow-on refresh calls.

## Rollback Plan
- Revert changes to `autocapture/web/ui/app.js` and `tests/test_settings_ui_contract.py`.
- Remove any doc additions if they prove misleading.
