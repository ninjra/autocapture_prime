# Autocapture Prime

## Project Overview

Autocapture Prime is a **local-first, privacy-focused screenshot and activity capture system** for Windows (running processing on WSL2). It continuously captures screenshots, UI automation metadata, keyboard/mouse input, audio, and clipboard events, then processes them through a multi-stage pipeline to produce a queryable "memory" corpus. Users can ask natural-language questions about their past screen activity and receive citation-backed answers grounded in the captured evidence.

Core design principles:
- **Localhost-only**: all services bind to 127.0.0.1; no remote access
- **No local deletion**: no delete endpoints; no retention pruning; archive/migrate only
- **Raw-first storage**: no masking/filtering locally; sanitization only on explicit export
- **Foreground gating**: when user is active, only capture+kernel runs; heavy processing pauses
- **Idle budgets**: CPU <= 50%, RAM <= 50% enforced; GPU may saturate
- **Citation-required answers**: never fabricate; clearly say when uncitable/indeterminate

## Architecture

### Three Runtime Packages

1. **`autocapture_nx/`** (canonical runtime) — The primary runtime. Contains:
   - `kernel/` — Config loading, audit, crypto/keyring, metadata store (SQLite), evidence records, query pipeline, hashing, telemetry, schema registry, determinism enforcement, doctor/diagnostics
   - `capture/` — Screenshot pipeline (MSS-based), AVI segment writer, deduplication, spool queues, screenshot policy
   - `processing/` — Idle-time processing (OCR, VLM extraction), SST (Screen State Tracking) pipeline with 15+ stages: normalize, tile, OCR, UI parse, layout, delta, action inference, cursor tracking, chart/table/code extraction, compliance redaction, persistence, indexing
   - `runtime/` — Batch runner (DAG-style), conductor (scheduling), governor (budget enforcement), HTTP localhost server, service ports
   - `storage/` — Stage1 derived store (SQLite overlay), facts NDJSON, retention, spillover, migrations
   - `plugin_system/` — Manifest-driven plugin discovery, registry, sandbox, lock signing, hash verification, capability-based wiring
   - `ux/` — Facade (shared by CLI and web), settings schema, fixture helpers
   - `state_layer/` — JEPA-like state model, anomaly detection, evidence compiler, vector indexes (HNSW/SQLite), workflow miner, retrieval
   - `ingest/` — File ingest, handoff ingest, UIA observation docs, stage2 projection docs
   - `inference/` — OpenAI-compatible client, vLLM endpoint adapter
   - `indexing/` — ColBERT indexing
   - `windows/` — Win32 APIs: ACL, DPAPI, credential manager, fullscreen detection, power management, screensaver, tray, cursor, idle detection, sandbox, window metadata
   - `tray.py` — Windows system tray integration with pywebview UI

2. **`autocapture/`** (legacy UX) — Deprecated facades. Contains the original web API routes (FastAPI), gateway, promptops engine, research runner, training (LoRA/DPO), retrieval (fusion/rerank/tiers), indexing (lexical/vector/graph), memory answer orchestrator, citations, and storage modules. Still in active use for runtime conductor/governor/budgets and web routes but marked for migration to NX.

3. **`autocapture_prime/`** (chronicle ingest) — Batch ingest pipeline for protobuf-encoded capture sessions. Contains OCR engines (PaddleOCR, Tesseract), layout engines (OmniParser, UIED), temporal linking, DuckDB/Parquet/FAISS indexing (chronicle v0), and a FastAPI chronicle API service.

### Plugin System

~85 builtin plugins in `plugins/builtin/`, covering:
- **Capture**: screenshot, cursor, audio, clipboard, input, window metadata, file activity (all Windows-specific)
- **OCR**: GPU, ONNX, RapidOCR, Nemotron, stub
- **VLM**: Qwen2-VL (2B/7B), MiniCPM, LLaVA, DeepSeek-OCR2, vLLM localhost, stub
- **Embeddings**: vLLM localhost, stub
- **SST Processing**: 15+ stage plugins (normalize, tile, OCR, UI parse, layout, delta, action, cursor, chart/table/code/spreadsheet extraction, compliance, persist, QA answers, temporal segmentation)
- **State Layer**: anomaly, evidence compiler, JEPA model/training, policy, retrieval, vector indexes, workflow miner
- **Storage**: SQLCipher encrypted, media, memory
- **Retrieval/Answer**: basic retrieval, ColBERT reranker (hash/torch), answer builder, citation validator, screen parse/index/answer
- **Runtime**: governor, scheduler, backpressure
- **Other**: observability, observation graph, journal, ledger, time (basic/advanced), prompt bundle, egress gateway/sanitizer, research, devtools

Plugins are locked via `config/plugin_locks.json` with SHA256 manifest+artifact hashes. Conflicts, capabilities, and dependencies are declaratively managed.

### Data Flow

```
[Windows Capture] -> metadata.db + media/ + spool/
                          |
                    [Handoff Spool]
                          |
                  [Stage1: Idle Processing]
                  (OCR, UIA docs, SST pipeline)
                          |
                   stage1_derived.db + markers
                          |
                  [Stage2: Projection/Indexing]
                  (text records, derivation edges, indexes)
                          |
                   metadata.live.db (read replica)
                          |
                  [Query Path]
                  (retrieval -> LLM synthesis -> citations)
```

### Key Databases

- `metadata.db` — Primary capture-side SQLite, actively written by capture
- `metadata.live.db` — Read/processing-safe replica for query path
- `derived/stage1_derived.db` — Stage1 derived overlay store for normalized outputs
- Stage1OverlayStore reads derived first, falls back to ingest metadata

### Web API

FastAPI-based, localhost-only. Routes for: query, health, status, settings, plugins, media, metadata, metrics, telemetry, trace, state, storage, auth, alerts, bookmarks, citations, doctor, egress, keys, run, timeline, verify.

### CLI

Entry point: `python -m autocapture_nx` (or `autocapture` command). Subcommands include: doctor, config (show/reset/restore), query, batch, backup, restore, plugins (list/enable/disable/approve/quarantine/settings/locks), keyring, export, capture, status, tray.

## Environment

- **Python**: >=3.10 (CI uses 3.11)
- **Platform**: Windows (capture) + WSL2 Ubuntu 22.04 (processing/development)
- **Virtual envs**: `.venv` (WSL), `.venv_win` and `.venv_win311` (Windows)
- **Core deps**: FastAPI, uvicorn, httpx, cryptography, psutil, pywebview, mss, Pillow, pynput, sounddevice, PyYAML, PyPDF2, protobuf, zstandard, jsonschema, platformdirs, tzdata
- **Optional deps**:
  - `sqlcipher`: pysqlcipher3-binary (encrypted SQLite)
  - `ocr`: pytesseract
  - `embeddings`: sentence-transformers, torch
  - `vision`: transformers, torch
  - `chronicle`: duckdb, pyarrow, faiss-cpu
  - `dev`: ruff, mypy, pip-audit
- **Data root**: `/mnt/d/autocapture/` (WSL path to Windows data)
- **GPU**: Optional CUDA for VLM/OCR/embeddings; GPU may saturate during idle processing
- **Linting**: ruff (configured in pyproject.toml, excludes .venv_win*)
- **Type checking**: mypy (mypy.ini present)
- **Build**: setuptools + wheel

## Current State

### Working
- **Capture pipeline**: Screenshot capture with deduplication, AVI segment encoding, spool queues, overflow handling
- **Plugin system**: Full lifecycle — discovery, manifest validation, lock enforcement, hash verification, enable/disable/quarantine/approve, conflict resolution, capability wiring
- **Stage1 processing**: Idle-time OCR/VLM extraction with adaptive parallelism, SLA control, metadata DB stability guard
- **Query pipeline**: Metadata-only mode, citation-backed answers, temporal/calendar query support, fast-cache, state policy gate
- **Batch runner**: DAG-style processing with budget enforcement, handoff spool drain, landscape manifests
- **Runtime governor**: Foreground gating, idle budget enforcement, heavy-work leases
- **Q40 validation suite**: 40 questions gauntlet with strict semantic gates (calendar, temporal, advanced), deterministic scoring
- **574 test files** with extensive coverage of kernel, processing, storage, plugins, query, and runtime
- **CI**: GitHub Actions — chronicle stack gate, strict Q40 synthetic gate, repo hygiene checks
- **Config system**: JSON schema validated, deep-merge defaults+user, capture presets, safe mode, metadata-only profile

### In Progress (branch: clean/q40-20260225)
- Stabilizing strict Q40 calendar and temporal semantic gates (latest commit)
- Improving idle throughput and stage1 overlay detection
- Fixing query fast-cache stale retention and leak guards
- Hardening projection freshness and stage2 index readiness gates
- Pipeline catch-up and freshness recovery (documented plan)
- Stage1/Stage2 golden background preprocessing pipeline (documented plan)

### Key Metrics (from recent artifacts)
- `frames_total=18087`, `frames_queryable=18087`, `stage1_ok=18087`
- Latest queryable frame: ~2026-02-21 (stale — freshness lag is a known issue)
- Retention validation needs work (`retention_ok` was low in some runs)
- Stage2 completion path needs restoration (`derived.ingest.stage2.complete=0` in some runs)

## Known Issues

1. **Freshness lag**: Latest queryable frame timestamp can lag days behind actual capture. Background processing stalls on stale mirror DB reads. See `docs/plans/pipeline-catchup-idle-freshness-plan.md`.

2. **Stage2 completion gap**: `derived.ingest.stage2.complete` counts are zero in some audit runs. Stage2 projection/indexing path needs restoration.

3. **Retention validation collapse**: `retention_ok` count drops dramatically in some configurations, despite stage1 completeness being high.

4. **Real corpus strict gate failures**: 17/20 failures in real corpus strict gate. Source tier attribution and citation chain integrity need hardening.

5. **Metadata DB hot-writer contention**: When capture is actively writing to `metadata.db`, background processing reads can stall. Stability guard with bounded retries exists but can block processing entirely.

6. **Zero-throughput idle loops**: Batch processing can report `pending_records > 0` with `throughput_records_per_s = 0` without escalation.

7. **Legacy package coupling**: `autocapture_nx` imports from `autocapture` (legacy) for conductor, governor, budgets, storage, indexing, and runtime. Full migration to NX is incomplete.

8. **Query path `schedule_extract` disabled**: Query path operates in metadata-only/raw-off mode. Real-time extraction during query is not currently used.

9. **Large file at root**: `repomix-output.md` (14MB) and `codexia.AppImage` (100MB) in repo root (gitignored but present).

## Session Log

_Updated at end of each session._

## Decisions

1. **autocapture_nx is canonical**: Legacy `autocapture` UX facades are deprecated. All new work goes in `autocapture_nx`. The `autocapture-prime` CLI is a deprecated shim.

2. **Plugin-forward architecture**: All capabilities are wired through the plugin system with manifest-driven discovery, hash-locked artifacts, and capability-based routing. No hardcoded feature paths.

3. **Two-DB split (metadata.db / metadata.live.db)**: Capture writes to `metadata.db`; query reads from `metadata.live.db` for isolation. Stage1 derived overlay bridges both.

4. **Stage1 is the only raw-media consumer**: After Stage1 completion, all downstream (Stage2, query, retrieval) must operate only on normalized artifacts. No raw media reads in the query path.

5. **No local deletion policy**: Archive/migrate only. No delete endpoints, no retention pruning that removes data. Append-only audit log for all privileged operations.

6. **Foreground gating with idle budgets**: Heavy processing (OCR, VLM, indexing) only runs when user is idle. CPU/RAM capped at 50% during idle. GPU may saturate.

7. **Citation-required answers**: Query responses must include citations from normalized evidence. Uncitable or indeterminate results must be explicitly labeled.

8. **SQLite everywhere**: Metadata, derived store, stage1 overlay, config, keyring, audit — all SQLite. Optional SQLCipher for encryption at rest.

9. **Q40 gauntlet as quality gate**: 40-question suite (20 advanced + 20 generic) with strict evaluation semantics (evaluated=total, skipped=0, failed=0) gates releases.

10. **Adaptive parallelism in batch processing**: Idle processing auto-scales CPU concurrency, batch size, and items-per-run based on system pressure, queue depth, and latency targets.

## Next Steps

1. **Fix freshness lag** — Implement metadata source arbitration so batch processing reads from fresh capture source rather than stale mirror. Add freshness SLO gates.

2. **Restore Stage2 completion path** — Ensure `derived.ingest.stage2.complete` markers are emitted and Stage2 projection/indexing progresses.

3. **Fix retention validation** — Ensure retention eligibility markers are correctly written for all Stage1-complete frames.

4. **Improve real corpus strict gate pass rate** — Currently 3/20 pass; needs source tier attribution, citation chain integrity, and fresh-window corpus.

5. **Zero-throughput guard** — Detect and escalate when batch processing has pending records but zero completions.

6. **Overnight soak validation** — Prove stable unattended operation with monotonic recency improvement and bounded memory.

7. **Complete NX migration** — Migrate remaining `autocapture` (legacy) modules to `autocapture_nx` to remove cross-package coupling.

8. **Stage2+ query correctness** — Ensure newly ingested frames produce citation-backed answers using only normalized layer records.
