# Database Migrations

Autocapture Prime uses local SQLite (and optionally SQLCipher) databases under `data_dir` for:
- metadata
- indexing (lexical/vector)
- state tape / state-layer stores

## Goals

- Deterministic upgrades with explicit version pinning.
- No silent schema drift.
- Rollback is always possible without deleting evidence.

## Mechanism

- Each SQLite/SQLCipher database contains a `schema_migrations` table.
- Migrations are **forward-only by default**.
- If a down-migration is required, it must be explicitly implemented and tested; otherwise rollback is via restore.

## Rollback Plan (Default)

1. Create a backup bundle before upgrades:
   - `autocapture backup create --out backup.zip --include-data`
2. If an upgrade fails:
   - Stop Autocapture
   - Restore the backup bundle:
     - `autocapture backup restore --bundle backup.zip --overwrite`

This satisfies the “no deletion” policy by treating rollback as restore/migrate rather than pruning data in-place.

