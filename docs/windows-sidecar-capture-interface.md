# Windows Sidecar Capture Interface (Data Contract)

This document defines the exact interface another repository (the "Windows sidecar") must implement to provide capture data for processing by this repository (`autocapture_prime`).

## Scope

- In scope: the data contract the sidecar must produce so this repo can run the full processing workflow (derive -> index -> query) without using capture plugins inside WSL.
- Out of scope: sidecar implementation details (capture hooks, scheduling, UI), and any WSL capture/ingest code in this repo.

## Terms

- **Sidecar**: a Windows-native companion app/service that performs capture and ingest.
- **Processor**: this repo running on WSL (or Linux) and performing processing/index/query.
- **DataRoot**: the `storage.data_dir` directory containing the canonical local stores and append-only provenance logs.
- **Evidence record**: a JSON object with `record_type` starting with `evidence.` or `derived.` that validates against `contracts/evidence.schema.json`.
- **Journal**: `journal.ndjson` append-only event stream used for recovery and observability.
- **Ledger**: `ledger.ndjson` append-only hash-chained log used for audit/integrity.

## Contract Overview

The sidecar must provide captured frames plus Windows-side context (window metadata + input summaries) in the same on-disk contract the processor already understands.

Chronicle spool mode is also supported and versioned at:
- `contracts/chronicle/v0/chronicle.proto`
- `contracts/chronicle/v0/spool_format.md`

There are two supported interchange modes:

1. **Mode A (Recommended): Backup Bundle Handoff**
   - Sidecar maintains a full DataRoot, then periodically exports a **backup bundle zip**.
   - Processor restores the bundle into its own DataRoot and runs processing.
2. **Mode B: Shared DataRoot**
   - Sidecar writes directly into a DataRoot on a filesystem accessible to the processor.
   - Processor reads from that same DataRoot and runs processing.

Mode A is recommended because it provides a deterministic, integrity-checked handoff boundary and avoids cross-filesystem partial writes.

## Mode A: Backup Bundle Handoff (Recommended)

### What The Sidecar Must Produce

For each handoff, the sidecar produces:

- A zip file created by the built-in backup bundler (`autocapture_nx.kernel.backup_bundle`).
- The zip must include:
  - `config/user.json` (the effective user override used by the sidecar run)
  - `repo/config/plugin_locks.json`
  - `data/journal.ndjson` (if present)
  - `data/ledger.ndjson` (if present)
  - The relevant DB files and media/blob storage needed for processing:
    - `data/metadata.db` (if using SQLCipher metadata store)
    - `data/lexical.db`, `data/vector.db` (indexes, if present)
    - `data/state/state_tape.db`, `data/state/state_vector.db` (if present)
    - `data/media/...` and `data/blobs/...` (when `--include-data` is used)
  - A portable key bundle when encryption is enabled (recommended):
    - A keyring bundle embedded into the zip (requires a passphrase)

### Reference CLI (Sidecar)

These commands apply only if the sidecar repo vendors/installs the `autocapture` CLI (this repo’s runtime package). If not, implement the same behavior using the library entrypoints described above.

Target shell: PowerShell (Windows PowerShell 5.1)

```powershell
autocapture backup create --out C:\autocapture\handoff\backup.zip --include-data --keys --passphrase "REPLACE_ME" --overwrite
```

Target shell: Bash (WSL)

```bash
./.venv/bin/autocapture backup create --out /mnt/c/autocapture/handoff/backup.zip --include-data --keys --passphrase 'REPLACE_ME' --overwrite
```

Notes:
- If the passphrase is omitted or empty, the CLI will prompt.
- The sidecar should treat the passphrase as a secret; do not hardcode it.

### Reference CLI (Processor)

Target shell: Bash (WSL)

```bash
./.venv/bin/autocapture backup restore --bundle /mnt/c/autocapture/handoff/backup.zip --restore-keys --passphrase 'REPLACE_ME' --overwrite
```

After restoring, validate the processor environment:

Target shell: Bash (WSL)

```bash
./.venv/bin/autocapture doctor --self-test
```

## Mode B: Shared DataRoot

If the sidecar and processor share the same DataRoot directory:

- The sidecar MUST only perform **append-only** writes to `journal.ndjson` and `ledger.ndjson`.
- The sidecar MUST NOT delete, prune, or rewrite existing evidence records (policy: "no deletion").
- The sidecar MUST use atomic replace patterns for files it writes (write temp, `os.replace`), and fsync according to `storage.fsync_policy`.

This mode is inherently more fragile across NTFS <-> WSL boundaries; Mode A is preferred.

### Reality Check: What "DataRoot" Means (Do Not Point At `media/`)

In Mode B, **DataRoot is the directory that contains** (at minimum) `journal.ndjson`, `ledger.ndjson`, `metadata.db` (or `metadata/metadata.db`), and `media/`.

Example (WSL): `/mnt/d/autocapture`

- Screenshots may live under `/mnt/d/autocapture/media/...`, but **`/mnt/d/autocapture/media` is not the DataRoot**.

### Processor Execution (Mode B)

Once the sidecar is writing a valid Mode-B DataRoot, the processor should drain the full processing DAG (OCR/VLM/SST/state/index) using the batch runner:

Target shell: Bash (WSL)

```bash
AUTOCAPTURE_DATA_DIR=/mnt/d/autocapture AUTOCAPTURE_CONFIG_DIR=/mnt/d/autocapture/config_wsl ./.venv/bin/autocapture batch run
```

Notes:
- This is processing-only. It never captures.
- Foreground gating is enforced via the sidecar activity signal file (fail closed by default).

### Required Layout (Mode B, Flat DataRoot)

This repo’s processor can be configured to treat the shared DataRoot as `storage.data_dir`.

If you are using `/mnt/d/autocapture` as the DataRoot, the sidecar MUST write:

- `/mnt/d/autocapture/journal.ndjson`
- `/mnt/d/autocapture/ledger.ndjson`
- `/mnt/d/autocapture/metadata.db` (SQLite, see schema below)
- `/mnt/d/autocapture/media/` (canonical media blob store, see layout below)
- `/mnt/d/autocapture/activity/activity_signal.json` (foreground gating signal)

Important:
- If you set `storage.data_dir` to `/mnt/d/autocapture`, you MUST also set storage paths to match this flat layout (otherwise defaults like `data/media` will resolve to `/mnt/d/autocapture/data/media`).
  - `storage.media_dir` MUST be `media`
  - `storage.metadata_path` MUST be `metadata.db`

### Required: Sidecar Activity Signal File (Foreground Gating)

Foreground gating requires a sidecar-provided activity signal so this repo can pause heavy processing while the user is active.

The sidecar MUST write a JSON file (atomic replace) at one of:

1. `<DataRoot>/activity/activity_signal.json` (recommended)
2. `<DataRoot>/activity_signal.json` (fallback)

The processor reads this file (best-effort) when no in-process `tracking.input` provider exists.

#### Schema (Exact Fields)

```json
{
  "ts_utc": "2026-02-10T12:34:56.789+00:00",
  "idle_seconds": 3.2,
  "user_active": true,
  "source": "windows-sidecar",
  "seq": 12345
}
```

Rules:
- `ts_utc`: ISO-8601 UTC timestamp string.
- `idle_seconds`: number (float permitted).
- `user_active`: boolean.
- `source`: optional string (recommended: stable identifier like `"windows-sidecar"`).
- `seq`: optional monotonically increasing integer (recommended).

Write cadence:
- Update at 4-20 Hz (250ms to 50ms). Faster is fine; avoid >60 Hz unless needed.

Atomicity:
- Write to a temp file in the same directory, then `os.replace()` to the final path.

## Canonical Stores And Required Artifacts

## Canonical JSON And Hashing (Exact Rules)

This repo uses "canonical JSON" for stable hashing and append-only logs. If the sidecar computes `payload_hash` or implements ledger chaining, it MUST follow these rules:

### Canonical JSON Serialization

Canonical JSON serialization is:

- Recursively normalize objects:
  - dict keys are converted to strings
  - lists preserved in order
  - strings normalized to Unicode NFC
- Floats are not permitted (NaN/Inf are forbidden; floats raise an error)
- Encode as JSON with:
  - `sort_keys=True`
  - `ensure_ascii=False`
  - `separators=(",", ":")` (no whitespace)

### `payload_hash` For Evidence Records

If an evidence record includes `payload_hash`, it MUST be:

- `payload_hash = sha256( canonical_json(record_without_payload_hash) ).hexdigest()`

### Ledger Hash Chaining (`entry_hash`)

Ledger entries are hash chained. If the sidecar is not using this repo's ledger writer, it MUST replicate:

1. Let `prev_hash = previous_entry.entry_hash` (or `null` for the first entry).
2. Create a payload object equal to the ledger entry, but:
   - set `prev_hash` to `prev_hash` (or `null`)
   - remove `entry_hash` if present
3. Serialize that payload object via canonical JSON.
4. Compute:
   - `entry_hash = sha256( canonical_json_payload + (prev_hash or "") ).hexdigest()`

### DataRoot Layout (Defaults)

Default paths from `config/default.json`:

- `storage.data_dir`: `data`
- `storage.metadata_path`: `data/metadata.db`
- `storage.media_dir`: `data/media`
- `storage.blob_dir`: `data/blobs`
- `storage.spool_dir`: `data/spool`
- `journal`: `data/journal.ndjson`
- `ledger`: `data/ledger.ndjson`

## Canonical Media Store (Mode B)

For Mode B to work, screenshots MUST be stored in the processor’s canonical media store keyed by `record_id`.

This repo’s default media store implementation uses:

- Record-id-safe filenames via `rid_<urlsafe_base64(record_id)>` (padding stripped).
  - Reference: `_encode_record_id()` in `plugins/builtin/storage_encrypted/plugin.py`
- Sharding by `run_id`, record kind (`evidence` vs `derived`), and date (from `ts_utc`).
  - Reference: `_shard_dir()` in `plugins/builtin/storage_encrypted/plugin.py`
- File extensions:
  - `.blob` for byte blobs
  - `.stream` for streams

### Required Media Layout For Frames

For a frame evidence record:

- `record_type = "evidence.capture.frame"`
- `run_id = "<run_id>"`
- `ts_utc = "<ISO-8601 timestamp>"`

The sidecar MUST write the PNG bytes to:

`<DataRoot>/media/<rid(run_id)>/evidence/YYYY/MM/DD/<rid(record_id)>.blob`

Where:
- `rid(x) = "rid_" + base64url(utf8(x)) with trailing '=' padding removed`
- `YYYY/MM/DD` come from parsing `ts_utc`

Notes:
- The bytes stored in the `.blob` are the *canonical* stored representation. For `evidence.capture.frame` this should be the PNG file bytes.
- Writing `.png` files to arbitrary folders (for example `media/screenshots/YYYYMMDD/*.png`) is not sufficient; the processor will not discover them without the canonical `.blob` layout above.

### Encryption Requirement (Mode B)

To avoid cross-platform key transport between Windows and WSL, Mode B SHOULD run with encryption disabled:

- `storage.encryption_enabled = false`
- `storage.encryption_required = false`

If you enable encryption, the sidecar MUST implement the same blob packing and keyring semantics as the in-repo stores (see `plugins/builtin/storage_encrypted/plugin.py` and `plugins/builtin/storage_sqlcipher/plugin.py`). This is intentionally out of scope for the “minimum viable sidecar” contract.

## Canonical Metadata Store (Mode B)

The sidecar MUST persist evidence/derived records into SQLite `metadata.db` under the `metadata` table.

Reference schema (matches the in-repo SQLCipher/plain SQLite store):
- Reference: `plugins/builtin/storage_sqlcipher/plugin.py`

```sql
CREATE TABLE IF NOT EXISTS metadata (
  id TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  record_type TEXT,
  ts_utc TEXT,
  run_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_metadata_record_type ON metadata(record_type);
CREATE INDEX IF NOT EXISTS idx_metadata_ts_utc ON metadata(ts_utc);
CREATE INDEX IF NOT EXISTS idx_metadata_run_id ON metadata(run_id);
```

Rules:
- `id` MUST equal the `record_id` used for the corresponding media blob key.
- `payload` MUST be the JSON string of the record (the evidence/derived object).
- `record_type`, `ts_utc`, `run_id` SHOULD be copied out of the payload for indexing.

### Evidence: Frames + Window + Input (Minimum Required For Full Workflow)

To enable the full workflow in this repo (processing + retrieval context), the sidecar MUST write:

- **Frame evidence** (`evidence.capture.frame`) for screenshots.
- **Window metadata evidence** (`evidence.window.meta`) on active-window changes.
- **Input summaries** (`derived.input.summary`) on a fixed flush cadence (for example every 250ms to 2s).

Additionally, each frame record SHOULD embed lightweight references:

- `window_ref`: the latest window snapshot (including its `record_id` when available)
- `input_ref`: the latest input snapshot/summary (including its `record_id` when available)

#### Recommended `window_ref` Shape

Match the window plugin’s `last_record()` shape:

```json
{
  "record_id": "run1/window/0",
  "ts_utc": "2026-02-10T12:34:50.000+00:00",
  "window": {
    "title": "Example - Notepad",
    "process_path": "C:\\\\Windows\\\\System32\\\\notepad.exe",
    "hwnd": 123456,
    "rect": [0, 0, 1920, 1080]
  }
}
```

#### Recommended `input_ref` Shape

`input_ref` is intentionally flexible. If you have a stable derived input summary record id, include it:

```json
{
  "record_id": "run1/derived.input.summary/42",
  "ts_utc": "2026-02-10T12:34:56.700+00:00",
  "kind": "input.summary",
  "idle_seconds": 3,
  "event_count": 12
}
```

1. **Media bytes**:
   - Store the canonical image bytes (PNG recommended) under the same `record_id` used for metadata.
2. **Metadata evidence record**:
   - A JSON object keyed by the same `record_id`, with `record_type = "evidence.capture.frame"`.
3. **Journal + Ledger provenance**:
   - Append `capture.frame` events to the journal and corresponding ledger entries.

#### Required Fields (Frame Record)

The evidence record MUST satisfy `contracts/evidence.schema.json`. For `evidence.capture.frame`, the schema requires:

- `schema_version` (integer, currently `1`)
- `record_type` (string, must be `evidence.capture.frame`)
- `run_id` (string)
- `ts_utc` (string, ISO-8601)
- At least one of: `content_hash` or `payload_hash`

For end-to-end processing quality, the sidecar SHOULD also include:

- `width` (int), `height` (int), `resolution` (e.g. `"1920x1080"`)
- `encoding` (e.g. `"png"`), `content_type` (e.g. `"image/png"`), `content_size` (bytes)
- `content_hash` as `sha256(png_bytes).hexdigest()`
- `payload_hash` as `sha256_canonical(record_without_payload_hash)`
- `policy_snapshot_hash` (from the active config policy snapshot)
- Optional UX context:
  - `window_ref` (active window snapshot)
  - `input_ref` (recent input snapshot)
  - `cursor` (cursor x/y/visible)

#### Minimal Example (Frame Record)

```json
{
  "schema_version": 1,
  "record_type": "evidence.capture.frame",
  "run_id": "run1",
  "ts_utc": "2026-02-10T12:34:56.789+00:00",
  "width": 1920,
  "height": 1080,
  "encoding": "png",
  "content_type": "image/png",
  "content_size": 123456,
  "content_hash": "SHA256_HEX_OF_PNG_BYTES",
  "policy_snapshot_hash": "OPTIONAL_BUT_RECOMMENDED",
  "payload_hash": "SHA256_HEX_OF_CANONICAL_JSON_OF_THIS_OBJECT_WITHOUT_payload_hash"
}
```

#### Required Fields (Journal Entry)

Journal lines are canonical JSON objects appended to `data/journal.ndjson` with fields:

- `schema_version` (int, `1`)
- `event_id` (string, stable per event; MUST be prefixed with `run_id`)
- `sequence` (int, monotonically increasing within the writer)
- `ts_utc` (string)
- `tzid` (string)
- `offset_minutes` (int)
- `event_type` (string, e.g. `"capture.frame"`)
- `payload` (object; the evidence record payload)
- `run_id` (string)

#### Required Fields (Ledger Entry)

Ledger lines are canonical JSON objects appended to `data/ledger.ndjson` with fields:

- `record_type`: `"ledger.entry"`
- `schema_version`: `1`
- `entry_id`: stable identifier (SHOULD match the capture record id for capture commits)
- `ts_utc`: ISO-8601 UTC with `Z` suffix preferred
- `stage`: stage name (e.g. `"capture.frame"`)
- `inputs`: list of strings
- `outputs`: list of strings (SHOULD include the evidence `record_id`)
- `policy_snapshot_hash`: string
- `payload`: optional object
- `prev_hash`: string or null
- `entry_hash`: sha256 hash chain value

Important:
- The ledger is **hash chained**: each entry's `entry_hash` depends on the canonical JSON of the entry plus the previous entry hash.
- If the sidecar does not use this repo's ledger writer, it must replicate the chaining algorithm exactly.

### Evidence: Window Metadata (`evidence.window.meta`)

The sidecar MUST write window metadata records when the active window changes.

Minimum required fields (per `contracts/evidence.schema.json`):

- `schema_version` (int, `1`)
- `record_type` (string, `evidence.window.meta`)
- `run_id` (string)
- `ts_utc` (string)
- `window` (object)
- At least one of: `content_hash` or `payload_hash`

Recommended additional fields:

- `text`: a searchable string (for example `"<window title> <process path>"`)
- `content_hash`: sha256 of canonical JSON payload for stable dedupe

### Derived: Input Summary (`derived.input.summary`)

The sidecar MUST write input summary records on a regular cadence (flush interval).

Minimum required fields (per `contracts/evidence.schema.json`):

- `schema_version` (int, `1`)
- `record_type` (string, `derived.input.summary`)
- `run_id` (string)
- `start_ts_utc` (string)
- `end_ts_utc` (string)
- `event_id` (string)
- `event_count` (int)
- At least one of: `content_hash` or `payload_hash`

Notes:

- These summaries are used by retrieval and timeline context. The exact summary schema can evolve; keep it forwards-compatible by allowing extra fields.

## Record ID Requirements

This repo assumes `record_id` and `event_id` are stable identifiers used across:

- media store key
- metadata store key
- journal `event_id`
- ledger `entry_id`

Requirements:

- `record_id` MUST be unique within the DataRoot.
- `record_id` SHOULD be prefixed with `run_id` (format: `{run_id}/...`).
- When writing journal events, `event_id` MUST be prefixed with `run_id` (the journal writer enforces this).

## Cross-Platform Crypto And Key Handling (Important)

Most production configurations enable encryption (`storage.encryption_enabled = true`).

To keep the processor able to decrypt sidecar-written media/metadata:

- Prefer Mode A and include a portable keyring bundle in the backup zip.
- Avoid Windows-only key protection mechanisms (for example DPAPI-only keys) without exporting a portable key bundle.

If you must share a live DataRoot (Mode B), you must ensure the processor has access to compatible key material for the storage backend in use.

## Validation Checklist (Processor-Side)

Before blaming processing, verify the handoff data is consistent:

- `data/journal.ndjson` exists and is parseable JSONL
- `data/ledger.ndjson` exists and is hash-chain valid
- For a sample `record_id`:
  - metadata record exists and validates against `contracts/evidence.schema.json`
  - corresponding media bytes exist and can be read/decrypted
- Run self-test:
  - `./.venv/bin/autocapture doctor --self-test`
