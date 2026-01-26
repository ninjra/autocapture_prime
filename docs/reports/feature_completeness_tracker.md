# Feature completeness tracker

Authoritative sources:
- `docs/spec/feature_completeness_spec.md`
- `docs/blueprints/feature_completeness_blueprint.txt`

## Modules
- [ ] MOD-001 — NX Kernel Boot & Effective Config Builder
- [ ] MOD-002 — NX Plugin Registry, Allowlist, Hash Locks, Safe Mode Loader
- [ ] MOD-003 — Capability Broker and System Container
- [ ] MOD-004 — Keyring, Key Derivation, and Key Rotation (Ledger + Anchor)
- [ ] MOD-005 — Journal Writer (Append-Only JSONL + Schema)
- [ ] MOD-006 — Ledger Writer (Hash-Chained Canonical JSON) + Anchor Store
- [ ] MOD-007 — Prime MX App Orchestrator + CLI Commands
- [ ] MOD-008 — Capture Pipeline Orchestrator (Screen + Audio + Metadata + Segmenting)
- [ ] MOD-009 — Screen Capture Backend DXCAM (Primary)
- [ ] MOD-010 — Screen Capture Backend MSS (Fallback)
- [ ] MOD-011 — Duplicate Detector (Frame Hash + pHash + Dedupe Grouping)
- [ ] MOD-012 — Segment Recorder (FFmpeg, NVENC Optional) + Segment Manifest
- [ ] MOD-013 — Foreground Context Tracker (App/Title/URL/Domain)
- [ ] MOD-014 — Raw Input Listener + Idle Gate
- [ ] MOD-015 — Runtime Governor (Modes + Pause Latch Semantics)
- [ ] MOD-016 — Privacy Policy Evaluator and Local Sensitivity Tagging
- [ ] MOD-017 — OCR Extractor (Local) Producing OCRSpan and Normalized Index Text
- [ ] MOD-018 — VLM Extractor (Local) for Structured Screen Understanding
- [ ] MOD-019 — Embedding Service (Fastembed + SentenceTransformer Fallback)
- [ ] MOD-020 — Vector Index Adapter (Local Default, Qdrant Optional)
- [ ] MOD-021 — Lexical Index (SQLite FTS5 + Deterministic Fallback)
- [ ] MOD-022 — Spans Store (Citable Spans, BBoxes, Provenance)
- [ ] MOD-023 — Hybrid Retrieval Engine (Time Intent + Filters + Fusion + Rerank)
- [ ] MOD-024 — Answer Builder + Validators (No-Evidence, Provenance, Entailment, Conflict, Integrity)
- [ ] MOD-025 — Citation Renderer + Overlay Evidence API
- [ ] MOD-026 — Deterministic Time Intent Parser (Basic + Advanced)
- [ ] MOD-027 — Gateway Stage Router + LLM Client (Local/Cloud via Policy)
- [ ] MOD-028 — Egress Gateway + Sanitizer (ReasoningPacketV1)
- [ ] MOD-029 — Memory Service (Local Store + API)
- [ ] MOD-030 — Exporter/Importer (Autocapture-Compatible ZIP + Roundtrip)
- [ ] MOD-031 — MX Plugin Manager (Discovery + Policy + Settings + Enable/Disable)
- [ ] MOD-032 — FastAPI Server (Core + Events + UX + Plugins + Storage + Query)
- [ ] MOD-033 — UI/UX Layer (Web UI + UX Facade)
- [ ] MOD-034 — Overlay Tracker + Citation Overlay Rendering
- [ ] MOD-035 — Doctor & Diagnostics (Full Parity)
- [ ] MOD-036 — Observability (Redacted JSONL Logs + Metrics)
- [ ] MOD-037 — Evaluation Harness + CI Gates (Retrieval, PromptOps, No-Evidence)
- [ ] MOD-038 — Installer + Infra (Qdrant/Prometheus/Loki/Grafana + Windows Setup)
- [ ] MOD-039 — Typed Storage + Migrations (Metadata, Indexes, Spans)
- [ ] MOD-040 — Retention, Deletion Semantics, and Archive (Tombstone-First)

## ADRs
- [ ] ADR-001
- [ ] ADR-002
- [ ] ADR-003
- [ ] ADR-004
- [ ] ADR-005
- [ ] ADR-006
- [ ] ADR-007
- [ ] ADR-008
- [ ] ADR-009
- [ ] ADR-010
