# Autocapture Prime repo work order: merge duplicate paths, implement Stage 1 handoff ingest, and harden Stage 2+ offline processing + instant query

This document is meant to be executed in the **autocapture_prime** repo (this repo) by your codex CLI / automation tooling.

It does **not** assume changes have already been made elsewhere. It is written to be **safe, incremental, and backwards-compatible** where possible.

---

## 0) The target end-state (what “done” looks like)

### A. One canonical pipeline in this repo
- **Canonical runtime/CLI**: `autocapture` (NX) is the single source of truth.
- **Legacy compatibility**: `autocapture-prime` still exists but becomes a thin wrapper over `autocapture` (or is explicitly deprecated with clear messaging).
- “Prime vs NX/MX” codepaths are merged so there is **one ingestion path**, **one processing path**, and **one query path**.

### B. Two-phase pipeline aligned to your requirements
**Stage 1 (ultralight + stable + accurate):**
- Inputs: hypervisor output **screenshots + metadata.db** (and raw HID/input logs if present).
- Output: “normalized layer” stored in this repo’s data dir (DataRoot / metadata.db + media blobs).
- Guarantees:
  - Fully deterministic, idempotent, restartable.
  - Does **no heavy OCR/VLM**.
  - Ends by writing an **ack/marker** in the hypervisor handoff directory so the hypervisor reaper can delete the raw handoff artifacts.

**Stage 2+ (offline + thorough + citeable):**
- Runs only when user is idle / not active.
- Performs all expensive analysis: OCR, VLM UI extraction, state machines, indexing, summaries, aggregations.
- Writes derived artifacts and indexes so queries are instant.

**Query time (user active):**
- **No on-demand processing, no decoding/extract scheduling, no VLM calls.**
- Returns answers from precomputed artifacts only, with citations.

---

## 1) Non‑negotiables (system constraints)

1) **Stage 1 must never do expensive work.**
   - No OCR, no VLM, no embeddings.
   - Only validation, copying/hardlinking, record normalization, integrity checks, and marking for reaping.

2) **Stage 2+ can be slow, but must be:**
   - Ultra thorough
   - Ultra accurate
   - Ultra citeable (every claim traceable to evidence frames + bounding boxes / record IDs)

3) **Interactive query must be instant and “read-only”:**
   - Never schedules background jobs.
   - Never runs extraction or VLM.
   - If data is not processed, return a “not available yet / not indexed yet” style response.

4) **This repo must not delete its own retained evidence store.**
   - Retention cleanup happens in hypervisor handoff spool via explicit marker/ack.

---

## 2) Current issues to fix (what’s wrong today)

### A) Duplicate product surfaces
- There are multiple CLIs (`autocapture` and `autocapture-prime`) and multiple ingestion/processing pathways.
- Chronicle spool ingestion utilities live under `autocapture_prime/ingest/*` even though the NX path is the canonical runtime.

### B) “Ingest” in autocapture_prime is too heavy
- The current prime pipeline `ingest_one_session()` instantiates OCR/layout engines during ingestion.
- This violates the Stage 1 requirement (ultralight).

### C) Handoff-to-reap is not standardized as an explicit contract
- You have a hypervisor “reap watcher” and need this repo to mark handoff directories as safe to delete.
- Today there is no single, enforced marker file schema.

---

## 3) Proposed architecture: a single pipeline with a Stage 1 “handoff ingest” front-door

### A) Normalize on one storage shape: DataRoot
Use a **DataRoot** directory structure in this repo for retained data:

- `DATA_ROOT/metadata.db` (SQLite, plaintext recommended for processing-only mode)
- `DATA_ROOT/media/…` (blob files keyed by record id / rid encoding)
- `DATA_ROOT/journal.ndjson` and `DATA_ROOT/ledger.ndjson` (append-only provenance)
- `DATA_ROOT/derived/...` (stage 2+ outputs)
- `DATA_ROOT/index/...` (stage 2+ indexes)
- `DATA_ROOT/activity/activity_signal.json` (from hypervisor, or imported)

This matches what your offline processing + query stack already expects.

### B) Define an explicit Stage 1 input: “handoff dir”
Hypervisor will write *one or more* handoff directories:
- Each handoff directory is a **mini DataRoot** (same shape as above), but typically only contains:
  - `metadata.db`
  - `media/…`
  - optional `activity/activity_signal.json`
  - optional raw HID logs (either in metadata payloads via blob refs or as blobs)

Stage 1 ingests each handoff dir into the main `DATA_ROOT`, then writes `reap_eligible.json` (or similar) back into the handoff dir.

---

## 4) Implementation plan (do in this order)

### Step 1 — Make NX the one true CLI surface (keep prime as wrapper)

1. Keep `autocapture` entrypoint as-is (NX).
2. Convert `autocapture-prime` to a thin shim that:
   - prints a short deprecation note (once), and
   - forwards to NX CLI subcommands.
3. Update docs to refer to NX as canonical and describe prime as legacy/compat.

**Concrete changes**
- `autocapture_prime/cli.py`
  - Replace command implementation with argument passthrough to `autocapture_nx.cli:main`.
  - Keep `autocapture-prime` script in `pyproject.toml` for now.
- `README.md`
  - Add a “Canonical CLI” note and update examples to use `autocapture`.

**Acceptance**
- Running `autocapture-prime …` behaves the same as `autocapture …` for supported commands.
- No code duplication for core pipeline behavior.

---

### Step 2 — Implement Stage 1: handoff ingestion (ultralight)

Add a new NX command group:
- `autocapture handoff ingest` (ingest one handoff dir)
- `autocapture handoff drain` (scan a spool root, ingest all, and mark each)

#### 2.1 New module: `autocapture_nx/ingest/handoff_ingest.py`
Provide a small, dependency-minimal implementation with:
- `HandoffIngestor(dest_data_root: Path, *, mode: Literal["copy","hardlink"], strict: bool)`
- `ingest_handoff_dir(handoff_root: Path) -> IngestResult`

**Algorithm**
1. Acquire a **single-instance lock** for the destination DataRoot (file lock).
2. Validate handoff root minimally:
   - must contain `metadata.db`
   - must contain `media/` (or if missing, allow if metadata has no blob records)
3. Open handoff `metadata.db` read-only.
4. Open destination `metadata.db` (create if missing) and ensure schema exists.
5. In a single transaction, copy rows:
   - Use `ATTACH DATABASE` and `INSERT OR IGNORE` into destination `metadata` table.
   - If destination has a different schema (legacy `records`), auto-migrate or write into both (temporary).
6. Copy blobs (raw media + any other referenced files):
   - **Fast path (canonical layout present):**
     - If the handoff dir already uses the canonical blob layout under `media/` (rid_… and `.blob` files), copy/link the entire `handoff_root/media/**` tree into `dest/media/**` using “skip if exists”.
   - **Fallback path (payload references):**
     - If records reference blobs via `payload.blob_path` (or similar), enumerate only those referenced files and copy/link them into the destination media store, preserving relative paths.
   - If `mode=hardlink`, attempt `os.link(src, dst)` first and fallback to a streamed copy.
   - Verify integrity after each blob import:
     - at minimum: size match
     - optionally (recommended when copying): compute SHA-256 while streaming and record it in an ingest log record (do not block Stage 1 on hash if hardlinking).
7. Write ingest journal entry in destination:
   - record type: `system.ingest.handoff.completed`
   - payload includes: handoff_id, counts, bytes, started_utc/ended_utc, errors=[]
8. Write **ack marker** into handoff dir:
   - `reap_eligible.json` (schema defined below)
   - Write atomically (tmp + rename).
9. Return result.

**Important implementation rules**
- **No OCR/VLM/embedding imports** in this module.
- No plugin/kernel boot is required unless you decide it’s safer to reuse existing store abstractions.
- Must be restartable: partial file copies should use temp filenames and atomic renames.

#### 2.2 Marker contract: `reap_eligible.json` (v1)
Write this file into handoff dir when (and only when) safe to delete:

```json
{
  "schema": "autocapture.handoff.reap_eligible.v1",
  "handoff_root": "C:/.../handoff/2026-02-20T19-33-12Z_run_abc",
  "dest_data_root": "/mnt/data/autocapture_dataroot",
  "ingested_at_utc": "2026-02-20T19:40:01Z",
  "ingest_run_id": "ingest_01J...ULID",
  "counts": {
    "metadata_rows_copied": 1234,
    "media_files_linked": 980,
    "media_files_copied": 12,
    "bytes_ingested": 987654321
  },
  "integrity": {
    "dest_metadata_db_sha256": "optional",
    "notes": "optional"
  }
}
```

- Hypervisor reap watcher deletes handoff directories **only** when this file exists and parses as valid v1.

#### 2.3 NX CLI wiring
- Add to `autocapture_nx/cli.py` a `handoff` command group:
  - `handoff ingest --handoff-root PATH --data-dir PATH [--mode copy|hardlink] [--strict]`
  - `handoff drain --spool-root PATH --data-dir PATH ...`
- Add help text making it explicit that Stage 1 is ultralight and is safe to run frequently.

**Acceptance**
- Given a handoff dir with metadata.db + media, Stage 1 ingests it and writes `reap_eligible.json`.
- Re-running Stage 1 is idempotent (no duplicates, no corruption, marker re-written consistently).
- Stage 1 runtime scales roughly with bytes copied/linked (no heavy compute).

---

### Step 3 — Move “Chronicle spool ingestion” behind the same Stage 1 interface (optional but recommended)

If chronicle spool is still relevant, do not keep it as a separate “prime-only” pipeline.

1. Move/copy `autocapture_prime/ingest/*` into `autocapture_nx/ingest/chronicle/*`.
2. Ensure chronicle ingestion **only produces evidence records + media blobs** and then marks the spool session as safe to delete.
3. Remove OCR/layout from ingestion (those belong in Stage 2 plugins).

**Acceptance**
- One ingestion front-door:
  - `handoff ingest` for hypervisor handoff dirs
  - `chronicle ingest` (or another subcommand) for chronicle sessions
- Both end by writing the same `reap_eligible.json` marker format.

---

### Step 4 — Harden Stage 2+ offline processing to be “hypervisor-friendly”

Stage 2+ already exists as batch processing / plugin pipelines. Make sure it is safe to run under hypervisor control:

1. Ensure Stage 2 checks “user activity / foreground” and fails closed.
   - Prefer reading `activity/activity_signal.json` (or equivalent) and default to “active” if missing.
2. Ensure VLM calls go through hypervisor-managed endpoints:
   - If you already support `EXTERNAL_VLLM_BASE_URL` / gateway, document and default it in the “under hypervisor” docs.
3. Make Stage 2 fully incremental:
   - Never reprocess frames whose derived outputs already exist unless explicitly forced.
4. Emit auditability:
   - Each derived record must cite:
     - source `evidence.capture.frame` record id(s)
     - bounding boxes (if applicable)
     - model name + prompt hash (for VLM outputs)

**Concrete changes**
- Add/strengthen gating in the batch runner / idle processor.
- Add “no VLM in foreground” unit tests:
  - Simulate activity signal “active” and verify batch runner does not call VLM endpoints.

**Acceptance**
- Stage 2 can be started anytime; it will self-throttle / pause when the user is active.
- When the user is idle, Stage 2 runs to completion and produces all needed indexes.

---

### Step 5 — Enforce “no on-demand processing” in query path

1. In query server and CLI:
   - hard-disable decode/extract and schedule modes.
   - always run in metadata-only retrieval mode.

2. If a query requests something that is not available because Stage 2 hasn’t computed it:
   - respond with a structured “not available” answer including:
     - what artifact/index is missing
     - last processed timestamp
     - how to run stage2 (or “wait until idle run completes”)

**Concrete changes**
- In query handler (HTTP + CLI), reject or ignore:
  - `schedule_extract=true`
  - any config that enables `allow_decode_extract`
- Add regression tests asserting:
  - no VLM calls happen during query
  - no new derived records are written during query

**Acceptance**
- Query is pure read-only over precomputed artifacts.
- Any attempt to enable scheduling/extraction during query is blocked.

---



## 4.5) Stage 2+ artifact roadmap (so you can answer “any NL question” instantly)

Stage 2+ should precompute *explicit, queryable artifacts* that cover the kinds of questions you described. The guiding principle:

- **Compute once while idle**
- **Index aggressively**
- **Query reads only**

### A) Minimum derived artifacts to support your example questions

1) **UI text + structure (high recall)**
   - OCR text lines + blocks for every frame (or keyframes)
   - VLM UI element extraction (buttons, inputs, labels, icons) for keyframes
   - Must include citations: `{frame_record_id, bbox, ts_utc, model}`

2) **Window/app semantics**
   - Active window title/process/app
   - URL/domain extraction for browser windows (from window title and/or address bar OCR/VLM)
   - Per-frame “what app is this?” classification when needed

3) **Code + console understanding**
   - Detect code blocks in terminals/editors
   - Extract snippets and classify language (SQL/bash/python/etc)
   - Store “final version” candidates (last edit in a time window) + provenance

4) **Color + visual features (for questions like “ANSI color code of Gmail background”)**
   - For each frame (or each active window region), compute:
     - dominant background color (RGB)
     - nearest ANSI 16 / ANSI 256 mapping (store both)
     - optional palette histogram
   - This is cheap enough to do offline at scale and makes those “visual detail” queries instant.

5) **Behavior/time rollups**
   - Daily + weekly rollups for:
     - top domains visited
     - top apps
     - most common documents/projects
   - Build these from the per-frame window/url records and store as small summary tables.

### B) Indexes to build offline (so query is instant)
- Text inverted index (BM25) over:
  - OCR text
  - UI element labels
  - window titles
  - extracted code snippets
- Vector index (optional) over:
  - frame summaries
  - UI element descriptions
  - code snippets
- Time-series lookup tables:
  - domain → {count, last_seen, first_seen, peak_day}
  - app → same
- “Evidence locator” index:
  - any derived record → its exact evidence frames (record ids + bboxes)

### C) Enforce “no on-demand”
- Query server must only read from:
  - metadata.db (records)
  - derived artifacts
  - indexes
- If an index is missing/stale:
  - respond “not available yet” and point to Stage 2 run logs/timestamps

**Acceptance**
- You can ask:
  - “What website did we visit a ton about 2 weeks ago?”
  - “What final SQL did we land on yesterday?”
  - “What ANSI color code is the Gmail background?”
  and the answer comes from precomputed artifacts with citations and no processing during query.

## 5) File-by-file change list (actionable)

### New files to add
- `autocapture_nx/ingest/handoff_ingest.py`
- `autocapture_nx/ingest/__init__.py` (if missing; export HandoffIngestor)
- `autocapture_nx/cli_handoff.py` (optional; keep cli.py from bloating)
- `docs/handoff-stage1-contract.md` (define handoff dir + marker schema)
- `tests/test_handoff_ingest.py` (unit tests)
- `tools/handoff_ingest_smoke.py` (optional small local smoke script)

### Files to modify
- `autocapture_nx/cli.py`
  - add `handoff` subcommands
  - enforce query no-on-demand flags consistently
- `autocapture_prime/cli.py`
  - thin wrapper over NX
- `docs/autocapture_prime_UNDER_HYPERVISOR.md`
  - update to describe Stage 1/Stage 2 responsibilities and the marker contract
- `docs/windows-hypervisor-popup-query-contract.md`
  - explicitly state schedule/extract is disabled for interactive queries

### Optional refactor
- Move chronicle ingestion modules:
  - `autocapture_prime/ingest/*` → `autocapture_nx/ingest/chronicle/*`
  - leave `autocapture_prime/…` as compatibility shims

---

## 6) Test plan (must add)

### Stage 1 ingest tests
- `test_handoff_ingest_idempotent`
  - ingest the same handoff dir twice; ensure dest metadata count stable and marker exists.
- `test_handoff_ingest_missing_media_fails_no_marker`
  - delete one blob; ingest should fail and must NOT write `reap_eligible.json`.
- `test_handoff_ingest_hardlink_mode_fallbacks_to_copy`
  - simulate cross-device link failure; ensure it copies and still succeeds.

### Query invariants
- `test_query_does_not_write_records`
  - run a query; assert metadata.db unchanged (or only read-only).
- `test_query_never_calls_vlm`
  - patch VLM client; assert not invoked.

### Stage 2 gating (offline)
- `test_batch_pauses_when_user_active`
  - provide activity signal “active”; ensure batch exits quickly without VLM.

---

## 7) Rollout plan (safe and incremental)

1. Land Stage 1 ingest + marker contract (no behavioral changes elsewhere).
2. Update hypervisor to write handoff dirs + respect `reap_eligible.json`.
3. Switch hypervisor to run:
   - `autocapture handoff drain ...` frequently
   - `autocapture batch run ...` only when idle
4. Only after stable:
   - convert `autocapture-prime` into wrapper
   - migrate chronicle ingestion if needed
5. After 1–2 weeks stable, delete or quarantine unused legacy modules.

---

## 8) Assumptions (explicit)

- Hypervisor can emit handoff dirs that include:
  - `metadata.db`
  - `media/` directory containing blob files referenced by metadata (directly or indirectly)
- Hypervisor reaper can delete handoff dirs based on a marker file.
- This repo’s retained DataRoot is on a storage volume that is not subject to the hypervisor’s tight space constraint.

If any of these are false, keep this plan but adjust the handoff dir contract (see `HYPERVISOR_LOCKSTEP_UPDATES.md`).

---
