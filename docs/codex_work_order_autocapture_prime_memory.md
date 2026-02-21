# Codex Work Order — Autocapture Prime
## Project: Export ChatGPT (Edge) transcripts into a local append-only NDJSON for Hypervisor ingest

**Target repo:** `ninjra/autocapture_prime`  
**Goal:** produce `chatgpt_transcripts.ndjson` (append-only, hash-chained) from
captured segments, local-only, fail-soft, no new mandatory services.  
**Primary consumer:** Hypervisor sidecar transcript ingestor (see sibling work order).  
**Existing relevant components:**
- Capture segments written to storage + journal:  
  https://github.com/ninjra/autocapture_prime/blob/abff23401f84e4ff71b5c417317a2d5eb2b24559/plugins/builtin/capture_windows/plugin.py
- Journal format:  
  https://github.com/ninjra/autocapture_prime/blob/abff23401f84e4ff71b5c417317a2d5eb2b24559/plugins/builtin/journal_basic/plugin.py
- Encrypted media store has `keys()` + `get()` APIs:  
  https://github.com/ninjra/autocapture_prime/blob/abff23401f84e4ff71b5c417317a2d5eb2b24559/plugins/builtin/storage_encrypted/plugin.py
- Egress sanitizer can sanitize local text (PII/tokenization):  
  https://github.com/ninjra/autocapture_prime/blob/abff23401f84e4ff71b5c417317a2d5eb2b24559/plugins/builtin/egress_sanitizer/plugin.py
- Ledger hash-chaining helper pattern:  
  https://github.com/ninjra/autocapture_prime/blob/abff23401f84e4ff71b5c417317a2d5eb2b24559/plugins/builtin/ledger_basic/plugin.py
- Plugin allowlist and defaults:  
  https://github.com/ninjra/autocapture_prime/blob/abff23401f84e4ff71b5c417317a2d5eb2b24559/config/default.json

---

## 0) Goals and non-goals

### Goals
1) Create a local exporter that reads existing captured segments and emits a
   **sanitized** chat transcript NDJSON stream for Hypervisor ingestion.
2) Keep exporter fail-soft and non-blocking for capture:
   - capture continues even if export fails
3) No new mandatory external services:
   - exporter uses only local file IO + existing stores
   - optional OCR dependency (if present) can be used; otherwise exporter
     continues but may emit fewer/empty transcripts

### Non-goals
- Perfect DOM-level chat extraction in Phase 1.
- Network submission to remote endpoints.
- Any dependency on Chrome (user uses Edge).

---

## 1) Output contract (must match Hypervisor ingest)

### 1.1 Export root (directory)
Resolve a single export directory.

Resolution order:
1) Env var `KERNEL_AUTOCAPTURE_EXPORT_ROOT`
2) If Windows and `KERNEL_AUTOCAPTURE_DATA_ROOT` exists, sibling `exports`
3) Default: `data/exports` under repo working directory

Ensure the directory exists.

### 1.2 Export file
- `${export_root}/chatgpt_transcripts.ndjson`
- Append-only. Each line is canonical JSON, hash-chained.

### 1.3 Line schema (minimum required fields)
```json
{
  "schema_version": 1,
  "entry_id": "chatgpt:edge:session:<opaque>",
  "ts_utc": "2026-02-17T20:59:12.123456+00:00",
  "source": {
    "browser": "msedge",
    "app": "chatgpt",
    "window_title": "...",
    "process_path": "C:\\Program Files\\...\\msedge.exe"
  },
  "segment_id": "segment_123",
  "frame_name": "frame_0.jpg",
  "text": "sanitized transcript text ...",
  "glossary": [],
  "prev_hash": null,
  "entry_hash": "<sha256 hex>"
}
```

Notes:
- `text` should be sanitized via `privacy.egress_sanitizer` (scope `"chatgpt"`).
- `glossary` is the sanitizer glossary list (may be empty).
- Hash chain:
  - `entry_hash = sha256(canonical_json_without_entry_hash + (prev_hash or ""))`

---

## 2) Exporter approach (Phase 1)

### 2.1 Inputs
- `data/journal.ndjson` contains `event_type="capture.segment"` entries and
  segment metadata (segment_id, frame_count, ts_utc).
- `storage.media` contains encrypted zip blobs for each segment id.
- `storage.metadata` contains window change records:
  - `record_type="window.meta"`
  - includes `process_path` and `title`

### 2.2 Segment selection heuristic (deterministic)
For each segment `capture.segment` event:
1) Find the nearest `window.meta` record whose `ts_utc <= segment_ts_utc` and
   within a maximum lookback window (config: 10 seconds).
2) If `process_path` contains `msedge` (case-insensitive), keep candidate.
3) If `window_title` contains `chatgpt` or `openai` (case-insensitive), mark as
   high confidence.
4) Otherwise still allow if `msedge` and OCR output contains `ChatGPT`
   (post-OCR filter).

### 2.3 Frame selection heuristic (deterministic, cheap)
Within a segment zip, select frames:
- `frame_0.jpg`
- `frame_{mid}.jpg`
- `frame_{last}.jpg`
where `mid = frame_count // 2`, `last = frame_count - 1`.

### 2.4 Text extraction (fail-soft)
Try these in order for each frame:
1) If `ocr.engine` capability is available and returns text, use it.
   - `builtin.ocr.stub` uses `pytesseract` if installed; it may raise.
2) If OCR fails/unavailable, skip frame.

Post-process:
- collapse whitespace
- drop very short strings (< 40 chars) unless they contain `chatgpt` or `openai`

### 2.5 Sanitization
Use `privacy.egress_sanitizer.sanitize_text(text, scope="chatgpt")`
and include:
- `text` sanitized
- `glossary` list
Do a leak check:
- `privacy.egress_sanitizer.leak_check(...)`
If leak check fails, write `text=""` and record `glossary`, and include an
additional field `export_notice="leak_check_failed"`.

---

## 3) Code changes

### Task 3.1 — Add exporter module
**New file:**
- `autocapture_nx/kernel/export_chatgpt.py` (new)

Functions:
- `resolve_export_root(config) -> str`
- `iter_capture_segments(journal_path) -> iterator[dict]`
- `load_window_index(metadata_store) -> list[dict]`
- `match_window_for_segment(window_index, segment_ts_utc) -> dict|None`
- `iter_selected_frames(zip_bytes, frame_count) -> iterator[(frame_name, jpg_bytes)]`
- `extract_text(system, jpg_bytes) -> str` (uses `ocr.engine` if present)
- `sanitize(system, text) -> (text, glossary, leak_ok)`
- `append_export_line(path, obj, prev_hash) -> new_hash`

Store the export file state:
- Read last line to recover `prev_hash` (fast tail read).
- No separate cursor needed for exporter (Hypervisor ingests incrementally).

### Task 3.2 — Add CLI command
**Edit file:**
- `autocapture_nx/cli.py`

Add a new top-level command:
- `autocapture export chatgpt [--max-segments N] [--since-ts ISO] [--follow]`

Behavior:
- Boot kernel once (`Kernel.boot()`) to get:
  - `storage.media`, `storage.metadata`, `privacy.egress_sanitizer`,
    `ocr.engine` (if available)
- Run export pass:
  - Read journal
  - For each segment id:
    - skip if already exported (persist this in metadata store):
      - metadata key: `export.chatgpt.<segment_id>`
      - value includes `exported_at`, `entry_hashes` list
  - Append one NDJSON line per extracted frame that produces acceptable text
- `--follow`:
  - sleep (2s) and continue; always fail-soft.

### Task 3.3 — Add unit tests
**New file:**
- `tests/test_export_chatgpt.py`

Tests (pure python, no Windows required):
1) Build a fake zip with 3 jpeg files (can be tiny fixtures in repo) OR stub
   `iter_selected_frames` to return bytes.
2) Stub `ocr.engine.extract` to return deterministic text.
3) Stub sanitizer to return deterministic output.
4) Run export into a temp dir and assert:
   - file exists
   - lines are valid JSON
   - `prev_hash` / `entry_hash` chain holds for all lines
   - `schema_version` and required fields exist

### Task 3.4 — Documentation
Add a short doc:
- `docs/chatgpt_export.md` (new)
Include:
- how to run exporter
- where export file is written
- how Hypervisor ingests it (link to Hypervisor work order)

---

## 4) No new external requirements
- Do not add network calls.
- Do not require any new system installs.
- OCR remains optional; exporter must continue without it.

---

## 5) Run instructions

### Export once
```bash
python -m autocapture_nx.cli export chatgpt --max-segments 50
```

### Export continuously (tailing new segments)
```bash
python -m autocapture_nx.cli export chatgpt --follow
```

### Tests
If this repo uses Poetry for tests in your setup, follow this convention:
- Run `poetry install --with dev` (or the repo’s declared test group) before
  running `pytest`.
If installs are unavailable in your environment, skip execution and rely on CI.

Then:
```bash
pytest -q
```

---

## 6) Deliverables checklist
- [x] `autocapture export chatgpt` command present and documented.
- [x] Export file is append-only NDJSON with hash chaining.
- [x] Text is sanitized with glossary included.
- [x] Export does not interrupt capture loops (fail-soft).
- [x] Unit tests cover hash chain + schema correctness.
