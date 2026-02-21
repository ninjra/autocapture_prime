# Stage 1 Handoff Contract

## Scope
This contract defines the `autocapture handoff ingest|drain` boundary between Hypervisor spool output and Autocapture NX retained DataRoot.

## Input Handoff Directory
- Required:
  - `metadata.db`
- Optional:
  - `media/` (required when metadata payload references media files)
  - `activity/`

## Ingest Rules
- Metadata is merged first-class from handoff `metadata.db` into destination `metadata.db` with `INSERT OR IGNORE`.
- Media files are imported from `media/**`:
  - `--mode hardlink`: link first, copy fallback.
  - `--mode copy`: streamed copy only.
- Strict mode (`--strict`, default `true`) rejects handoff when referenced media files are missing.
- Runtime is fail-safe: errors abort the handoff, no marker is written, and pipeline does not delete anything locally.

## Completion Marker
On successful ingest, Stage 1 writes:
- `reap_eligible.json` (atomic write) in handoff root.

Schema:
- `schema`: `autocapture.handoff.reap_eligible.v1`
- `handoff_root`
- `dest_data_root`
- `ingested_at_utc`
- `ingest_run_id`
- `counts`:
  - `metadata_rows_copied`
  - `media_files_linked`
  - `media_files_copied`
  - `bytes_ingested`
- `integrity.dest_metadata_db_sha256`

Hypervisor reaper must only delete handoff directories when marker schema is valid.

## Journal Record
Destination metadata contains:
- `record_type`: `system.ingest.handoff.completed`
- Stable deterministic ID per handoff metadata hash.
- Counts and provenance fields for audit/citeability.
