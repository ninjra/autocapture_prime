# Safe Mode

Autocapture enters **safe mode** when it detects a crash-loop or when you start it with `--safe-mode`.

Safe mode is designed to:
- Fail closed (avoid unsafe processing when the system state is uncertain).
- Keep capture and query available where possible.
- Make the reason and the next safe action explicit and deterministic.

## How To Check Safe Mode

- CLI: `autocapture status`
- Web API: `GET /api/status`

Both surfaces include:
- `safe_mode` (boolean)
- `safe_mode_reason` (string or null)
- `crash_loop` (object with `crash_count`, `max_crashes`, `safe_mode_until`, etc)

## Common Reasons

- `crash_loop`: The previous run did not shut down cleanly and the crash-loop policy triggered.
- `manual`: Safe mode was requested explicitly.

## Deterministic Next Steps (Checklist)

1. **Inspect status**
   - Confirm `safe_mode_reason` and `crash_loop.safe_mode_until` (if present).
2. **Run doctor**
   - `autocapture doctor`
3. **Verify integrity**
   - `autocapture integrity scan`
4. **If crash-loop is active**
   - Wait until `safe_mode_until` passes, or start in safe mode explicitly and investigate `kernel_error`.
5. **Collect diagnostics bundle (for support)**
   - `autocapture doctor --bundle` (if enabled in your build)

## Notes

- Safe mode is *not* a “delete/repair” tool. This project never deletes local evidence; recovery actions must be append-only and auditable.
- If disk pressure is the underlying problem, resolve it first. Capture can fail closed on hard low-disk.

