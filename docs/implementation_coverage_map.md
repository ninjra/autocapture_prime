# Implementation Coverage Map

## Sprint 1 Coverage
- SRC-020, SRC-016: No-deletion mode enforced in `autocapture/storage/retention.py` and `autocapture_nx/cli.py`.
- SRC-021, SRC-145: Memory Replacement (Raw) preset applied via `autocapture_nx/kernel/config.py` and `config/default.json`.
- SRC-007: Foreground gating activity signal strengthened with display power status in `plugins/builtin/input_windows/plugin.py`.

## Sprint 2 Coverage
- SRC-019: Capture journal staging/commit/unavailable + startup reconcile in `autocapture_nx/kernel/event_builder.py`, `autocapture_nx/kernel/loader.py`, and `autocapture_nx/kernel/metadata_store.py` with coverage in `tests/test_capture_journal_reconcile.py`.
- SRC-023: Disk watermarks + hard halt surfaced through `autocapture/storage/pressure.py`, `autocapture_nx/capture/pipeline.py`, `autocapture_nx/kernel/alerts.py`, `autocapture/web/ui/app.js`, and `autocapture_nx/tray.py` (tests: `tests/test_capture_disk_pressure_degrade.py`).

## Sprint 3 Coverage
- SRC-026: Startup integrity sweep + stale evidence markers in `autocapture_nx/kernel/loader.py` and `autocapture_nx/kernel/query.py` with coverage in `tests/test_integrity_sweep_stale.py`.

## Sprint 4 Coverage
- SRC-010, SRC-133, SRC-134: Trace APIs + UI for capture → derived evidence lineage in `autocapture_nx/ux/facade.py`, `autocapture/web/routes/trace.py`, `autocapture/web/routes/media.py`, `autocapture/web/ui/app.js`, and `autocapture/web/ui/index.html` with coverage in `tests/test_trace_facade.py`.

## Sprint 5 Coverage
- I-9: Crash-loop safe mode detection + safe-mode overrides in `autocapture_nx/kernel/loader.py`, `autocapture_nx/kernel/config.py`, `config/default.json`, and `contracts/config_schema.json` with coverage in `tests/test_crash_loop_safe_mode.py`.
- III-5: Processing watchdog heartbeat + status surfacing in `autocapture/runtime/conductor.py`, `autocapture_nx/ux/facade.py`, and `autocapture/web/ui/app.js`.
- SRC-044, SRC-152: Citations-required notices in `autocapture_nx/kernel/query.py` with coverage in `tests/test_query_citations_required.py`.

## Sprint 6 Coverage
- III-5: Processing watchdog alert escalation in `autocapture/runtime/conductor.py`, `autocapture_nx/kernel/alerts.py`, and `config/default.json` with coverage in `tests/test_watchdog_alerts.py`.
