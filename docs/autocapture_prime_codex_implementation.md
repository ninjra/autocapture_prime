# autocapture_prime — Codex implementation spec (ingest + OCR/layout + linking + indexing + vLLM + chronicle_api)

This document converts the attached architecture report into a concrete,
repo-local implementation plan for **autocapture_prime** (WSL2/Linux). It is
written to be consumable by **Codex CLI**: it specifies *what files to create*,
*pipelines to implement*, the *API contract*, and *acceptance tests*.

> Scope: ingest spool sessions written by `hypervisor`, extract structured UI
> state with OCR/layout parsing, index the results, and expose a **talking
> layer** API that performs retrieval + VLM QA via vLLM.

---

## Safety boundary (explicit)

This spec supports analyzing **captured screens** and **pointer interaction**
(mouse position/clicks). It **does not** include instructions to collect
system-wide keyboard telemetry (keylogging).

---

## 0) Design decision: where the “talking layer” lives

You do not have a third repo like the report’s `chronicle_api`.

**Recommendation: implement the talk layer inside autocapture_prime** at:

- `services/chronicle_api/` (FastAPI or repo-standard HTTP framework)

Rationale:
- The talk layer needs access to OCR/layout outputs, indexes, and vLLM.
- These dependencies are already Linux/WSL-friendly (Python-first).
- Hypervisor remains lean and real-time.

Hypervisor should only contain a thin “bridge/agent” (optional), not retrieval.

---

## 1) Repo responsibilities (must/should)

### MUST (autocapture_prime)
- Ingest sessions from the **spool directory** produced by hypervisor.
- Decode frames (PNG first; optional HEVC segments later).
- Run OCR and text normalization:
  - Primary: PaddleOCR 3.x (PP-OCRv5 + PP-StructureV3).
  - Fallbacks: Tesseract and/or docTR (optional).
- Run UI layout parsing / element detection:
  - License-gated option: OmniParser (note AGPL for icon detector).
  - Alternative: UIED (Apache-2.0) with local OCR replacement.
- Temporal linking across frames using timestamps + pointer-event anchors.
- Store derived facts in:
  - Parquet for columnar frame/element tables,
  - DuckDB for local analytics,
  - Zstd compression for large JSON blobs,
  - FAISS for vector search (optional but recommended).
- Run vLLM serving for InternVL3.5-8B and expose a **chronicle_api** that:
  - offers OpenAI-compatible `/v1/chat/completions` (recommended),
  - performs retrieval across time and attaches relevant frames/crops,
  - calls vLLM’s OpenAI-compatible server.

### SHOULD (autocapture_prime)
- Adaptive downscaling + ROI extraction for small text (tab titles, timestamps).
- Multi-screenshot QA that avoids feeding dozens of full frames by retrieving
  top-k candidates.
- Embedding-based retrieval (text + multimodal) with strict safety gating.

---

## 2) Required contracts (must match hypervisor exactly)

Because there is no third repo, the safest approach is to **duplicate the
contract files verbatim** in both repos under the same path, and add a drift
check (hash match). Hypervisor writes; autocapture_prime reads.

### 2.1 Create: `contracts/chronicle/v0/chronicle.proto`

```proto
syntax = "proto3";
package chronicle.v0;

// NOTE: v0 is intentionally simple and append-only.
// Do not reuse field numbers. Add new fields with new numbers.
// When removing fields, mark them reserved.

message RectI32 {
  int32 x = 1;  // left in desktop pixels
  int32 y = 2;  // top in desktop pixels
  int32 w = 3;  // width in pixels
  int32 h = 4;  // height in pixels
}

enum PixelFormat {
  PIXEL_FORMAT_UNSPECIFIED = 0;
  BGRA8 = 1;    // 4 bytes/pixel, typical Windows capture surface
  NV12  = 2;    // common video encode/decode interchange
}

message DpiInfo {
  // Desktop/monitor scaling; used to normalize coordinates across DPI.
  float scale_x = 1;
  float scale_y = 2;
  uint32 dpi_x = 3;
  uint32 dpi_y = 4;
  string monitor_id = 5; // stable per-monitor identifier if available
}

message SessionManifest {
  string schema_version = 1; // must be "chronicle/v0"
  string session_id = 2;     // UUID string
  string host_id = 3;        // stable anonymized host identifier
  int64 qpc_frequency_hz = 4;

  // Start/end are optional until session closes; qpc is primary timeline.
  int64 start_qpc_ticks = 5;
  int64 end_qpc_ticks = 6;

  // Wall clock is best-effort and may be absent/zero if policy forbids.
  int64 start_unix_ns = 7;
  int64 end_unix_ns = 8;

  uint32 desktop_width = 9;
  uint32 desktop_height = 10;

  // Capture method identifier ("wgc", "dxgi", etc.)
  string capture_backend = 11;

  // Free-form JSON string for configuration snapshot (redacted as needed).
  string config_json = 12;
}

message FrameMeta {
  string session_id = 1;
  uint64 frame_index = 2;

  // Primary timebase
  int64 qpc_ticks = 3;

  // Optional wallclock
  int64 unix_ns = 4;

  uint32 width = 5;
  uint32 height = 6;
  PixelFormat pixel_format = 7;

  // Absolute desktop location of the captured content
  RectI32 desktop_rect = 8;

  // Dirty rectangles when provided by backend
  repeated RectI32 dirty_rects = 9;

  DpiInfo dpi = 10;

  // Relative path within session directory (e.g., "frames/frame_000123.png")
  string artifact_path = 11;

  // Optional integrity
  bytes sha256 = 12;
}

message FrameMetaBatch {
  repeated FrameMeta items = 1;
}

// IMPORTANT SAFETY NOTE:
// This contract intentionally omits system-wide keyboard telemetry.
// If you later decide to log keystrokes, treat that as a separate, explicit,
// opt-in feature with strong compliance controls.

enum InputEventType {
  INPUT_EVENT_UNSPECIFIED = 0;
  MOUSE = 1;

  // High-level, non-text control events (e.g., "start_capture", "stop_capture").
  CONTROL = 2;

  // Generic HID payloads for specific devices only when explicitly allowed.
  GENERIC_HID = 3;
}

message MouseEvent {
  // Absolute pointer position in desktop pixels
  int32 x = 1;
  int32 y = 2;

  // Relative movement since last event (device reported)
  int32 delta_x = 3;
  int32 delta_y = 4;

  // Bitmask of pressed buttons (implementation-defined but stable)
  uint32 buttons = 5;

  // Wheel delta (WHEEL_DELTA units)
  int32 wheel_delta = 6;
}

message ControlEvent {
  // Examples: "start_capture", "stop_capture", "bookmark".
  string action = 1;

  // Optional free-form JSON payload (append-only).
  string payload_json = 2;
}

message GenericHidEvent {
  // Minimal shape; include opaque payload only if policy allows.
  uint32 usage_page = 1;
  uint32 usage = 2;
  bytes payload = 3;
}

message InputEvent {
  string session_id = 1;
  uint64 event_index = 2;

  // Primary timebase
  int64 qpc_ticks = 3;

  // Optional wallclock
  int64 unix_ns = 4;

  // Device identifier MUST be anonymized (hash) unless policy allows raw.
  string device_id = 5;

  InputEventType type = 6;

  oneof payload {
    MouseEvent mouse = 10;
    ControlEvent control = 11;
    GenericHidEvent generic_hid = 12;
  }
}

message InputEventBatch {
  repeated InputEvent items = 1;
}

enum UiElementType {
  UI_ELEMENT_UNSPECIFIED = 0;
  WINDOW = 1;
  PANE = 2;
  TAB = 3;
  BUTTON = 4;
  TEXT = 5;
  ICON = 6;
  INPUT = 7;
}

message UiElement {
  string element_id = 1;   // stable within session if possible
  UiElementType type = 2;
  RectI32 bbox = 3;        // desktop pixels
  float confidence = 4;    // 0..1
  string label = 5;        // classifier label (optional)
  string text = 6;         // OCR text for element (optional)
  string parent_id = 7;    // containment (optional)
}

message DetectionFrame {
  string session_id = 1;
  uint64 frame_index = 2;
  int64 qpc_ticks = 3;
  repeated UiElement elements = 4;
}

message DetectionBatch {
  repeated DetectionFrame items = 1;
}
```

### 2.2 Create: `contracts/chronicle/v0/spool_format.md`

```text
ROOT_SPOOL/
  session_<session_id>/
    manifest.json
    meta/
      frames.pb.zst
      input.pb.zst
      detections.pb.zst
    frames/
      frame_000000.png
      frame_000001.png
      ...
    COMPLETE.json
```

**Atomicity rules**
- Hypervisor writes artifacts to `*.tmp` then renames atomically.
- `COMPLETE.json` is the final marker written last. Autocapture must ignore any
  session directory without COMPLETE.json.

**Compression**
- `*.pb.zst` are Zstandard-compressed protobuf payloads.

**manifest.json**
- JSON serialization of `SessionManifest` plus any extra fields (append-only).

### 2.3 Add a drift check

Add a CI check that:
- computes SHA-256 of `contracts/chronicle/v0/*`,
- compares against a pinned expected hash in this repo,
- fails if the contract changes without an explicit bump.

This prevents silent contract divergence between repos.

---

## 3) Environment prerequisites (WSL2 + CUDA invariants)

Codex should **not** attempt to install drivers, but must encode constraints in
docs and startup checks:

- CUDA on WSL2 requires the **Windows NVIDIA driver**; do not install a Linux
  display driver inside WSL.
- Use WSL-appropriate CUDA toolkit packages.
- Provide a runtime preflight that checks:
  - `nvidia-smi` is visible in WSL,
  - GPU compute is available,
  - vLLM can allocate on the GPU.

Add a `scripts/preflight.sh` that prints actionable failures.

---

## 4) Implementation plan (Codex tasks)

### 4.1 Add config: `config/autocapture_prime.yaml`

Required fields:
- `spool.root_dir_linux` (e.g., `/mnt/c/.../chronicle_spool`)
- `ingest.poll_interval_ms`
- `ingest.max_parallel_sessions`
- `ocr.engine` = `paddleocr` | `tesseract` | `doctr`
- `ocr.full_frame_scale` (e.g., 0.5)
- `ocr.roi_strategy` = `none` | `dirty_rects` | `heuristic_tabs` | `click_anchored`
- `layout.engine` = `none` | `omniparser` | `uied`
- `storage.root_dir`
- `storage.parquet_compression` = `zstd`
- `index.enable_duckdb` (bool)
- `index.enable_faiss` (bool)
- `vllm.base_url` (default `http://127.0.0.1:8000`)
- `vllm.model` (default `OpenGVLab/InternVL3_5-8B`)
- `vllm.trust_remote_code` (bool)
- `chronicle_api.host` (default `127.0.0.1`)
- `chronicle_api.port` (default `7020`)
- `privacy.allow_mm_embeds` (bool; default false)

Also add `config/example.autocapture_prime.yaml`.

### 4.2 Implement spool ingestion

Create module `autocapture_prime/ingest/` with:

- `SessionScanner`:
  - enumerates `ROOT_SPOOL/session_*`,
  - only processes sessions that contain `COMPLETE.json`,
  - tracks processed sessions in a local state DB (SQLite or DuckDB).

- `SessionLoader`:
  - loads `manifest.json`,
  - loads and decompresses `meta/*.pb.zst`,
  - provides iterators over:
    - frames (path + decoded image),
    - input events,
    - detections (if present).

- `FrameDecoder`:
  - MVP: PNG decoding (Pillow/OpenCV).
  - Optional: HEVC segment decode (PyAV/ffmpeg) if segments exist.

Timestamp alignment:
- Use QPC ticks as the primary key.
- Convert to relative time within session: `t = (qpc_ticks - start_qpc) / freq`.

Coordinate normalization:
- Ensure all bounding boxes are in desktop pixel coordinates as emitted by
  hypervisor; store DPI info for reference.

### 4.3 OCR pipeline (PaddleOCR primary)

Create `autocapture_prime/ocr/`:

- `OcrEngine` interface: `run(image, rois=None) -> list[TextSpan]`
- `TextSpan` includes:
  - `text`, `confidence`,
  - `bbox` (desktop pixels, not ROI-local),
  - `reading_order` (optional),
  - `language` (optional).

Implement `PaddleOcrEngine`:
- Use PaddleOCR 3.x high-performance inference configuration when available.
- Run a two-pass strategy:
  1) Downscaled full-frame pass for large text.
  2) ROI pass for small text (tabs, timestamps, click vicinity).

ROI strategies (configurable):
- From `FrameMeta.dirty_rects` if provided.
- Heuristic “tabstrip band” (top N% of window) when parsing browsers/terminals.
- Click-anchored: generate ROIs around recent click points.

Provide a deterministic OCR cache:
- key by `(frame_sha256, roi_rect, ocr_config_hash)`,
- store results on disk to avoid reprocessing.

Fallbacks (optional):
- `TesseractOcrEngine` for deterministic baseline.
- `DocTROcrEngine` for alternate model behavior.

### 4.4 Layout parsing / UI element detection

Create `autocapture_prime/layout/`:

- `LayoutEngine` interface: `run(image, ocr_spans) -> list[UiElement]`

Provide two plug-in backends:

#### Option A: OmniParser (license-gated)
- Implement integration behind a build/run flag.
- Enforce a **license gate**:
  - The icon detection component is AGPL-derived (per report).
  - Require an explicit config flag `layout.allow_agpl=true` to enable.
  - Default is false; when false, do not import/execute AGPL components.

#### Option B: UIED (Apache-2.0)
- Integrate UIED element detection.
- Replace any remote OCR dependency with local OCR spans already computed.

Output:
- Emit `UiElement` objects (same shape as protobuf):
  - stable `element_id` per frame,
  - `type`, `bbox`, `confidence`, optional `text`.

Write `derived/elements.parquet` per session:
- one row per element per frame:
  - `session_id`, `frame_index`, `qpc_ticks`, `type`, `bbox`, `text`, `confidence`.

### 4.5 Temporal linking

Create `autocapture_prime/link/`:

Goal: assign stable IDs across frames for windows/panes/elements.

Algorithm (MVP):
- For each frame, match elements to previous frame by:
  - IOU threshold on bbox,
  - type compatibility,
  - text similarity (for text elements),
  - optional click anchoring: if a click occurred at time t, boost matches for
    elements containing the click point.

Track state:
- `track_id` stable within session.
- Store an `id_switches` metric for evaluation.

Output tables:
- `derived/tracks.parquet`:
  - `track_id`, `frame_index`, `element_id`, `bbox`, `type`, `text`.

### 4.6 Storage + indexing

Create `autocapture_prime/store/`:

- Parquet datasets (partition by `session_id`):
  - `events_input.parquet`
  - `frames.parquet` (FrameMeta flattened)
  - `elements.parquet`
  - `tracks.parquet`
  - `ocr_spans.parquet`

- DuckDB:
  - optional local DB file that attaches these Parquet datasets for query.

- Zstd:
  - compress large per-frame graphs as `derived/frame_graph_<idx>.json.zst`.

Vector index (optional, recommended):
- If `index.enable_faiss=true`:
  - Create embeddings for:
    - OCR text chunks,
    - element text,
    - (optional) vision embeddings.
  - Store:
    - FAISS index on disk,
    - mapping table `vectors.parquet`.

**Safety gate for multimodal embeddings**
- vLLM has an option to enable multimodal embedding inputs; keep
  `privacy.allow_mm_embeds=false` by default.
- If enabled, restrict chronicle_api access to trusted local callers only.

### 4.7 vLLM serving (InternVL3.5-8B)

Add `services/vllm/`:

- `scripts/run_vllm.sh`:
  - runs `vllm serve` with:
    - model `OpenGVLab/InternVL3_5-8B`,
    - `--host 127.0.0.1 --port 8000`,
    - `--trust-remote-code` only if config allows,
    - optional quantization knobs (config-driven).

Add a health check script:
- verifies `GET /v1/models` responds.

Latency/throughput knobs (config-driven):
- `--max-num-batched-tokens`
- `--max-num-seqs`
Lowering can reduce latency at throughput cost.

### 4.8 Implement chronicle_api (the talk layer)

Create `services/chronicle_api/` with a Python HTTP API (FastAPI recommended).

#### 4.8.1 Endpoints (minimum)
- `GET /health` → ok
- `GET /sessions` → list ingested sessions
- `GET /sessions/{session_id}` → session metadata + available tables
- `POST /ingest/scan` → trigger spool rescan
- `POST /v1/chat/completions` → OpenAI-compatible chat endpoint (recommended)

#### 4.8.2 OpenAI-compatible behavior (`/v1/chat/completions`)
Implement a **retrieval-augmented** chat completion:

Input:
- Standard OpenAI ChatCompletions JSON.

Policy:
- retrieve candidate frames by:
  - time range,
  - keyword match over OCR text,
  - optional vector search.

- Select top-k frames (config `qa.top_k_frames`, default 3–5).
- For each selected frame:
  - attach either:
    - base64-encoded PNG as a `data:image/png;base64,...` `image_url`, OR
    - serve local assets and pass URLs (optional).

Call vLLM:
- Forward the constructed messages to vLLM’s OpenAI-compatible endpoint at
  `vllm.base_url`.

Return:
- vLLM response directly, plus optional `chronicle` metadata in `response.usage`
  or an extension field (append-only).

#### 4.8.3 Security
- Bind to `127.0.0.1` by default.
- Do not expose raw frame file serving unless explicitly enabled.
- If enabling any embedding endpoints, require explicit allowlist.

### 4.9 CLI entrypoints

Add a repo CLI:
- `autocapture_prime ingest --once|--watch`
- `autocapture_prime build-index --session <id>|--all`
- `autocapture_prime serve` (starts chronicle_api)

---

## 5) Tests and regression gates (do not ship if regress)

### 5.1 Unit tests
- Protobuf decode/encode round-trip.
- Zstd compression/decompression correctness.
- OCR span coordinate remapping from ROI to desktop coords.
- Temporal linker stability on synthetic sequences.

### 5.2 Integration tests (local)
- Use a recorded spool session from hypervisor (committed to test fixtures
  if policy allows; otherwise generate a synthetic minimal session).
- Validate:
  - sessions are discovered only after COMPLETE.json,
  - derived Parquet tables are created,
  - chronicle_api can answer a trivial question about a known screenshot
    (golden answer or contains-keyword check).

### 5.3 Evaluation metrics (store + track)
- OCR accuracy proxy:
  - compare OCR output against known expected tokens for fixture frames.
- Linker quality proxy:
  - count ID switches across fixture sequence.
- QA latency:
  - measure p50/p95 request time for a fixed prompt set.

---

## 6) Definition of done (autocapture_prime)

Autocapture_prime is considered complete when:
- It ingests hypervisor sessions and produces Parquet outputs.
- It runs vLLM serving for InternVL3.5-8B in WSL2.
- chronicle_api serves `/v1/chat/completions` and returns answers grounded in
  retrieved frames (validated on a fixture session).
- Contract drift checks pass.

---

## 7) Open questions to encode as config (do not block implementation)

- Continuous vs click-triggered capture cadence assumptions.
- Whether HEVC segment decode is needed immediately.
- OmniParser licensing acceptability (AGPL gate).
- Privacy/retention/encryption requirements.
- Whether `trust_remote_code` is allowed in production.

Encode them as config flags with safe defaults.
