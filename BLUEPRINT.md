# 1. System Context & Constraints
   Project_Scope: Prime (this repo) MUST become a complete, higher-quality successor to Autocapture by implementing all missing Autocapture ideas/subsystems (not copying code) with full functionality/nuance, with no stubs or deferred-work markers; output is an implementation-ready architectural blueprint for Codex CLI to generate code.
   Architectural_Hard_Rules:

* Prime MUST implement everything missing from Autocapture with 100% functionality and nuance coverage; nothing may be left as stubs or deferred-work placeholders.
* Prime MUST treat Autocapture as the idea/reference surface; Prime is the new vehicle and must incorporate the ideas, not copy the code.
* Prime MUST remain “plugin-forward”: kernel loads config, enforces policy, and composes capabilities via plugins.
* Prime MUST be local-first: capture and store locally; cloud must not receive raw PII; sanitization occurs only on egress.
* Prime MUST be single-user and single-machine.
* Prime MUST deny network by default; only the egress gateway may request network permission.
* Prime MUST enforce plugin allowlisting and hash locks (plugin artifacts/manifests pinned by hashes).
* Prime MUST be fail-closed for security invariants (deny egress if leak checks fail; enforce encryption-at-rest when required).
* Prime MUST be auditably append-only for journal + ledger; ledger entries must be hash-chained, with an anchor store recording head hashes.
* Prime MUST provide full doctor/diagnostics parity (DB/encryption/qdrant/ffmpeg/capture backends/OCR/embeddings/vector index/LLM/API/metrics/raw input).
* Prime MUST provide API + UX/UI parity (FastAPI server, routes/middleware, web UI, overlay tracker, UX facade).
* Prime MUST provide export/import parity (ZIP export incl. events.jsonl + manifests + redacted configs; roundtrip correctness).
  Environment_Standards:
* Language_Runtime: Python (project expects Windows 11; model paths under `D:\autocapture\models`; optional FFmpeg with NVENC).
* Config_Format: JSON defaults + optional JSON user overrides merged into “effective config”; schema pinned and hash-locked.
* Contracts_Pinned: config schema, plugin manifest schema, plugin SDK, security contract, user surface contract, journal/ledger schemas, reasoning packet schema, time intent schema, plus Autocapture Phase-0 contracts (FrameRecord/OCRSpan/RetrievalResult) adapted into Prime.
* Security_Posture:

  * Network denied by default; only egress gateway may request network permission.
  * Egress sanitization must produce typed tokens `⟦ENT:<TYPE>:<TOKEN>⟧` and a glossary, and must block egress on leak check failure.
  * Secrets must never be persisted plaintext; any secrets in source material must be treated as untrusted and redacted in outputs.
* Error_Handling:

  * Fail-closed for invariant violations (doctor, contracts, encryption required, leak detection).
  * CLI exit codes follow pinned contract (0 success, 1 runtime/config error, 2 invariant failure).
* Determinism:

  * Contract hashing lock file must pin all contract files.
  * Canonical JSON must be used for ledger hashing.
## Source_Index
* SRC-001:
  Type: Requirement
  Priority: MUST
  Quote: "prime needs to have everything implemented that is missing from autocapture."
  Notes: Conversation (user message, 2026-01-25).
* SRC-002:
  Type: Requirement
  Priority: MUST
  Quote: "implement all as recommended with 100% functionality and nuance coverage."
  Notes: Conversation (user message, 2026-01-25).
* SRC-003:
  Type: Constraint
  Priority: MUST
  Quote: "do not leave any stubs todos implement laters or etc."
  Notes: Conversation (user message, 2026-01-25).
* SRC-004:
  Type: Requirement
  Priority: MUST
  Quote: "prime is the new vehicle and we need all the ideas from autocapture, not the code."
  Notes: Conversation (user message, 2026-01-25).
* SRC-005:
  Type: Data
  Priority: MUST
  Quote: "Autocapture snapshot contains 785 file sections; Prime snapshot contains 153; only 5 identical relative paths."
  Notes: Conversation (user message, 2026-01-25).
* SRC-006:
  Type: Data
  Priority: MUST
  Quote: "Autocapture repo includes many subsystems absent from Prime’s tree (e.g., autocapture/api, ui, ux, overlay_tracker, qdrant)."
  Notes: Conversation (user message, 2026-01-25).
* SRC-007:
  Type: Data
  Priority: MUST
  Quote: "Prime repo is centered on autocapture_nx (kernel + plugin system) and plugins/builtin/*."
  Notes: Conversation (user message, 2026-01-25).
* SRC-008:
  Type: Data
  Priority: MUST
  Quote: "Autocapture capture orchestration references multiple backends (DXCAM + MSS)... Prime’s capture path is a plugin capturing frames and writing ZIP/JPEG segments."
  Notes: Conversation (user message, 2026-01-25).
* SRC-009:
  Type: Requirement
  Priority: MUST
  Quote: "Autocapture exports capture data to a ZIP including events.jsonl..."
  Notes: Conversation (user message, 2026-01-25).
* SRC-010:
  Type: Data
  Priority: MUST
  Quote: "Prime answering and retrieval are minimal... Autocapture has a richer answer/evidence model."
  Notes: Conversation (user message, 2026-01-25).
* SRC-011:
  Type: Data
  Priority: MUST
  Quote: "Prime uses lockfiles to pin plugin manifests/artifacts... Autocapture uses a plugin manager with discovery and policy layers."
  Notes: Conversation (user message, 2026-01-25).
* SRC-012:
  Type: Requirement
  Priority: MUST
  Quote: "API server + routes + middleware (Autocapture autocapture/api/*)."
  Notes: Missing subsystem grouping from conversation (user message, 2026-01-25).
* SRC-013:
  Type: Requirement
  Priority: MUST
  Quote: "UI & UX (tray UI, web UI assets, UX facade)."
  Notes: Missing subsystem grouping from conversation (user message, 2026-01-25).
* SRC-014:
  Type: Requirement
  Priority: MUST
  Quote: "Overlay tracker subsystem (autocapture/overlay_tracker/*)."
  Notes: Missing subsystem grouping from conversation (user message, 2026-01-25).
* SRC-015:
  Type: Requirement
  Priority: MUST
  Quote: "Qdrant + embeddings + hybrid indexing (autocapture/qdrant/*, autocapture/embeddings/*, autocapture/indexing/*)."
  Notes: Missing subsystem grouping from conversation (user message, 2026-01-25).
* SRC-016:
  Type: Requirement
  Priority: MUST
  Quote: "LLM/agent stack (autocapture/llm/*, autocapture/agents/*, memory_service/*)."
  Notes: Missing subsystem grouping from conversation (user message, 2026-01-25).
* SRC-017:
  Type: Requirement
  Priority: MUST
  Quote: "Installer / infra / alembic migrations / src layout."
  Notes: Missing subsystem grouping from conversation (user message, 2026-01-25).
* SRC-018:
  Type: Requirement
  Priority: MUST
  Quote: "Export/import pipeline (Autocapture export ZIP + manifest workflow)."
  Notes: Missing subsystem grouping from conversation (user message, 2026-01-25).
* SRC-019:
  Type: Requirement
  Priority: MUST
  Quote: "“Gateway” model & docs used in Autocapture’s architecture... with no parity module in Prime."
  Notes: Missing subsystem grouping from conversation (user message, 2026-01-25).
* SRC-020:
  Type: Requirement
  Priority: MUST
  Quote: "R1 — Capture parity: backend selection, dedupe, privacy filter, FFmpeg segments, enrichment."
  Notes: Conversation per_recommendation R1 (user message, 2026-01-25).
* SRC-021:
  Type: Requirement
  Priority: MUST
  Quote: "R2 — Input/idle gating + foreground context (url/domain/app) parity."
  Notes: Conversation per_recommendation R2 (user message, 2026-01-25).
* SRC-022:
  Type: Requirement
  Priority: MUST
  Quote: "R3 — Storage parity: typed records + migrations + retention + export/import."
  Notes: Conversation per_recommendation R3 (user message, 2026-01-25).
* SRC-023:
  Type: Requirement
  Priority: MUST
  Quote: "R4 — OCR + embeddings + vector index + hybrid retrieval parity."
  Notes: Conversation per_recommendation R4 (user message, 2026-01-25).
* SRC-024:
  Type: Requirement
  Priority: MUST
  Quote: "R5 — Answer builder parity: evidence model, claim validation, citation rendering, contradiction checks."
  Notes: Conversation per_recommendation R5 (user message, 2026-01-25).
* SRC-025:
  Type: Requirement
  Priority: MUST
  Quote: "R6 — API + UI/UX parity (if Prime must match Autocapture user surface)."
  Notes: Conversation per_recommendation R6 (user message, 2026-01-25).
* SRC-026:
  Type: Requirement
  Priority: MUST
  Quote: "R7 — Policy gate + secret vault + offline guard parity."
  Notes: Conversation per_recommendation R7 (user message, 2026-01-25).
* SRC-027:
  Type: Requirement
  Priority: MUST
  Quote: "R8 — Observability + doctor parity: metrics, health, deep dependency checks."
  Notes: Conversation per_recommendation R8 (user message, 2026-01-25).
* SRC-028:
  Type: Constraint
  Priority: MUST
  Quote: "Capture everything locally... Cloud never sees raw PII. Sanitization occurs only on egress."
  Notes: Prime MX blueprint non-negotiable.
* SRC-029:
  Type: Constraint
  Priority: MUST
  Quote: "Single user, single machine."
  Notes: Prime MX blueprint non-negotiable.
* SRC-030:
  Type: Constraint
  Priority: MUST
  Quote: "Deny-by-default network egress."
  Notes: Prime MX blueprint non-negotiable.
* SRC-031:
  Type: Decision
  Priority: MUST
  Quote: "D1 — Remove privacy sanitization and exclusion from capture/processing."
  Notes: Prime MX blueprint decision. 
* SRC-032:
  Type: Decision
  Priority: MUST
  Quote: "D7 — Remove deletion/retention; no deletion of local evidence."
  Notes: Prime MX blueprint decision.
* SRC-033:
  Type: Constraint
  Priority: MUST
  Quote: "Network access is denied by default."
  Notes: Security contract pinned. 
* SRC-034:
  Type: Constraint
  Priority: MUST
  Quote: "Only builtin.egress.gateway may request network permission."
  Notes: Security contract pinned. 
* SRC-035:
  Type: Constraint
  Priority: MUST
  Quote: "Plugin hashes must match config/plugin_locks.json."
  Notes: Security contract pinned. 
* SRC-036:
  Type: Constraint
  Priority: MUST
  Quote: "Sanitized payloads use typed tokens ⟦ENT:<TYPE>:<TOKEN>⟧ and a glossary."
  Notes: Security contract pinned. 
* SRC-037:
  Type: Constraint
  Priority: MUST
  Quote: "Egress is blocked if leak checks fail."
  Notes: Security contract pinned. 
* SRC-038:
  Type: Constraint
  Priority: MUST
  Quote: "Journal and ledger writers are append-only."
  Notes: Security contract pinned. 
* SRC-039:
  Type: Constraint
  Priority: MUST
  Quote: "Ledger entries are hash-chained with canonical JSON."
  Notes: Security contract pinned. 
* SRC-040:
  Type: Requirement
  Priority: MUST
  Quote: "The baseline user-visible interface is the autocapture CLI."
  Notes: User surface contract pinned. 
* SRC-041:
  Type: Requirement
  Priority: MUST
  Quote: "Commands: - autocapture doctor ... - autocapture query "<text>""
  Notes: User surface contract pinned (command list). 
* SRC-042:
  Type: Constraint
  Priority: MUST
  Quote: "Exit codes - 0: success - 1: ... - 2: invariant check failure"
  Notes: User surface contract pinned. 
* SRC-043:
  Type: Data_Contract
  Priority: MUST
  Quote: "required: plugin_id, version, enabled, entrypoints, permissions, compat, depends_on, hash_lock"
  Notes: Plugin manifest schema. 
* SRC-044:
  Type: Data_Contract
  Priority: MUST
  Quote: "entrypoints ... required: kind, id, path, callable"
  Notes: Plugin manifest schema. 
* SRC-045:
  Type: Data_Contract
  Priority: MUST
  Quote: "Journal ... required: schema_version, event_id, sequence, ts_utc, tzid, offset_minutes, event_type, payload"
  Notes: Journal schema pinned. 
* SRC-046:
  Type: Data_Contract
  Priority: MUST
  Quote: "Ledger ... required: schema_version, entry_id, ts_utc, stage, inputs, outputs, policy_snapshot_hash, prev_hash, entry_hash"
  Notes: Ledger schema pinned. 
* SRC-047:
  Type: Data_Contract
  Priority: MUST
  Quote: "Reasoning Packet v1 ... glossary ... entities use typed tokens."
  Notes: Reasoning packet schema and sanitizer spec. 
* SRC-048:
  Type: Data_Contract
  Priority: MUST
  Quote: "FrameRecord v1 ... Never compute latency deltas using wall-clock time. Use monotonic_ts only."
  Notes: Autocapture Phase 0 contracts. 
* SRC-049:
  Type: Data_Contract
  Priority: MUST
  Quote: "OCRSpan ... bbox_px ... frame_id and frame_hash provenance"
  Notes: Autocapture Phase 0 contracts. 
* SRC-050:
  Type: Data_Contract
  Priority: MUST
  Quote: "RetrievalResult v1 ... score breakdown fields ... Non-citable rule"
  Notes: Autocapture Phase 0 contracts. 
* SRC-051:
  Type: Behavior
  Priority: MUST
  Quote: "from autocapture.capture.backends import DXCAMBackend, MSSBackend"
  Notes: Autocapture multi-backend capture orchestration.
* SRC-052:
  Type: Behavior
  Priority: MUST
  Quote: "Autocapture export ZIP includes: events.jsonl, manifest.json, settings.json, config.json (redacted)."
  Notes: Export ZIP builder. 
* SRC-053:
  Type: Behavior
  Priority: MUST
  Quote: "/api/context-pack returns: {"version": 1, "query": ".", ... "evidence": [...] }"
  Notes: Context Pack v1 contract. 
* SRC-054:
  Type: Behavior
  Priority: MUST
  Quote: "Runtime governor modes ... FULLSCREEN_HARD_PAUSE ... ACTIVE_INTERACTIVE ... IDLE_DRAIN"
  Notes: Autocapture runtime gates doc. 
* SRC-055:
  Type: Behavior
  Priority: MUST
  Quote: "If excluded, should_skip_capture returns True."
  Notes: Autocapture privacy filter skip capture behavior (will be reconciled with D1).
* SRC-056:
  Type: Behavior
  Priority: MUST
  Quote: "Embedding service ... fastembed first; falls back to SentenceTransformer."
  Notes: Autocapture embedding service behavior. 
* SRC-057:
  Type: Decision
  Priority: SHOULD
  Quote: "ADR 003: Qdrant is opt-in."
  Notes: Autocapture ADR about Qdrant.
* SRC-058:
  Type: Data
  Priority: MUST
  Quote: "Default config ... capture.video.segment_seconds": 60"
  Notes: Prime default config.
* SRC-059:
  Type: Requirement
  Priority: MUST
  Quote: "Missing/incomplete in Prime ... Full doctor coverage parity ... Metrics/telemetry parity ..."
  Notes: Gap map diagnostics parity. 
## Coverage_Map
* SRC-001: Section 1/Project_Scope; MOD-007; ADR-001
* SRC-002: Section 1/Architectural_Hard_Rules; MOD-007; ADR-001
* SRC-003: Section 1/Architectural_Hard_Rules; MOD-007; ADR-001
* SRC-004: Section 1/Project_Scope; ADR-001
* SRC-005: ADR-001 (Scope justification)
* SRC-006: MOD-032; MOD-033; MOD-034; MOD-020; MOD-027; MOD-038
* SRC-007: MOD-001; MOD-002
* SRC-008: MOD-008; MOD-009; MOD-010; MOD-012
* SRC-009: MOD-030; ADR-005
* SRC-010: MOD-023; MOD-024; ADR-004
* SRC-011: MOD-002; MOD-031; ADR-002
* SRC-012: MOD-032
* SRC-013: MOD-033
* SRC-014: MOD-034; MOD-025
* SRC-015: MOD-019; MOD-020; MOD-021; MOD-023
* SRC-016: MOD-027; MOD-024; MOD-029
* SRC-017: MOD-038; MOD-039
* SRC-018: MOD-030
* SRC-019: MOD-027; ADR-006
* SRC-020: MOD-008; MOD-009; MOD-010; MOD-011; MOD-012; ADR-003
* SRC-021: MOD-014; MOD-015; MOD-013
* SRC-022: MOD-039; MOD-040; ADR-007
* SRC-023: MOD-017; MOD-019; MOD-020; MOD-023
* SRC-024: MOD-024; MOD-025
* SRC-025: MOD-032; MOD-033
* SRC-026: MOD-016; MOD-028; MOD-004
* SRC-027: MOD-036; MOD-035; MOD-032
* SRC-028: ADR-003; MOD-008; MOD-028
* SRC-029: Section 1/Architectural_Hard_Rules; ADR-001
* SRC-030: MOD-028; MOD-016; MOD-002
* SRC-031: ADR-003; MOD-016; MOD-008
* SRC-032: ADR-007; MOD-040
* SRC-033: MOD-028; MOD-002; MOD-032
* SRC-034: MOD-028; MOD-002
* SRC-035: MOD-002; MOD-031
* SRC-036: MOD-028; ADR-008
* SRC-037: MOD-028; MOD-032; ADR-008
* SRC-038: MOD-005; MOD-006
* SRC-039: MOD-006
* SRC-040: MOD-007; MOD-035; MOD-037
* SRC-041: MOD-007; MOD-035; MOD-037
* SRC-042: MOD-035; MOD-037
* SRC-043: MOD-002; MOD-031
* SRC-044: MOD-002; MOD-031
* SRC-045: MOD-005; ADR-009
* SRC-046: MOD-006; ADR-009
* SRC-047: MOD-028; ADR-008
* SRC-048: MOD-008; MOD-039
* SRC-049: MOD-017; MOD-022; MOD-025
* SRC-050: MOD-023; MOD-024
* SRC-051: MOD-009; MOD-010; MOD-008
* SRC-052: MOD-030; ADR-005
* SRC-053: MOD-032; MOD-023; MOD-024
* SRC-054: MOD-015
* SRC-055: ADR-003; MOD-016
* SRC-056: MOD-019
* SRC-057: ADR-010; MOD-020
* SRC-058: MOD-008; MOD-012
* SRC-059: MOD-035; MOD-036
## Validation_Checklist
* Ensure exactly 4 top-level sections exist in this BLUEPRINT.md and are in the required order.
* Ensure no deferred-work markers or placeholder language appears as deferral.
* Ensure every Object entry in Section 2 includes Sources and an explicit Interface_Definition.
* Ensure every ADR in Section 3 includes Sources.
* Ensure every SRC-### appears exactly once in Coverage_Map.
* Ensure every logic-heavy module listed in Section 2 has a 3-row sample table in Section 4.
* Ensure Legacy_I_Item_Crosswalk lists every legacy I-item exactly once and includes MOD coverage and Test/Gate fields.
* Ensure no secrets are reproduced; if any were present in sources, they are replaced with [REDACTED_SECRET] and noted.


## Legacy_I_Item_Crosswalk

This table enumerates legacy NX I-items and maps them to MOD/ADR coverage with explicit test gates.

| I-ID | Phase | Title | MOD Coverage | ADR Coverage | Test/Gate |
| --- | --- | --- | --- | --- | --- |
| I001 | Phase 1: Correctness + immutability blockers | Eliminate floats from journal/ledger payloads | MOD-006, MOD-005 | ADR-009 | Gate-CANON: reject floats/bytes; unit tests for all event types; Test: capture disk-pressure event emits integer bytes, not floats |
| I002 | Phase 1: Correctness + immutability blockers | Make backpressure actually affect capture rate | MOD-008, MOD-009, MOD-010 | - | Test: backpressure changes fps target and measured interval responds; Perf: capture tick p95 stays within budget under disk pressure |
| I003 | Phase 1: Correctness + immutability blockers | Stop buffering whole segments in RAM; stream segments | MOD-008, MOD-009, MOD-010 | - | Perf: sustained capture uses bounded RAM (ceiling configured); Test: segments written continuously without OOM on large resolutions |
| I004 | Phase 1: Correctness + immutability blockers | Do not write to storage from realtime audio callback | MOD-008, MOD-039, MOD-012 | - | Test: callback path performs no disk IO (mock store asserts not called); Perf: audio capture has no xruns under load (best-effort check) |
| I005 | Phase 1: Correctness + immutability blockers | Stop mutating primary evidence metadata during query | MOD-024, MOD-039 | - | Gate-IMMUT: detect `put_replace` on evidence types; Test: extraction creates `derived.*` record; parent unchanged (hash stable) |
| I006 | Phase 1: Correctness + immutability blockers | Introduce globally unique run/session identifier; prefix all record IDs | MOD-005, MOD-006 | - | Test: two runs produce non-colliding IDs even with same sequences; Gate: lint rule forbids bare `segment_0` style IDs in plugins |
| I007 | Phase 1: Correctness + immutability blockers | Make ledger writing thread-safe | MOD-005, MOD-006 | ADR-009 | Concurrency tests (Phase 0 I090) validate chain under multi-threading |
| I008 | Phase 1: Correctness + immutability blockers | Make journal writing thread-safe; centralize sequences | MOD-005, MOD-006 | ADR-009 | Test: concurrent writes produce strictly increasing per-stream sequence; Snapshot: journal schema stable and contains run_id |
| I009 | Phase 1: Correctness + immutability blockers | Fail closed if DPAPI protection fails when encryption_required | MOD-004, MOD-032, MOD-033 | - | Security test: DPAPI fail leads to startup failure when encryption_required; Doctor reports actionable remediation (recreate vault, permissions, etc.) |
| I010 | Phase 1: Correctness + immutability blockers | Sort all store keys deterministically | MOD-004 | - | Test: repeated `keys()` calls return identical order; Gate: retrieval is deterministic given identical data |
| I011 | Phase 1: Correctness + immutability blockers | Use monotonic clocks for segment duration | MOD-008, MOD-009, MOD-010 | - | Test: system clock changes do not break segment scheduling |
| I012 | Phase 1: Correctness + immutability blockers | Align default config with implemented capture backend | MOD-020, MOD-019, MOD-001 | - | Doctor warns if config selects unsupported backend; Test: default config runs capture without unsupported backend errors |
| I013 | Phase 1: Correctness + immutability blockers | Remove hard-coded model paths; config-driven + portable | MOD-020, MOD-019, MOD-001 | - | Test: no absolute host-specific paths in repo; Doctor: warns when model missing; offers download command |
| I014 | Phase 1: Correctness + immutability blockers | Enforce plugin compat.requires_kernel / schema versions | MOD-002, MOD-033, MOD-031 | ADR-002 | Test: incompatible plugin is refused with clear error; Doctor: lists plugin compat mismatches |
| I015 | Phase 1: Correctness + immutability blockers | Verify contract lock at boot/doctor | MOD-001, MOD-035, MOD-002 | - | Gate: contract lock verify in CI and on startup; Test: modifying contract file without lock update fails |
| I016 | Phase 2: Capture pipeline refactor | Split capture into grab → encode/pack → encrypt/write pipeline | MOD-008, MOD-009, MOD-010 | - | Perf: capture tick p95 within budget while pipeline backlog grows; Test: pipeline stages can be independently throttled/cancelled |
| I017 | Phase 2: Capture pipeline refactor | Bounded queues with explicit drop policies | MOD-008, MOD-009, MOD-010 | - | Test: queue never grows beyond configured max; Test: drops are recorded in metadata and journal |
| I018 | Phase 2: Capture pipeline refactor | Replace zip-of-JPEG with real video container for primary artifact | MOD-008, MOD-009, MOD-010 | ADR-005 | Test: segment decode/extract works on all supported OS targets; Test: container metadata timestamps align with recorded ts_start/end |
| I019 | Phase 2: Capture pipeline refactor | Add GPU-accelerated capture/encode backend (NVENC/DD) | MOD-008, MOD-009, MOD-010 | - | Perf: CPU usage drops vs mss baseline at target resolution/fps; Security: subprocess sandbox for encoder if using external binaries |
| I020 | Phase 2: Capture pipeline refactor | Record segment start/end timestamps | MOD-008, MOD-009, MOD-010 | - | Test: segments always have valid start/end with end >= start |
| I021 | Phase 2: Capture pipeline refactor | Record capture parameters per segment | MOD-008, MOD-009, MOD-010 | - | Schema test ensures required capture params exist |
| I022 | Phase 2: Capture pipeline refactor | Correlate frames with active window via synchronized timeline | MOD-013, MOD-008, MOD-012 | - | Test: given window-change events, frame-to-window mapping is correct |
| I023 | Phase 2: Capture pipeline refactor | Add cursor/input correlation timeline references | MOD-014, MOD-026 | - | Test: correlation graph includes references from text/citation to input bursts |
| I024 | Phase 2: Capture pipeline refactor | Disk pressure degrades capture quality before stopping | MOD-008, MOD-009, MOD-010 | - | Test: under simulated low disk, capture degrades (fps/quality) before stop; Journal: emits `disk.pressure` and `capture.degrade` events |
| I025 | Phase 2: Capture pipeline refactor | Atomic segment writes (temp + os.replace) | MOD-008, MOD-009, MOD-010 | - | Test: crash mid-write does not produce partially visible evidence; Recovery scanner (I104) reconciles temp artifacts safely |
| I026 | Phase 3: Storage scaling + durability | Default to SQLCipher for metadata when available | MOD-039, MOD-037 | - | encrypted_fs` |
| I027 | Phase 3: Storage scaling + durability | Add DB indexes on ts_utc, record_type, run_id | MOD-039 | - | EXPLAIN-based test: queries use indexes for common patterns |
| I028 | Phase 3: Storage scaling + durability | Store media in binary encrypted format (not base64 JSON) | MOD-039 | - | Test: media blobs are not valid JSON and have expected magic/version; Test: decrypt+verify hash roundtrip works |
| I029 | Phase 3: Storage scaling + durability | Stream encryption (avoid whole-segment in memory) | MOD-039, MOD-004, MOD-008 | - | Perf: writing large segments does not allocate segment-sized RAM; Test: chunk boundaries validate and reject tampering |
| I030 | Phase 3: Storage scaling + durability | Immutability/versioning in stores (put_new vs put_replace) | MOD-039 | - | Gate-IMMUT: evidence types cannot call replace; tests enforce |
| I031 | Phase 3: Storage scaling + durability | Make record ID encoding reversible (no lossy mapping) | MOD-039 | - | Test: encode→decode roundtrip yields same ID for all legal IDs |
| I032 | Phase 3: Storage scaling + durability | Shard media/metadata directories by date/run | MOD-039 | - | Perf test: listing/iterating keys remains fast at large scale |
| I033 | Phase 3: Storage scaling + durability | Add per-run storage manifest records | MOD-039, MOD-002, MOD-031 | - | Test: manifest exists for each run and includes expected hashes |
| I034 | Phase 3: Storage scaling + durability | Configurable fsync policy (critical vs bulk) | MOD-039, MOD-001 | - | Crash test: critical records survive; bulk media may lag but seals prevent inconsistency |
| I035 | Phase 4: Retrieval + provenance + citations | Replace full-scan query with tiered indexed retrieval | MOD-023, MOD-037 | - | Perf: query latency improves at N records vs full scan baseline; Accuracy: golden queries return expected evidence set deterministically |
| I036 | Phase 4: Retrieval + provenance + citations | Deterministic retrieval ordering (stable sort keys) | MOD-023, MOD-037, MOD-004 | - | Test: same dataset yields identical ranked output across runs |
| I037 | Phase 4: Retrieval + provenance + citations | Candidate-first extraction (retrieve then extract) | MOD-023 | - | Perf: extraction work bounded to top-K candidates; Accuracy: extraction uses explicit time/span constraints |
| I038 | Phase 4: Retrieval + provenance + citations | Derived artifact records for OCR/VLM outputs | MOD-017, MOD-018 | - | Test: derived text record includes parent reference and span_ref; Test: model identity fields present and hashed |
| I039 | Phase 4: Retrieval + provenance + citations | Ledger query executions (inputs/outputs) | MOD-005, MOD-006, MOD-014 | ADR-009 | Golden: query ledger entry reproducible for fixed corpus |
| I040 | Phase 4: Retrieval + provenance + citations | Ledger extraction operations (inputs/outputs) | MOD-005, MOD-006, MOD-014 | ADR-009 | Test: derived artifacts have corresponding ledger derivation entries |
| I041 | Phase 4: Retrieval + provenance + citations | Citations point to immutable evidence IDs + spans | MOD-024, MOD-032, MOD-033 | - | Schema test: citations cannot be created without required fields |
| I042 | Phase 4: Retrieval + provenance + citations | Citation resolver validates hashes/anchors/spans | MOD-024, MOD-032, MOD-033 | ADR-009 | Test: resolver detects tampering and missing spans |
| I043 | Phase 4: Retrieval + provenance + citations | Fail closed if citations do not resolve | MOD-024, MOD-032, MOD-033 | - | Golden tests: unresolved citations produce `state=no_evidence` or `state=partial` |
| I044 | Phase 5: Scheduler/governor | Real scheduler plugin gates heavy work on user activity | MOD-015, MOD-037, MOD-002 | ADR-002 | Test: ACTIVE mode prevents OCR/VLM/embeddings/indexing jobs from running; Test: IDLE mode allows bounded enrichment and records budgets in journal |
| I045 | Phase 5: Scheduler/governor | Input tracker exposes activity signals (not only journal) | MOD-014, MOD-034, MOD-006 | ADR-009 | Test: simulated input produces immediate ACTIVE signal; Test: inactivity decays to IDLE after configured timeout |
| I046 | Phase 5: Scheduler/governor | Capture emits telemetry (queues, drops, lag, CPU) | MOD-015, MOD-036, MOD-008 | - | Test: telemetry includes queue depths, drops, lag, CPU; Websocket (I83) streams telemetry with stable schema |
| I047 | Phase 5: Scheduler/governor | Governor outputs feed backpressure and job admission | MOD-015 | - | Integration test: governor changes lead to fps/quality changes within bounded time |
| I048 | Phase 5: Scheduler/governor | Immediate ramp down on user input (cancel/deprioritize heavy jobs) | MOD-015, MOD-014 | - | Test: user input interrupts ongoing enrichment within timeout budget |
| I049 | Phase 6: Security + egress hardening | Egress gateway must be subprocess-hosted; kernel network-denied | MOD-002, MOD-028, MOD-027 | ADR-008, ADR-006 | Security test: kernel cannot reach network even if code tries; Test: egress plugin can reach allowlisted endpoints only |
| I050 | Phase 6: Security + egress hardening | Minimize inproc_allowlist; prefer subprocess hosting | MOD-002, MOD-031 | - | Gate: fail if new inproc plugin added without security justification entry |
| I051 | Phase 6: Security + egress hardening | Capability bridging for subprocess plugins (real capability plumbing) | MOD-002, MOD-031 | ADR-002 | Test: subprocess plugin receives only declared capabilities and can operate |
| I052 | Phase 6: Security + egress hardening | Enforce least privilege per plugin manifest | MOD-002, MOD-031 | ADR-002 | Test: plugin without declared capability cannot access it |
| I053 | Phase 6: Security + egress hardening | Enforce filesystem permission policy declared by plugins | MOD-002, MOD-031 | ADR-002 | Test: plugin cannot read outside allowed roots (integration) |
| I054 | Phase 6: Security + egress hardening | Strengthen Windows job object restrictions (limits) | MOD-013 | - | Test: runaway plugin is terminated and reported |
| I055 | Phase 6: Security + egress hardening | Sanitize subprocess env; pin caches; disable proxies | MOD-002, MOD-028 | ADR-008 | Test: proxy env vars removed; cache dirs pinned |
| I056 | Phase 6: Security + egress hardening | Plugin RPC timeouts and watchdogs | MOD-002, MOD-031, MOD-026 | ADR-002 | Test: hung plugin call times out and system recovers without deadlock |
| I057 | Phase 6: Security + egress hardening | Max message size limits in plugin RPC protocol | MOD-002, MOD-031 | ADR-002 | Test: oversized message rejected; chunked streaming used for large blobs |
| I058 | Phase 6: Security + egress hardening | Harden hashing against symlinks / filesystem nondeterminism | MOD-002 | - | Test: symlinks in plugin root are rejected or hashed deterministically |
| I059 | Phase 6: Security + egress hardening | Secure vault file permissions (Windows ACLs) | MOD-004, MOD-013 | - | Test: created files are not world-readable (platform-dependent assertions) |
| I060 | Phase 6: Security + egress hardening | Separate keys by purpose (metadata/media/tokenization/anchor) | MOD-004, MOD-016, MOD-039 | ADR-009 | Test: rotating one key does not break others; derived artifacts remain readable as policy dictates |
| I061 | Phase 6: Security + egress hardening | Anchor signing (HMAC/signature) with separate key domain | MOD-006, MOD-004, MOD-005 | ADR-009 | Test: anchor verify fails if anchor modified or wrong key used |
| I062 | Phase 6: Security + egress hardening | Add verify commands (ledger/anchors/evidence) | MOD-005, MOD-006, MOD-024 | ADR-009 | Golden verification suite passes; tamper cases fail |
| I063 | Phase 6: Security + egress hardening | Audit security events in ledger (key rotations, lock updates, config) | MOD-005, MOD-006, MOD-004 | ADR-009 | Test: key rotation and lock updates emit ledger entries |
| I064 | Phase 6: Security + egress hardening | Dependency pinning + hash checking (supply chain) | MOD-002, MOD-019, MOD-038 | - | CI verifies dependency hashes; runtime doctor reports mismatches |
| I065 | Phase 4: Retrieval + provenance + citations | Define canonical evidence model (EvidenceObject) | MOD-008, MOD-012, MOD-024 | ADR-009 | Schema tests cover all evidence types and require minimal fields |
| I066 | Phase 4: Retrieval + provenance + citations | Hash everything that matters (media/metadata/derived) | MOD-008, MOD-012, MOD-039 | - | Verify: recomputed hashes match stored hashes for sample corpus |
| I067 | Phase 4: Retrieval + provenance + citations | Ledger every state transition | MOD-005, MOD-006 | ADR-009 | Gate: required event types appear for each run (start, evidence writes, stop/crash) |
| I068 | Phase 4: Retrieval + provenance + citations | Anchor on schedule (N entries or M minutes) | MOD-006, MOD-005 | ADR-009 | Test: anchors created at configured cadence; verification passes |
| I069 | Phase 4: Retrieval + provenance + citations | Immutable per-run manifest (config+locks+versions) | MOD-008, MOD-012, MOD-002 | - | Test: manifest includes config/plugin/contracts hashes + versions |
| I070 | Phase 4: Retrieval + provenance + citations | Citation objects carry verifiable pointers | MOD-024, MOD-032, MOD-033 | - | Resolver rejects citations missing required verification fields |
| I071 | Phase 4: Retrieval + provenance + citations | Citation resolver CLI/API | MOD-024, MOD-032, MOD-033 | - | Golden: resolver output stable and correct for known citations |
| I072 | Phase 4: Retrieval + provenance + citations | Metadata immutable by default; derived never overwrites | MOD-039 | - | Gate-IMMUT catches any overwrite on evidence/derived records |
| I073 | Phase 4: Retrieval + provenance + citations | Persist derivation graphs (parent→child links) | MOD-008, MOD-012 | - | Test: derived artifacts create derivation edge to parent |
| I074 | Phase 4: Retrieval + provenance + citations | Record model identity for ML outputs | MOD-008, MOD-012 | - | Test: derived artifacts contain model_name + model_digest + params |
| I075 | Phase 4: Retrieval + provenance + citations | Deterministic text normalization before hashing | MOD-026, MOD-021 | - | Test: normalization is deterministic and stable on sample inputs |
| I076 | Phase 4: Retrieval + provenance + citations | Proof bundles export (evidence + ledger slice + anchors) | MOD-030, MOD-024, MOD-006 | ADR-005, ADR-009 | Test: exported bundle verifies on a clean machine without network |
| I077 | Phase 4: Retrieval + provenance + citations | Replay mode validates citations without model calls | MOD-024, MOD-032, MOD-033 | - | Golden: replay reproduces expected citations and verification results |
| I078 | Phase 7: FastAPI UX facade + Web Console | FastAPI UX facade as canonical interface | MOD-032, MOD-033, MOD-006 | ADR-009 | API contract tests: endpoints stable and validated against schemas; Security: binds to localhost by default; requires auth token (I82) |
| I079 | Phase 7: FastAPI UX facade + Web Console | CLI parity: CLI calls shared UX facade functions | MOD-032, MOD-033, MOD-007 | - | Test: CLI commands produce identical results as API endpoints |
| I080 | Phase 7: FastAPI UX facade + Web Console | Web Console UI (status/timeline/query/proof/plugins/keys) | MOD-032, MOD-033, MOD-004 | ADR-002 | UI smoke tests: load pages and call API endpoints (headless); API snapshot tests for UI-critical views |
| I081 | Phase 7: FastAPI UX facade + Web Console | Alerts panel driven by journal events | MOD-032, MOD-033, MOD-006 | ADR-009 | Test: disk pressure and capture drops appear as alerts |
| I082 | Phase 7: FastAPI UX facade + Web Console | Local-only auth boundary (bind localhost + token) | MOD-032, MOD-033, MOD-016 | - | Security test: state-changing endpoints require auth token |
| I083 | Phase 7: FastAPI UX facade + Web Console | Websocket for live telemetry | MOD-032, MOD-033, MOD-036 | - | Test: websocket schema stable and rate-limited |
| I084 | Phase 0: Scaffolding and gates | Split heavy ML dependencies into optional extras | MOD-037, MOD-002, MOD-019 | - | CI matrix: minimal install runs capture+stores without ML deps; CI matrix: extras[vision]/[embeddings]/[sqlcipher] enable corresponding plugins; Gate: import-time scan ensures no heavy deps imported in ACTIVE ingest path |
| I085 | Phase 0: Scaffolding and gates | Make resource paths package-safe (no CWD dependence) | MOD-001 | - | Test: run from arbitrary CWD and verify default.json/contracts/plugins load; Wheel install test: builtin plugins discoverable and loadable |
| I086 | Phase 0: Scaffolding and gates | Use OS-appropriate default data/config dirs (platformdirs) | MOD-001 | - | Test matrix: Windows/Linux/WSL path resolution produces valid dirs; Doctor check: directories exist and are writable; vault is restricted |
| I087 | Phase 0: Scaffolding and gates | Package builtin plugins as package data | MOD-033, MOD-002, MOD-031 | ADR-002 | Wheel install test: `autocapture doctor` lists builtin plugins; Gate: plugin lock hashing includes packaged plugin files |
| I088 | Phase 0: Scaffolding and gates | Add reproducible dependency lockfile (hash-locked) | MOD-037, MOD-002, MOD-031 | - | Gate: lock drift check fails if deps change without lock update; Supply-chain test: install from lock only; run smoke tests |
| I089 | Phase 0: Scaffolding and gates | Add canonical-json safety tests for journal/ledger payloads | MOD-006, MOD-005 | ADR-009 | Test: generate sample events from each plugin; validate canonical JSON; Gate: fail on floats/bytes/non-UTC timestamps |
| I090 | Phase 0: Scaffolding and gates | Add concurrency tests for ledger/journal append correctness | MOD-005, MOD-006 | ADR-009 | Test: multi-thread append; verify entry count and stable chain; Test: forced thread interleavings do not corrupt files |
| I091 | Phase 0: Scaffolding and gates | Add golden chain test: ledger verify + anchor verify | MOD-005, MOD-006 | ADR-009 | Test: produce N entries; verify chain and anchor head deterministically; Test: tamper with one entry; verification fails |
| I092 | Phase 0: Scaffolding and gates | Add performance regression tests (capture latency/memory/query latency) | MOD-028, MOD-008, MOD-012 | ADR-008 | Bench: sustained capture at configured fps; assert bounded RAM; Bench: query over N records completes under budget |
| I093 | Phase 0: Scaffolding and gates | Add security regression tests (DPAPI fail-closed, network guard, no raw egress) | MOD-028, MOD-032, MOD-004 | ADR-008 | Test: DPAPI failure with encryption_required causes hard failure; Test: kernel process cannot open network sockets; Test: unsanitized egress blocked unless dangerous_ops enabled |
| I094 | Phase 0: Scaffolding and gates | Static analysis: ruff + typing + vuln scan | MOD-001, MOD-007 | - | CI fails on new lint/type errors; CI fails on high-severity dependency vulnerabilities (policy-defined) |
| I095 | Phase 0: Scaffolding and gates | Doctor validates locks, storage, anchors, and network policy | MOD-001, MOD-035, MOD-039 | ADR-009 | Test: doctor detects missing lockfile, plugin hash mismatch, bad perms; Test: doctor output is stable (snapshot test) |
| I096 | Phase 1: Correctness + immutability blockers | Fail loud on decrypt errors when encryption_required | MOD-004, MOD-033 | - | Test: corrupted ciphertext causes explicit error, not silent default; Doctor: can detect corruption and suggest recovery steps |
| I097 | Phase 1: Correctness + immutability blockers | Add record type fields everywhere | MOD-008, MOD-009, MOD-010 | - | Schema tests ensure `record_type` present for all stored records |
| I098 | Phase 1: Correctness + immutability blockers | Add unified EventBuilder helper | MOD-005, MOD-006, MOD-033 | - | Gate: forbid direct JournalWriter/LedgerWriter calls outside EventBuilder; Test: EventBuilder outputs canonical-json-safe payloads |
| I099 | Phase 1: Correctness + immutability blockers | Stamp every journal event with run_id | MOD-005, MOD-006 | ADR-009 | Test: all journal events include run_id |
| I100 | Phase 1: Correctness + immutability blockers | Cache policy snapshot hashing per run | MOD-005, MOD-006 | - | Perf test: capture loop no longer recomputes policy hash per segment; Test: policy hash stable for a run and changes when config changes |
| I101 | Phase 3: Storage scaling + durability | Add content_hash to metadata for every media put | MOD-039 | - | Test: content_hash present and matches recomputed hash after decrypt |
| I102 | Phase 3: Storage scaling + durability | Track partial failures explicitly in journal/ledger | MOD-005, MOD-006, MOD-037 | ADR-009 | Test: injected failures produce explicit failure records |
| I103 | Phase 3: Storage scaling + durability | Add segment sealing ledger entry after successful write | MOD-005, MOD-006, MOD-008 | ADR-009 | Test: sealed only after media+metadata committed and hashes known |
| I104 | Phase 3: Storage scaling + durability | Add startup recovery scanner to reconcile stores | MOD-039, MOD-037 | - | Crash simulation: partial writes detected and repaired/quarantined |
| I105 | Phase 2: Capture pipeline refactor | If keeping zips, use ZIP_STORED for JPEG frames | MOD-008, MOD-009, MOD-010 | ADR-005 | Perf: segment packing CPU drops vs deflate for JPEG frames |
| I106 | Phase 2: Capture pipeline refactor | If keeping zips, stream ZipFile writes to a real file | MOD-008, MOD-009, MOD-010 | ADR-005 | Perf: no large in-memory segment buffers; Test: zip is valid and contains expected files |
| I107 | Phase 2: Capture pipeline refactor | Batch input events to reduce write overhead | MOD-014 | - | Perf: input plugin reduces write rate under heavy input; Test: event ordering within batch preserved and timestamped |
| I108 | Phase 3: Storage scaling + durability | Add compact binary input log (derived) + JSON summary | MOD-039, MOD-014 | - | Test: binary log roundtrip decode; JSON summary matches counts/time range |
| I109 | Phase 2: Capture pipeline refactor | Add WASAPI loopback option for system audio capture | MOD-008, MOD-032, MOD-012 | - | Test: device enumeration deterministic; loopback selection works on CI mocks |
| I110 | Phase 2: Capture pipeline refactor | Store audio as PCM/FLAC/Opus derived artifact | MOD-008, MOD-012, MOD-009 | - | Test: audio roundtrip decode yields expected sample count |
| I111 | Phase 2: Capture pipeline refactor | Normalize active window process paths (device → drive paths) | MOD-013 | - | Test: device path conversion deterministic given known mappings |
| I112 | Phase 2: Capture pipeline refactor | Capture window.rect and monitor mapping | MOD-013, MOD-008, MOD-012 | - | Test: rect fields present and valid; monitor id matches layout snapshot |
| I113 | Phase 2: Capture pipeline refactor | Optional cursor position+shape capture | MOD-008, MOD-009, MOD-010 | - | Test: cursor capture disabled by default; when enabled, schema valid; Security: ensure cursor capture does not leak privileged info beyond local store |
| I114 | Phase 8: Optional expansion plugins | Clipboard capture plugin (local-only, append-only) | MOD-002, MOD-031, MOD-007 | ADR-002 | Test: disabled by default; when enabled, records are append-only and ledgered; Security: redaction policy for sensitive clipboard types (optional) is explicit |
| I115 | Phase 8: Optional expansion plugins | File activity capture plugin (USN journal / watcher) | MOD-006, MOD-005, MOD-002 | ADR-009, ADR-002 | Test: disabled by default; when enabled, events are time-ordered and searchable |
| I116 | Phase 5: Scheduler/governor | Model execution budgets per idle window | MOD-015, MOD-013, MOD-014 | - | Test: budgets enforced; jobs stop/continue across idle windows without violating budget |
| I117 | Phase 5: Scheduler/governor | Preemption/chunking for long jobs | MOD-015 | - | Test: job can be paused/resumed without redoing completed work |
| I118 | Phase 4: Retrieval + provenance + citations | Index versioning for retrieval reproducibility | MOD-023, MOD-037 | - | Test: query includes index version refs; rebuild increments version |
| I119 | Phase 6: Security + egress hardening | Persist entity-tokenizer key id/version; version tokenization | MOD-004, MOD-016 | - | Test: tokenization output is stable under same key id; rotation yields new version |
| I120 | Phase 6: Security + egress hardening | Ledger sanitized egress packets (hash + schema version) | MOD-002, MOD-028, MOD-006 | ADR-008, ADR-009 | Test: egress attempt emits `egress.packet` ledger entry with hash + schema version |
| I121 | Phase 7: FastAPI UX facade + Web Console | Egress approval workflow in UI | MOD-032, MOD-033, MOD-028 | ADR-008 | Test: egress blocked without approval; approved egress logs approval id + packet hash (I120) |
| I122 | Phase 8: Optional expansion plugins | Plugin hot-reload with hash verification and safe swap | MOD-002, MOD-031 | ADR-002 | Test: hot-reload updates plugin only if lockfile updated and verified; Test: in-flight jobs are drained/cancelled safely on reload |
| I123 | Phase 1: Correctness + immutability blockers | Write kernel boot ledger entry system.start | MOD-005, MOD-006, MOD-001 | ADR-009 | Golden ledger test includes start entry; Doctor verifies presence of start entry for completed runs |
| I124 | Phase 1: Correctness + immutability blockers | Write kernel shutdown ledger entry system.stop | MOD-005, MOD-006, MOD-001 | ADR-009 | Test: graceful shutdown emits stop entry |
| I125 | Phase 1: Correctness + immutability blockers | Write crash ledger entry on next startup | MOD-005, MOD-006 | ADR-009 | Test: simulate crash (no stop) then restart emits crash entry |
| I126 | Phase 0: Scaffolding and gates | Make sha256_directory path sorting deterministic across OSes | MOD-002 | - | Test: same directory hashed on Windows/Linux yields identical digest; Gate: plugin lock update is deterministic on same content |
| I127 | Phase 4: Retrieval + provenance + citations | Record python/OS/package versions into run manifest | MOD-008, MOD-012, MOD-002 | - | Test: manifest contains python version, OS build, package versions list |
| I128 | Phase 3: Storage scaling + durability | Tooling to migrate data_dir safely (copy+verify, no delete) | MOD-039, MOD-040 | ADR-007 | Test: migrate copies all evidence and manifests; verification passes |
| I129 | Phase 3: Storage scaling + durability | Disk usage forecasting (days remaining) + alerts | MOD-039 | - | Test: forecasting produces deterministic output for fixed input series |
| I130 | Phase 3: Storage scaling + durability | Storage compaction for derived artifacts only | MOD-039 | - | Gate-IMMUT: compaction never touches primary evidence; Test: compaction reduces size; citations still resolve |

# 2. Functional Modules & Logic

* Object_ID: MOD-001
  Object_Name: NX Kernel Boot & Effective Config Builder
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Boot the Prime system by loading default config, applying user overrides, enforcing safe mode and pinned contracts, and producing a System container composed from plugins.
  Sources: [SRC-007, SRC-028, SRC-030, SRC-040, SRC-043, SRC-058]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict, Optional

  @dataclass(frozen=True)
  class KernelBootArgs:
      safe_mode: bool
      config_default_path: str  # default: "config/default.json"
      config_user_path: str     # default: "config/user.json"

  @dataclass(frozen=True)
  class EffectiveConfig:
      data: Dict[str, Any]
      schema_hash: str          # sha256 of contracts/config_schema.json
      effective_hash: str       # sha256(canonical_json(data))

  class Kernel:
      def __init__(self, args: KernelBootArgs) -> None: ...
      def boot(self) -> "System": ...
      def load_effective_config(self) -> EffectiveConfig: ...
      def validate_config(self, cfg: Dict[str, Any]) -> None: ...
  ```
* Object_ID: MOD-002
  Object_Name: NX Plugin Registry, Allowlist, Hash Locks, Safe Mode Loader
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Discover plugin manifests, enforce allowlisting + artifact hash locks, enforce network permission limits, and load plugins into the kernel capability graph; safe mode restricts to default pack only.
  Sources: [SRC-011, SRC-030, SRC-033, SRC-034, SRC-035, SRC-043, SRC-044]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict, List, Optional, Protocol, Tuple

  @dataclass(frozen=True)
  class PluginEntrypoint:
      kind: str          # e.g. "capture.source", "storage.metadata", "retrieval.engine"
      id: str            # unique within plugin_id
      path: str          # python import root
      callable: str      # attribute name to import

  @dataclass(frozen=True)
  class PluginPermissions:
      filesystem: str    # "none"|"read"|"read_write"
      gpu: bool
      raw_input: bool
      network: bool

  @dataclass(frozen=True)
  class PluginCompat:
      requires_kernel: str
      requires_schema_versions: List[int]

  @dataclass(frozen=True)
  class PluginHashLock:
      manifest_sha256: str
      artifact_sha256: str

  @dataclass(frozen=True)
  class PluginManifest:
      plugin_id: str
      version: str
      enabled: bool
      entrypoints: List[PluginEntrypoint]
      permissions: PluginPermissions
      compat: PluginCompat
      depends_on: List[str]
      hash_lock: PluginHashLock

  class Plugin(Protocol):
      def activate(self, ctx: "PluginContext") -> None: ...

  class PluginRegistry:
      def discover_manifests(self) -> List[PluginManifest]: ...
      def validate_allowlist_and_hashes(self, manifests: List[PluginManifest]) -> None: ...
      def load_enabled(self, manifests: List[PluginManifest], *, safe_mode: bool) -> List[Plugin]: ...
      def register_capabilities(self, plugins: List[Plugin], system: "System") -> None: ...
  ```
* Object_ID: MOD-003
  Object_Name: Capability Broker and System Container
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Provide a typed, named registry of system capabilities (e.g., storage, capture, retrieval, egress, logging) built from plugins and used by all layers (CLI, API, workers).
  Sources: [SRC-007, SRC-040, SRC-041]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict, Optional

  @dataclass
  class System:
      config: Dict[str, Any]
      def get(self, capability_name: str) -> Any: ...
      def has(self, capability_name: str) -> bool: ...
      def register(self, capability_name: str, value: Any) -> None: ...
  ```
* Object_ID: MOD-004
  Object_Name: Keyring, Key Derivation, and Key Rotation (Ledger + Anchor)
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Manage root keys (DPAPI-protected on Windows), derive separated keys for metadata/media/entity tokens, rotate keys, rewrap stores, and record rotation in ledger + anchor.
  Sources: [SRC-036, SRC-038, SRC-039, SRC-041]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict, Tuple

  @dataclass
  class KeyringStatus:
      active_key_id: str
      keyring_path: str

  class Keyring:
      @property
      def active_key_id(self) -> str: ...
      def active_key(self) -> Tuple[str, bytes]: ...
      def rotate(self) -> str: ...

  def derive_key(root_key: bytes, purpose: str) -> bytes: ...

  def rotate_keys(system: "System") -> Dict[str, Any]:
      """
      Returns:
        {
          "old_key_id": str,
          "new_key_id": str,
          "rotated": {"metadata": Any, "media": Any, "entity_map": Any},
          "ledger_hash": str
        }
      """
      ...
  ```
* Object_ID: MOD-005
  Object_Name: Journal Writer (Append-Only JSONL + Schema)
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Record append-only event stream for local observability/audit, validated against pinned journal schema.
  Sources: [SRC-038, SRC-045]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict

  @dataclass(frozen=True)
  class JournalEvent:
      schema_version: int
      event_id: str
      sequence: int
      ts_utc: str
      tzid: str
      offset_minutes: int
      event_type: str
      payload: Dict[str, Any]

  class JournalWriter:
      def append(self, event: Dict[str, Any]) -> None: ...
      def append_typed(self, event: JournalEvent) -> None: ...
  ```
* Object_ID: MOD-006
  Object_Name: Ledger Writer (Hash-Chained Canonical JSON) + Anchor Store
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Provide an immutable, hash-chained ledger of key stages (security, retrieval, answering, egress) and record head hashes via an anchor writer.
  Sources: [SRC-038, SRC-039, SRC-046]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict, List, Optional

  @dataclass(frozen=True)
  class LedgerEntryV1:
      schema_version: int
      entry_id: str
      ts_utc: str
      stage: str
      inputs: List[str]
      outputs: List[str]
      policy_snapshot_hash: str
      payload: Dict[str, Any]
      prev_hash: Optional[str]
      entry_hash: str

  class LedgerWriter:
      def append(self, entry_without_hashes: Dict[str, Any]) -> str: ...
      def head_hash(self) -> Optional[str]: ...

  class AnchorWriter:
      def anchor(self, ledger_head_hash: str) -> None: ...
  ```
* Object_ID: MOD-007
  Object_Name: Prime MX App Orchestrator + CLI Commands
  Object_Type: CLI
  Priority: MUST
  Primary_Purpose: Implement the pinned `autocapture` CLI surface; orchestrate system boot, doctor, config management, plugin approvals, run pipelines, local query with retrieval + citations, devtools, key rotation.
  Sources: [SRC-001, SRC-002, SRC-003, SRC-040, SRC-041, SRC-042]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from typing import Any, Dict, Optional

  def cmd_doctor(args: Any) -> int: ...
  def cmd_config_show(args: Any) -> int: ...
  def cmd_config_reset(args: Any) -> int: ...
  def cmd_config_restore(args: Any) -> int: ...
  def cmd_plugins_list(args: Any) -> int: ...
  def cmd_plugins_approve(args: Any) -> int: ...
  def cmd_run(args: Any) -> int: ...
  def cmd_query(args: Any) -> int: ...
  def cmd_devtools_diffusion(args: Any) -> int: ...
  def cmd_devtools_ast_ir(args: Any) -> int: ...
  def cmd_keys_rotate(args: Any) -> int: ...
  ```
* Object_ID: MOD-008
  Object_Name: Capture Pipeline Orchestrator (Screen + Audio + Metadata + Segmenting)
  Object_Type: Background Worker
  Priority: MUST
  Primary_Purpose: Provide Autocapture-parity capture orchestration in Prime: multi-backend selection, dedupe, FFmpeg segment recording, and enrichment (app/title/url/domain), while aligning to Prime decision to not apply local privacy sanitization/exclusion.
  Sources: [SRC-008, SRC-020, SRC-028, SRC-031, SRC-051, SRC-058]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict, Iterator, List, Optional, Tuple

  @dataclass(frozen=True)
  class CaptureFrame:
      frame_id: str
      created_at_utc: str
      monotonic_ts: float
      monitor_id: str
      monitor_bounds: Tuple[int, int, int, int]  # x,y,w,h
      app_name: Optional[str]
      window_title: Optional[str]
      url: Optional[str]
      domain: Optional[str]
      image_ref: str          # blob ref or path
      frame_hash: str
      phash: Optional[str]
      privacy_flags: Dict[str, Any]  # see MOD-016; D1 means no local masking/exclusion

  class CapturePipeline:
      def start(self) -> None: ...
      def stop(self) -> None: ...
      def run_forever(self) -> None: ...
      def capture_tick(self) -> Optional[CaptureFrame]: ...
      def on_frame(self, frame: CaptureFrame) -> None: ...
  ```
* Object_ID: MOD-009
  Object_Name: Screen Capture Backend DXCAM (Primary)
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Provide high-performance Windows screen capture backend with fallback selection logic.
  Sources: [SRC-051, SRC-020]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from typing import Any, Optional

  class ScreenCaptureBackend:
      def start(self) -> None: ...
      def stop(self) -> None: ...
      def grab(self) -> Optional[Any]: ...  # returns frame image object/bytes per implementation

  class DXCAMBackend(ScreenCaptureBackend):
      ...
  ```
* Object_ID: MOD-010
  Object_Name: Screen Capture Backend MSS (Fallback)
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Provide fallback Windows screen capture backend for environments where DXCAM is unavailable/unreliable.
  Sources: [SRC-051, SRC-020]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from typing import Any, Optional

  class MSSBackend(ScreenCaptureBackend):
      ...
  ```
* Object_ID: MOD-011
  Object_Name: Duplicate Detector (Frame Hash + pHash + Dedupe Grouping)
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Reduce storage/CPU by detecting duplicate/near-duplicate frames and emitting dedupe_group_id used by retrieval and answer evidence.
  Sources: [SRC-020, SRC-050]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Optional

  @dataclass(frozen=True)
  class DedupeDecision:
      is_duplicate: bool
      dedupe_group_id: Optional[str]
      reason: str  # e.g. "exact_hash", "phash_threshold", "time_window"

  class DuplicateDetector:
      def __init__(self, *, phash_threshold: int, exact_hash_window_ms: int) -> None: ...
      def decide(self, frame_hash: str, phash: Optional[str], monotonic_ts: float) -> DedupeDecision: ...
  ```
* Object_ID: MOD-012
  Object_Name: Segment Recorder (FFmpeg, NVENC Optional) + Segment Manifest
  Object_Type: Background Worker
  Priority: MUST
  Primary_Purpose: Record continuous video segments (default segment_seconds=60) with deterministic manifests, aligning Prime config defaults and Autocapture FFmpeg segmenting parity.
  Sources: [SRC-020, SRC-058]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict, Optional

  @dataclass(frozen=True)
  class SegmentRecord:
      segment_id: str
      ts_start_utc: str
      ts_end_utc: str
      duration_s: float
      codec: str
      path_or_blob_ref: str
      sha256: str
      keyframes: int
      frames: int

  class SegmentRecorder:
      def start(self) -> None: ...
      def stop(self) -> None: ...
      def write_frame(self, frame_bytes: bytes, *, ts_utc: str) -> None: ...
      def finalize_segment(self) -> SegmentRecord: ...
  ```
* Object_ID: MOD-013
  Object_Name: Foreground Context Tracker (App/Title/URL/Domain)
  Object_Type: Background Worker
  Priority: MUST
  Primary_Purpose: Track foreground window transitions and enrich capture frames/events with app name, window title, URL/domain when available.
  Sources: [SRC-021, SRC-020]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Optional

  @dataclass(frozen=True)
  class ForegroundContext:
      ts_utc: str
      app_name: Optional[str]
      window_title: Optional[str]
      url: Optional[str]
      domain: Optional[str]
      hwnd: Optional[int]

  class ForegroundTracker:
      def start(self) -> None: ...
      def stop(self) -> None: ...
      def current(self) -> ForegroundContext: ...
  ```
* Object_ID: MOD-014
  Object_Name: Raw Input Listener + Idle Gate
  Object_Type: Background Worker
  Priority: MUST
  Primary_Purpose: Provide input/idle gating signals to runtime governor and capture pipelines; MUST avoid collecting sensitive keystroke content.
  Sources: [SRC-021, SRC-020]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass

  @dataclass(frozen=True)
  class InputState:
      ts_utc: str
      idle_seconds: float
      last_input_monotonic_ts: float
      is_idle: bool

  class RawInputListener:
      def start(self) -> None: ...
      def stop(self) -> None: ...
      def get_state(self) -> InputState: ...
  ```
* Object_ID: MOD-015
  Object_Name: Runtime Governor (Modes + Pause Latch Semantics)
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Select runtime mode (FULLSCREEN_HARD_PAUSE, ACTIVE_INTERACTIVE, IDLE_DRAIN) based on fullscreen detection and input idle; enforce deterministic transitions and allow capture/worker throttling consistent with Autocapture runtime gates.
  Sources: [SRC-054, SRC-021]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Literal, Optional

  RuntimeMode = Literal["FULLSCREEN_HARD_PAUSE", "ACTIVE_INTERACTIVE", "IDLE_DRAIN"]

  @dataclass(frozen=True)
  class RuntimeModeTransition:
      mode: RuntimeMode
      reason: str
      since_ts_utc: str

  class RuntimeGovernor:
      def __init__(self, *, idle_threshold_seconds: float, fullscreen_pause: bool) -> None: ...
      def update(self, *, is_fullscreen: bool, idle_seconds: float, ts_utc: str) -> RuntimeModeTransition: ...
      def current_mode(self) -> RuntimeModeTransition: ...
  ```
* Object_ID: MOD-016
  Object_Name: Privacy Policy Evaluator and Local Sensitivity Tagging
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Implement privacy allow/deny logic from Autocapture as “tagging” (not local masking/exclusion) and enforce egress/UI behavior via policy; reconcile Autocapture skip-capture behavior with Prime D1.
  Sources: [SRC-031, SRC-055, SRC-028, SRC-026]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Dict, Optional, Tuple

  @dataclass(frozen=True)
  class PrivacyDecision:
      local_capture_allowed: bool        # always True under D1 unless user explicitly pauses capture
      local_processing_allowed: bool     # True under D1; may be throttled, not filtered
      egress_allowed: bool               # default False unless sanitized
      ui_visible: bool                   # default True locally; can be hidden by user filters
      flags: Dict[str, bool]             # e.g. {"matches_deny_process": True, ...}
      reason: str

  class PrivacyPolicy:
      def decide(self, *, app_name: Optional[str], window_title: Optional[str], url: Optional[str], domain: Optional[str]) -> PrivacyDecision: ...
  ```
* Object_ID: MOD-017
  Object_Name: OCR Extractor (Local) Producing OCRSpan and Normalized Index Text
  Object_Type: Background Worker
  Priority: MUST
  Primary_Purpose: Extract OCR text + spans as canonical citation units; enforce immutability for raw OCR and spans; write spans to spans store and normalized text to indexes.
  Sources: [SRC-023, SRC-049, SRC-050]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import List, Optional, Tuple

  @dataclass(frozen=True)
  class OCRSpan:
      span_id: str
      start_offset: int
      end_offset: int
      bbox_px: Tuple[int, int, int, int]  # x0,y0,x1,y1
      conf: float
      text: str
      engine: str
      frame_id: str
      frame_hash: str

  @dataclass(frozen=True)
  class OCRDocument:
      frame_id: str
      frame_hash: str
      raw_text: str
      spans: List[OCRSpan]

  class OcrExtractor:
      def extract(self, *, frame_id: str, frame_hash: str, image_bytes: bytes) -> OCRDocument: ...
  ```
* Object_ID: MOD-018
  Object_Name: VLM Extractor (Local) for Structured Screen Understanding
  Object_Type: Background Worker
  Priority: MUST
  Primary_Purpose: Provide VLM-based extraction pathway (enabled, not stubbed) for higher-fidelity understanding; integrate with citation provenance by linking outputs to frame_id/frame_hash and/or spans.
  Sources: [SRC-023, SRC-020, SRC-050]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict, Optional

  @dataclass(frozen=True)
  class VlmExtraction:
      frame_id: str
      frame_hash: str
      model_id: str
      outputs: Dict[str, Any]   # structured output (e.g. entities, UI elements, summary)
      confidence: Optional[float]

  class VlmExtractor:
      def extract(self, *, frame_id: str, frame_hash: str, image_bytes: bytes, prompt: str) -> VlmExtraction: ...
  ```
* Object_ID: MOD-019
  Object_Name: Embedding Service (Fastembed + SentenceTransformer Fallback)
  Object_Type: Background Worker
  Priority: MUST
  Primary_Purpose: Generate dense embeddings for text (and optionally image-derived text) to support vector indexing and hybrid retrieval, matching Autocapture behavior.
  Sources: [SRC-023, SRC-056]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import List, Sequence

  @dataclass(frozen=True)
  class EmbeddingResult:
      model_name: str
      dim: int
      vectors: List[List[float]]

  class Embedder:
      def embed_texts(self, texts: Sequence[str]) -> EmbeddingResult: ...
  ```
* Object_ID: MOD-020
  Object_Name: Vector Index Adapter (Local Default, Qdrant Optional)
  Object_Type: Data Store
  Priority: MUST
  Primary_Purpose: Provide vector indexing/search; default local single-machine store; optionally enable Qdrant as opt-in backend.
  Sources: [SRC-015, SRC-023, SRC-057]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Dict, List, Optional, Sequence, Tuple

  @dataclass(frozen=True)
  class VectorPoint:
      point_id: str
      vector: List[float]
      payload: Dict[str, str]  # minimally: frame_id/event_id/span_id
      ts_utc: str

  @dataclass(frozen=True)
  class VectorHit:
      point_id: str
      score: float
      payload: Dict[str, str]

  class VectorIndex:
      def upsert(self, points: Sequence[VectorPoint]) -> None: ...
      def search(self, vector: List[float], *, k: int, filters: Optional[Dict[str, str]] = None) -> List[VectorHit]: ...
      def health(self) -> Dict[str, str]: ...
  ```
* Object_ID: MOD-021
  Object_Name: Lexical Index (SQLite FTS5 + Deterministic Fallback)
  Object_Type: Data Store
  Priority: MUST
  Primary_Purpose: Provide lexical search over normalized OCR/VLM text and metadata; include deterministic fallback if FTS5 unavailable.
  Sources: [SRC-015, SRC-023, SRC-050]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Dict, List, Optional

  @dataclass(frozen=True)
  class LexicalHit:
      doc_id: str          # e.g. frame_id or span_id
      score: float
      snippet: str
      snippet_offset: Optional[int]
      payload: Dict[str, str]

  class LexicalIndex:
      def upsert_document(self, *, doc_id: str, text: str, payload: Dict[str, str]) -> None: ...
      def search(self, query: str, *, k: int, filters: Optional[Dict[str, str]] = None) -> List[LexicalHit]: ...
      def health(self) -> Dict[str, str]: ...
  ```
* Object_ID: MOD-022
  Object_Name: Spans Store (Citable Spans, BBoxes, Provenance)
  Object_Type: Data Store
  Priority: MUST
  Primary_Purpose: Persist immutable OCR spans (and other citable spans) and provide lookup by span_id, frame_id, and event_id; support overlay rendering and provenance validation.
  Sources: [SRC-049, SRC-050]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from typing import List, Optional

  class SpansStore:
      def put_ocr_document(self, doc: "OCRDocument") -> None: ...
      def get_span(self, span_id: str) -> Optional["OCRSpan"]: ...
      def list_spans_for_frame(self, frame_id: str) -> List["OCRSpan"]: ...
  ```
* Object_ID: MOD-023
  Object_Name: Hybrid Retrieval Engine (Time Intent + Filters + Fusion + Rerank)
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Provide Autocapture-quality retrieval: parse time intent, apply filters (app/title/domain), do lexical + vector search, fuse results, optional rerank, and emit RetrievalResult with citable/non-citable flags and score breakdown.
  Sources: [SRC-010, SRC-023, SRC-050, SRC-053]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Dict, List, Optional, Tuple

  @dataclass(frozen=True)
  class ScoreBreakdown:
      lexical: Optional[float]
      dense: Optional[float]
      sparse: Optional[float]
      late_interaction: Optional[float]
      rerank: Optional[float]

  @dataclass(frozen=True)
  class RetrievalResult:
      event_id: str
      frame_id: str
      span_id: Optional[str]
      snippet: str
      snippet_offset: Optional[int]
      bbox_px: Optional[Tuple[int, int, int, int]]
      non_citable: bool
      dedupe_group_id: Optional[str]
      score: float
      scores: ScoreBreakdown

  class RetrievalEngine:
      def retrieve(
          self,
          *,
          query: str,
          time_window: Optional[Tuple[str, str]],
          filters: Dict[str, str],
          k: int
      ) -> List[RetrievalResult]: ...
  ```
* Object_ID: MOD-024
  Object_Name: Answer Builder + Validators (No-Evidence, Provenance, Entailment, Conflict, Integrity)
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Build grounded answers from retrieval evidence with claim-level citations; enforce “no evidence → no claim”; validate citations resolve to stored artifacts; detect contradictions and entailment issues.
  Sources: [SRC-024, SRC-010, SRC-050]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Dict, List, Optional

  @dataclass(frozen=True)
  class EvidenceItem:
      id: str                  # "E1", "E2", ...
      ts_start: str
      ts_end: Optional[str]
      source: str
      title: str
      text: str
      meta: Dict[str, object]  # includes event_id, domain, score, screenshot_path/hash, spans

  @dataclass(frozen=True)
  class Claim:
      text: str
      citations: List[str]     # evidence IDs, e.g., ["E1","E4"]

  @dataclass(frozen=True)
  class Answer:
      query: str
      claims: List[Claim]
      evidence: List[EvidenceItem]
      warnings: List[str]

  class AnswerBuilder:
      def build(self, *, query: str, retrieval: List["RetrievalResult"]) -> Answer: ...

  class ClaimValidators:
      def validate_no_evidence(self, answer: Answer) -> None: ...
      def validate_provenance(self, answer: Answer) -> None: ...
      def validate_entailment(self, answer: Answer) -> None: ...
      def validate_conflict(self, answer: Answer) -> None: ...
      def validate_integrity(self, answer: Answer) -> None: ...
  ```
* Object_ID: MOD-025
  Object_Name: Citation Renderer + Overlay Evidence API
  Object_Type: API Endpoint
  Priority: MUST
  Primary_Purpose: Provide evidence/citation rendering for UI and overlays; expose citation overlay endpoint and map evidence IDs to screenshot hashes/spans.
  Sources: [SRC-014, SRC-024, SRC-049]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import List, Optional, Tuple

  @dataclass(frozen=True)
  class CitationOverlayItem:
      evidence_id: str
      frame_id: str
      span_id: Optional[str]
      bbox_px: Optional[Tuple[int, int, int, int]]
      label: str
      score: float

  class CitationOverlayService:
      def list_overlay_items(self, *, run_id: str) -> List[CitationOverlayItem]: ...
  ```
* Object_ID: MOD-026
  Object_Name: Deterministic Time Intent Parser (Basic + Advanced)
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Parse natural language time intent deterministically for query/retrieval, producing a window and assumptions, conforming to pinned schema.
  Sources: [SRC-059, SRC-041]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import List, Optional, Tuple

  @dataclass(frozen=True)
  class TimeWindow:
      start: str  # ISO
      end: str    # ISO

  @dataclass(frozen=True)
  class TimeIntentResult:
      query: str
      time_window: Optional[TimeWindow]
      tz: str
      assumptions: List[str]

  class TimeIntentParser:
      def parse(self, *, query: str, tz: str, now_utc: str) -> TimeIntentResult: ...
  ```
* Object_ID: MOD-027
  Object_Name: Gateway Stage Router + LLM Client (Local/Cloud via Policy)
  Object_Type: API Endpoint
  Priority: MUST
  Primary_Purpose: Implement Autocapture-style “Gateway” stage routing (refine, draft, final, tool transforms), integrating with policy for allow_cloud and internal tokens, while staying deny-by-default for network except through egress gateway.
  Sources: [SRC-016, SRC-019, SRC-030, SRC-034]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict, Optional

  @dataclass(frozen=True)
  class ModelStage:
      stage_id: str
      provider: str
      model: str
      base_url: Optional[str]
      allow_cloud: bool
      max_concurrency: int

  class StageRouter:
      def route(self, stage_id: str) -> ModelStage: ...

  class LlmClient:
      def complete(self, *, stage: ModelStage, prompt: str, **kwargs: Any) -> Dict[str, Any]: ...
  ```
* Object_ID: MOD-028
  Object_Name: Egress Gateway + Sanitizer (ReasoningPacketV1)
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Build sanitized outbound payloads (Reasoning Packet v1) using typed tokens and a glossary; enforce leak checks; block egress when checks fail; only this module may request network.
  Sources: [SRC-028, SRC-033, SRC-034, SRC-036, SRC-037, SRC-047]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict, List, Optional, Tuple

  @dataclass(frozen=True)
  class SanitizationResult:
      sanitized_text: str
      glossary: Dict[str, str]        # token -> plaintext (stored locally only)
      entities: List[Dict[str, Any]]  # entity metadata
      leak_detected: bool
      leak_reasons: List[str]

  class EgressSanitizer:
      def sanitize(self, text: str) -> SanitizationResult: ...

  @dataclass(frozen=True)
  class ReasoningPacketV1:
      version: int
      query: str
      time_window: Optional[Dict[str, str]]
      sanitized_context: str
      citations: List[Dict[str, Any]]
      glossary: Dict[str, str]
      metadata: Dict[str, Any]

  class EgressGateway:
      def build_packet(self, *, query: str, answer: "Answer", time_intent: "TimeIntentResult") -> ReasoningPacketV1: ...
      def send(self, packet: ReasoningPacketV1) -> Dict[str, Any]: ...  # may raise on leak or policy violation
  ```
* Object_ID: MOD-029
  Object_Name: Memory Service (Local Store + API)
  Object_Type: API Endpoint
  Priority: MUST
  Primary_Purpose: Provide memory snapshot generation and optional “memory hotness” ranking used by context packs; maintain deterministic memory view and manifest.
  Sources: [SRC-016, SRC-053]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict, Optional

  @dataclass(frozen=True)
  class MemorySnapshot:
      snapshot_id: str
      generated_at: str
      payload: Dict[str, Any]
      manifest: Dict[str, Any]

  class MemoryService:
      def build_snapshot(self, *, mode: str, as_of_utc: Optional[str]) -> MemorySnapshot: ...
  ```
* Object_ID: MOD-030
  Object_Name: Exporter/Importer (Autocapture-Compatible ZIP + Roundtrip)
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Export local capture/evidence into a ZIP bundle containing events.jsonl, manifest.json, settings.json, and redacted config.json; import must roundtrip deterministically.
  Sources: [SRC-009, SRC-018, SRC-052]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict, Optional

  @dataclass(frozen=True)
  class ExportOptions:
      start_utc: Optional[str]
      end_utc: Optional[str]
      include_media: bool
      decrypt_media: bool
      output_path: str

  @dataclass(frozen=True)
  class ExportResult:
      zip_path: str
      manifest_path_in_zip: str
      events_count: int
      media_files_count: int

  class ExportService:
      def export_zip(self, opts: ExportOptions) -> ExportResult: ...

  class ImportService:
      def import_zip(self, zip_path: str) -> Dict[str, Any]: ...
  ```
* Object_ID: MOD-031
  Object_Name: MX Plugin Manager (Discovery + Policy + Settings + Enable/Disable)
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Provide Autocapture-style plugin discovery/policy/settings surfaces atop Prime’s plugin system; enable/disable plugins and validate hashes/allowlist and dependency graph.
  Sources: [SRC-011, SRC-043, SRC-044]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict, List, Optional

  @dataclass(frozen=True)
  class PluginStatus:
      plugin_id: str
      enabled: bool
      allowlisted: bool
      hash_ok: bool
      version: str
      permissions: Dict[str, Any]
      depends_on: List[str]

  class PluginManager:
      def list_plugins(self) -> List[PluginStatus]: ...
      def enable(self, plugin_id: str) -> None: ...
      def disable(self, plugin_id: str) -> None: ...
      def approve_hashes(self) -> Dict[str, Any]: ...
  ```
* Object_ID: MOD-032
  Object_Name: FastAPI Server (Core + Events + UX + Plugins + Storage + Query)
  Object_Type: API Endpoint
  Priority: MUST
  Primary_Purpose: Implement full API parity: core routes, ingest routes, UX routes, middleware (auth/rate-limit/security headers/session), plugin routes, storage stats, query + context-pack, citations overlay.
  Sources: [SRC-012, SRC-025, SRC-053]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from typing import Any, Dict, Optional
  from fastapi import FastAPI

  def create_app(system: "System") -> FastAPI: ...

  # Required route contracts (minimum)
  # GET  /healthz
  # GET  /readyz
  # GET  /api/state
  # POST /api/events/ingest
  # POST /api/query
  # POST /api/context-pack
  # GET  /api/plugins
  # POST /api/plugins/enable/{plugin_id}
  # POST /api/plugins/disable/{plugin_id}
  # GET  /api/storage
  # POST /api/citations/overlay
  ```
* Object_ID: MOD-033
  Object_Name: UI/UX Layer (Web UI + UX Facade)
  Object_Type: Other
  Priority: MUST
  Primary_Purpose: Provide user-facing UX parity for exploring captures, searching, viewing evidence + citations, managing plugins and configuration, and showing system status.
  Sources: [SRC-013, SRC-025]
  Interface_Definition:

  ```text
  UX Facade Responsibilities:
    - Render timeline/explorer views using /api/query and /api/context-pack
    - Provide plugin enable/disable UI backed by /api/plugins/*
    - Provide storage stats, system state, and doctor diagnostics output
    - Provide citation overlay toggles and deep-linking to evidence
  Static Assets:
    - Serve under /ui/* (or /static/*) from packaged assets directory
  ```
* Object_ID: MOD-034
  Object_Name: Overlay Tracker + Citation Overlay Rendering
  Object_Type: Other
  Priority: MUST
  Primary_Purpose: Implement overlay tracker subsystem to display on-screen overlays for citations and/or active capture context, integrating with citation overlay API.
  Sources: [SRC-014, SRC-025]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import List, Optional, Tuple

  @dataclass(frozen=True)
  class OverlayRect:
      x0: int
      y0: int
      x1: int
      y1: int

  @dataclass(frozen=True)
  class OverlayLabel:
      text: str
      confidence: float

  class OverlayTracker:
      def start(self) -> None: ...
      def stop(self) -> None: ...
      def render(self, items: List["CitationOverlayItem"]) -> None: ...
  ```
* Object_ID: MOD-035
  Object_Name: Doctor & Diagnostics (Full Parity)
  Object_Type: CLI
  Priority: MUST
  Primary_Purpose: Provide doctor checks covering DB/encryption/qdrant/ffmpeg/capture backends/OCR/embeddings/vector index/LLM/API/metrics/raw input; fail non-zero on invariant failure.
  Sources: [SRC-027, SRC-059, SRC-042]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Dict, List, Literal, Optional

  Severity = Literal["OK", "WARN", "FAIL"]

  @dataclass(frozen=True)
  class DoctorCheckResult:
      name: str
      severity: Severity
      details: str
      metadata: Dict[str, str]

  class DoctorService:
      def run(self, *, verbose: bool) -> List[DoctorCheckResult]: ...
      def summarize_exit_code(self, results: List[DoctorCheckResult]) -> int: ...  # 0/1/2 per user_surface
  ```
* Object_ID: MOD-036
  Object_Name: Observability (Redacted JSONL Logs + Metrics)
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Extend beyond JSONL logs to provide metrics parity and health endpoints while ensuring no PII leakage and policy-aware redaction.
  Sources: [SRC-027, SRC-059]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from typing import Any, Dict, Optional

  class Logger:
      def info(self, msg: str, **fields: Any) -> None: ...
      def warn(self, msg: str, **fields: Any) -> None: ...
      def error(self, msg: str, **fields: Any) -> None: ...

  class Metrics:
      def inc(self, name: str, value: int = 1, **labels: str) -> None: ...
      def observe_ms(self, name: str, ms: float, **labels: str) -> None: ...
      def render_prometheus(self) -> str: ...
  ```
* Object_ID: MOD-037
  Object_Name: Evaluation Harness + CI Gates (Retrieval, PromptOps, No-Evidence)
  Object_Type: CLI
  Priority: MUST
  Primary_Purpose: Implement Autocapture parity evals (golden queries, retrieval cases, promptops AB) and CI gates that block shipping on regressions in grounding, evidence, privacy leakage, and integrity.
  Sources: [SRC-002, SRC-024]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict, List, Optional

  @dataclass(frozen=True)
  class EvalCase:
      id: str
      query: str
      expected_evidence_ids: Optional[List[str]]
      expected_no_evidence: Optional[bool]

  @dataclass(frozen=True)
  class EvalMetrics:
      recall_at_k: float
      mrr: float
      no_evidence_accuracy: float

  class EvalRunner:
      def run_retrieval_eval(self, cases: List[EvalCase]) -> EvalMetrics: ...
      def run_promptops_eval(self, cases: List[Dict[str, Any]]) -> Dict[str, Any]: ...

  class CiGate:
      def run_all(self) -> Dict[str, Any]: ...  # raises or returns FAIL on regression
  ```
* Object_ID: MOD-038
  Object_Name: Installer + Infra (Qdrant/Prometheus/Loki/Grafana + Windows Setup)
  Object_Type: Other
  Priority: MUST
  Primary_Purpose: Provide parity infra scaffolding and setup docs/scripts for local services (qdrant optional) and developer/operator setup on Windows.
  Sources: [SRC-017, SRC-057]
  Interface_Definition:

  ```text
  Infra Artifacts (must exist in-repo):
    - infra/compose.yaml: services for qdrant (optional), prometheus, loki, grafana (optional)
    - infra/prometheus.yml: scrape configs for local metrics endpoints
    - docs/windows_setup.md: model paths and optional ffmpeg guidance
  ```
* Object_ID: MOD-039
  Object_Name: Typed Storage + Migrations (Metadata, Indexes, Spans)
  Object_Type: Data Store
  Priority: MUST
  Primary_Purpose: Provide typed record storage with schema versions and migrations; enforce encryption-at-rest when required; support roundtrip export/import and deterministic backfills.
  Sources: [SRC-022, SRC-048, SRC-050]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict, List, Optional

  @dataclass(frozen=True)
  class MigrationResult:
      from_version: int
      to_version: int
      applied: List[str]

  class MetadataStore:
      schema_version: int
      def migrate(self, target_version: int) -> MigrationResult: ...
      def put_frame(self, frame: "CaptureFrame") -> None: ...
      def get_frame(self, frame_id: str) -> Optional[Dict[str, Any]]: ...
      def list_frames(self, *, start_utc: Optional[str], end_utc: Optional[str]) -> List[Dict[str, Any]]: ...
  ```
* Object_ID: MOD-040
  Object_Name: Retention, Deletion Semantics, and Archive (Tombstone-First)
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Provide Autocapture-like “delete preview/apply” semantics while respecting Prime decision that local evidence is not deleted; implement tombstoning/hiding and derived-cache cleanup; archive/export is user-driven.
  Sources: [SRC-022, SRC-032]
  Interface_Definition:

  ```python
  from __future__ import annotations
  from dataclasses import dataclass
  from typing import Any, Dict, List, Optional

  @dataclass(frozen=True)
  class DeletePreview:
      request_id: str
      affected_frames: int
      affected_segments: int
      affected_spans: int
      notes: List[str]

  class RetentionService:
      def preview(self, *, start_utc: str, end_utc: str, filters: Dict[str, str]) -> DeletePreview: ...
      def apply_tombstone(self, request_id: str) -> Dict[str, Any]: ...
      def cleanup_derived(self) -> Dict[str, Any]: ...
  ```

# 3. Architecture Decision Records (ADRs)

* ADR_ID: ADR-001
  Title: Prime is the successor vehicle implementing all Autocapture ideas with full parity
  Decision: Prime will implement all missing Autocapture subsystems and nuances (ideas, not code) with no stubs/TODOs and 100% functionality coverage, using this blueprint as the deterministic source for Codex CLI.
  Rationale: Prime snapshot lacks most Autocapture subsystems; user requires full parity and no stubs.
  Consequences:

  * Large implementation surface: API/UI/overlay/indexing/agents/export/infra must be built.
  * Requires strong contract pinning and CI gates to prevent regressions.
    Sources: [SRC-001, SRC-002, SRC-003, SRC-004, SRC-005, SRC-006]
* ADR_ID: ADR-002
  Title: Dual-layer plugin architecture (NX kernel plugins + MX app/plugin manager)
  Decision: Keep NX kernel plugin system (manifest + hash locks + allowlist) as the enforcement point, and implement an MX-level PluginManager for discovery/settings/enable-disable surfaces compatible with Autocapture workflows.
  Rationale: Prime already centers on `autocapture_nx` and lockfile enforcement, while Autocapture expects richer discovery and policy layers.
  Consequences:

  * Plugin IDs and entrypoints remain the authoritative capability graph.
  * UI and CLI can manage plugins without weakening kernel enforcement.
    Sources: [SRC-007, SRC-011, SRC-043, SRC-044]
* ADR_ID: ADR-003
  Title: Privacy posture reconciliation: local capture is unmodified; privacy is enforced at egress and UI surfaces
  Decision: Follow Prime D1 and non-negotiables: do not apply local privacy sanitization/exclusion; instead compute privacy “tags” and enforce egress sanitization (typed tokens + leak checks) and UI visibility controls; capture pause is only via explicit user/runtime governor, not privacy filtering.
  Rationale: Prime blueprint explicitly removes local sanitization/exclusion; Autocapture includes privacy skip-capture logic and masking; user wants privacy parity, which is implemented as tagging + egress enforcement.
  Consequences:

  * Local data remains full-fidelity; privacy safety depends on strict egress sanitizer and policy gate.
  * Autocapture privacy filters become query/UI/egress constraints rather than write-time deletion.
    Sources: [SRC-028, SRC-031, SRC-055, SRC-026]
* ADR_ID: ADR-004
  Title: Evidence-first answering with claim-level citations and strict provenance validation
  Decision: Replace minimal `answer_basic` behavior with an evidence-driven AnswerBuilder that enforces “no evidence → no claim”, validates citations resolve to stored artifacts (span/frame/segment), and runs contradiction/entailment/integrity checks.
  Rationale: Prime answering is minimal; user requires Autocapture-level evidence/citation model and validators.
  Consequences:

  * Retrieval must always produce citable units or mark results non_citable.
  * Answer output must include structured evidence list and warnings.
    Sources: [SRC-010, SRC-024, SRC-049, SRC-050]
* ADR_ID: ADR-005
  Title: Export/import format compatibility with Autocapture ZIP bundles
  Decision: Implement ZIP export/import with Autocapture-compatible bundle structure (events.jsonl, manifest.json, settings.json, redacted config.json) and roundtrip tests.
  Rationale: User requires parity; Autocapture export format is explicitly defined.
  Consequences:

  * Storage must support enumerating events and media references deterministically.
  * Import must avoid duplicate IDs and preserve provenance.
    Sources: [SRC-009, SRC-018, SRC-052]
* ADR_ID: ADR-006
  Title: Implement Gateway model as first-class Prime component
  Decision: Implement a Gateway StageRouter + LLM Client layer with stage routing and internal-token protections; integrate with policy (allow_cloud) and deny-by-default networking (network only via egress gateway).
  Rationale: Autocapture architecture includes Gateway model; gap map identifies missing parity.
  Consequences:

  * LLM access becomes staged and auditable via ledger/journal.
  * Any remote calls must be mediated via policy and sanitizer.
    Sources: [SRC-016, SRC-019, SRC-030, SRC-034]
* ADR_ID: ADR-007
  Title: Retention and deletion semantics are tombstone-first with no physical deletion of local evidence
  Decision: Implement delete preview/apply as tombstoning/hiding and derived-cache cleanup, not physical deletion of evidence; user-driven archive/export is the mechanism for lifecycle management.
  Rationale: Prime D7 removes deletion/retention; user still needs Autocapture-like UX flows, reconciled via tombstones.
  Consequences:

  * Storage schema must support tombstone flags and exclude-by-default in UI/retrieval unless explicitly requested.
  * Disk-pressure handling triggers explicit user actions rather than automatic sweeps.
    Sources: [SRC-032, SRC-022]
* ADR_ID: ADR-008
  Title: Egress sanitization uses typed tokens + glossary with leak-check blocking
  Decision: All outbound payloads must be transformed into ReasoningPacketV1 and pass sanitizer + leak checks; if leak detected, block egress.
  Rationale: Security contract pinned; user requires secure parity.
  Consequences:

  * Any network plugin other than egress gateway is forbidden.
  * Sanitizer must be evaluated for recall/precision; failures are fail-closed.
    Sources: [SRC-033, SRC-034, SRC-036, SRC-037, SRC-047]
* ADR_ID: ADR-009
  Title: Journal + Ledger are pinned contracts for auditability
  Decision: Journal events and ledger entries conform to pinned schemas; ledger uses canonical JSON hashing and anchors head hashes in an anchor store.
  Rationale: Security contract requires append-only and hash chaining; schemas are pinned.
  Consequences:

  * All critical operations (key rotation, policy changes, egress sends) must emit ledger entries.
  * Contract changes must update contract lock hashes.
    Sources: [SRC-038, SRC-039, SRC-045, SRC-046]
* ADR_ID: ADR-010
  Title: Vector index backend defaults local; Qdrant is optional opt-in
  Decision: Provide a local vector index backend by default and support Qdrant adapter as opt-in.
  Rationale: Autocapture ADR indicates Qdrant opt-in; Prime must remain single-machine local-first.
  Consequences:

  * Doctor must check qdrant only when enabled.
  * Export/import must handle both backends (exported embeddings and IDs).
    Sources: [SRC-057, SRC-015]

# 4. Grounding Data (Few-Shot Samples)

* Sample_ID: SAMPLE-001
  Module: MOD-026
  Purpose: Deterministic time intent parsing
  Table:

  ```text
  | query                         | tz                  | now_utc                  | time_window.start           | time_window.end             | assumptions                          |
  | "this morning emails"         | "America/Denver"    | "2026-01-25T20:00:00Z"    | "2026-01-25T07:00:00-07:00" | "2026-01-25T12:00:00-07:00" | ["interpreted 'morning' as 07-12"]  |
  | "yesterday afternoon"         | "America/Denver"    | "2026-01-25T20:00:00Z"    | "2026-01-24T12:00:00-07:00" | "2026-01-24T17:00:00-07:00" | ["interpreted 'afternoon' as 12-17"]|
  | "between 3pm and 4pm Friday"  | "America/Denver"    | "2026-01-25T20:00:00Z"    | "2026-01-23T15:00:00-07:00" | "2026-01-23T16:00:00-07:00" | ["resolved 'Friday' as 2026-01-23"] |
  ```
* Sample_ID: SAMPLE-002
  Module: MOD-011
  Purpose: Duplicate detection decisions
  Table:

  ```text
  | frame_hash  | phash     | monotonic_ts | decision.is_duplicate | dedupe_group_id | reason            |
  | "h1"        | "p1"      | 1000.0       | false                 | "G1"            | "new_group"       |
  | "h1"        | "p1"      | 1000.5       | true                  | "G1"            | "exact_hash"      |
  | "h2"        | "p1"      | 1002.0       | true                  | "G1"            | "phash_threshold" |
  ```
* Sample_ID: SAMPLE-003
  Module: MOD-023
  Purpose: Hybrid retrieval fusion and citable mapping
  Table:

  ```text
  | query        | lexical_hits(doc_id:score)           | vector_hits(point_id:score)          | fused_top(doc_id) | non_citable | scores(lexical,dense,rerank) |
  | "roadmap"    | ["S12:0.80","S90:0.60"]              | ["S12:0.72","S77:0.65"]              | "S12"             | false      | (0.80,0.72,0.90)            |
  | "ticket-123" | ["S33:0.95"]                          | ["S44:0.40"]                          | "S33"             | false      | (0.95,0.10,0.88)            |
  | "unobtainium"| []                                    | []                                    | [NONE]            | true       | (null,null,null)            |
  ```
* Sample_ID: SAMPLE-004
  Module: MOD-024
  Purpose: Evidence-first answer building (“no evidence → no claim”)
  Table:

  ```text
  | query                   | retrieval_count | output.claims_count | output.warnings                         | citation_example |
  | "When did I update..."  | 5               | 2                   | []                                      | "Claim cites E1" |
  | "Find security review"  | 1               | 1                   | ["low_evidence_count"]                  | "Claim cites E1" |
  | "unobtainium"           | 0               | 0                   | ["no_evidence"]                         | [NONE]           |
  ```
* Sample_ID: SAMPLE-005
  Module: MOD-028
  Purpose: Egress sanitizer typed tokens + leak blocking
  Table:

  ```text
  | input_text                                 | sanitized_text                               | glossary_keys                     | leak_detected | leak_reasons            |
  | "Email Ada at ada@example.com"             | "Email ⟦ENT:PERSON:T1⟧ at ⟦ENT:EMAIL:T2⟧"   | ["⟦ENT:PERSON:T1⟧","⟦ENT:EMAIL:T2⟧"] | false        | []                      |
  | "SSN 123-45-6789 in note"                 | "SSN ⟦ENT:SSN:T1⟧ in note"                  | ["⟦ENT:SSN:T1⟧"]                  | false        | []                      |
  | "My API key is [REDACTED_SECRET]"         | [BLOCKED]                                   | []                                | true         | ["secret_pattern_match"]|
  ```
* Sample_ID: SAMPLE-006
  Module: MOD-030
  Purpose: Export/import ZIP bundle structure and roundtrip
  Table:

  ```text
  | export_opts(include_media,decrypt_media) | zip_contains_files                                      | import_result.summary                 | roundtrip_ok |
  | (true,false)                            | ["events.jsonl","manifest.json","settings.json","config.json"] + media blobs | {"events": 100, "media": 50}         | true         |
  | (false,false)                           | ["events.jsonl","manifest.json","settings.json","config.json"]               | {"events": 100, "media": 0}          | true         |
  | (true,true)                             | ["events.jsonl","manifest.json","settings.json","config.json"] + decrypted media | {"events": 100, "media": 50, "decrypted":true} | true |
  ```
* Sample_ID: SAMPLE-007
  Module: MOD-015
  Purpose: Runtime governor mode transitions
  Table:

  ```text
  | is_fullscreen | idle_seconds | expected_mode             | reason                         |
  | true          | 5            | "FULLSCREEN_HARD_PAUSE"   | "fullscreen_detected"          |
  | false         | 10           | "ACTIVE_INTERACTIVE"      | "interactive_default"          |
  | false         | 600          | "IDLE_DRAIN"              | "idle_threshold_exceeded"      |
  ```
* Sample_ID: SAMPLE-008
  Module: MOD-031
  Purpose: Plugin enable/disable with allowlist + hash lock enforcement
  Table:

  ```text
  | plugin_id                 | allowlisted | hash_ok | action          | result                 |
  | "mx.capture.screen_windows"| true        | true    | enable          | enabled=true           |
  | "mx.core.egress_gateway"  | true        | false   | enable          | blocked(hash_mismatch) |
  | "thirdparty.plugin"       | false       | n/a     | enable          | blocked(not_allowlisted) |
  ```
* Sample_ID: SAMPLE-009
  Module: MOD-003
  Purpose: Capability registration and lookup behavior
  Table:

  ```text
  | action      | capability_name        | value        | expected_has | expected_get                   |
  | "register"  | "storage.metadata"     | "store_v1"   | true         | "store_v1"                     |
  | "get"       | "capture.source"       | [NONE]       | false        | error("Missing capability")     |
  | "register"  | "observability.logger" | "logger_v2"  | true         | "logger_v2"                    |
  ```
* Sample_ID: SAMPLE-010
  Module: MOD-016
  Purpose: Privacy policy tagging and egress gating decisions (D1)
  Table:

  ```text
  | context.label   | privacy_flags                 | local_capture | egress_allowed | sanitize_required |
  | "email_thread" | ["PII_EMAIL"]                | true          | false          | true              |
  | "public_docs"  | []                             | true          | true           | false             |
  | "ssn_note"     | ["PII_SSN","SENSITIVE"]      | true          | false          | true              |
  ```
* Sample_ID: SAMPLE-011
  Module: MOD-040
  Purpose: Tombstone-first retention flow (preview/apply/cleanup derived)
  Table:

  ```text
  | action    | target_scope        | preview_count | apply_count | derived_cleanup | evidence_deleted |
  | "preview" | "before:2025-01-01" | 12            | 0           | 0               | false            |
  | "apply"   | "before:2025-01-01" | 12            | 12          | 12              | false            |
  | "cleanup" | "before:2025-01-01" | 0             | 0           | 12              | false            |
  ```
