# Operator Runbook

Scope: local-first operation and maintenance of Autocapture Prime (`autocapture_nx` runtime).

Non-negotiables enforced by policy/gates:
- Localhost-only services (bind to `127.0.0.1`).
- No deletion endpoints; archive/migrate only.
- Raw-first local store; sanitization only on explicit export/egress.
- Foreground gating: heavy processing only when user is idle.
- Default answers require citations.

## Backup and Restore

Backup objectives:
- `storage.metadata_path` (SQLite/SQLCipher) and index DBs.
- `storage.media_dir` (media blobs) and `storage.blob_dir` (if used).
- `data/runs/<run_id>/` (per-run logs, traces, host logs).
- `data/vault/` (keyring and root keys) if encrypted stores are used.

Recommended backup approach:
1. Stop the kernel cleanly.
2. Export a diagnostics bundle (see "Diagnostics").
3. Copy the entire `data_dir` to external storage.

Restore:
1. Place `data_dir` on the new machine (same directory layout).
2. Start the kernel with `AUTOCAPTURE_DATA_DIR` pointing to that directory.
3. Run `autocapture verify` to validate ledger + anchors + blob references.

## Safe Mode Triage

Symptoms:
- Kernel boots in safe mode (CLI `autocapture status` exit code 3).
- UI banner shows safe mode and missing capabilities.

Steps:
1. Run doctor: `autocapture doctor`.
2. Check plugin locks: `autocapture plugins status`.
3. If a plugin update caused the issue, rollback locks (see below).

## Plugin Rollback

Lock rollbacks are file-based and ledgered (no deletion).

Steps:
1. Inspect current and previous locks: `autocapture plugins locks --history`.
2. Apply rollback: `autocapture plugins rollback --to <lock_id>`.
3. Re-run doctor: `autocapture doctor`.

## Disk Pressure

When disk pressure reaches configured watermarks, capture may halt (fail closed) to avoid partial evidence.

Steps:
1. Check disk telemetry in UI or `autocapture status`.
2. Free space on the primary volume.
3. Optional: enable spillover routing to a secondary mounted drive via `storage.spillover`.

## Integrity Verification

Use:
- `autocapture verify` for integrity scan (ledger chain, anchors, blob references).
- `autocapture replay --bundle <path>` for proof bundle replay verification.

## Diagnostics

Diagnostics bundles are designed for support/debug without including raw media unless explicitly requested.

- `autocapture doctor --bundle <out.zip>` creates a bundle with:
  - config snapshots
  - plugin locks
  - doctor output
  - recent logs/telemetry
  - a manifest with sha256 for included files

