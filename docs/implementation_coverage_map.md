# Implementation Coverage Map

## Sprint 1 Coverage
- SRC-020, SRC-016: No-deletion mode enforced in `autocapture/storage/retention.py` and `autocapture_nx/cli.py`.
- SRC-021, SRC-145: Memory Replacement (Raw) preset applied via `autocapture_nx/kernel/config.py` and `config/default.json`.
- SRC-007: Foreground gating activity signal strengthened with display power status in `plugins/builtin/input_windows/plugin.py`.

## Sprint 2 Coverage
- SRC-019, SRC-026: Capture journal staging/commit/unavailable + startup reconcile in `autocapture_nx/kernel/event_builder.py`, `autocapture_nx/kernel/loader.py`, and `autocapture_nx/kernel/metadata_store.py` with coverage in `tests/test_capture_journal_reconcile.py`.
- SRC-023: Disk watermarks + hard halt surfaced through `autocapture/storage/pressure.py`, `autocapture_nx/capture/pipeline.py`, `autocapture_nx/kernel/alerts.py`, `autocapture/web/ui/app.js`, and `autocapture_nx/tray.py` (tests: `tests/test_capture_disk_pressure_degrade.py`).
