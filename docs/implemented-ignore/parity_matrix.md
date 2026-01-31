# Parity matrix (MOD/ADR/SRC)

Source: `data/full.md`.
Legacy I-item coverage is embedded in `data/full.md` under `Legacy_I_Item_Crosswalk`.

## Modules

| MOD | Object_Name | Object_Type | Priority | Sources | Sample_IDs | I-Refs | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MOD-001 | NX Kernel Boot & Effective Config Builder | Library | MUST | SRC-007, SRC-028, SRC-030, SRC-040, SRC-043, SRC-058 | - | - | unverified | - |
| MOD-002 | NX Plugin Registry, Allowlist, Hash Locks, Safe Mode Loader | Library | MUST | SRC-011, SRC-030, SRC-033, SRC-034, SRC-035, SRC-043, SRC-044 | - | - | unverified | - |
| MOD-003 | Capability Broker and System Container | Business Logic | MUST | SRC-007, SRC-040, SRC-041 | SAMPLE-009 | - | unverified | - |
| MOD-004 | Keyring, Key Derivation, and Key Rotation (Ledger + Anchor) | Library | MUST | SRC-036, SRC-038, SRC-039, SRC-041 | - | - | unverified | - |
| MOD-005 | Journal Writer (Append-Only JSONL + Schema) | Library | MUST | SRC-038, SRC-045 | - | - | unverified | - |
| MOD-006 | Ledger Writer (Hash-Chained Canonical JSON) + Anchor Store | Library | MUST | SRC-038, SRC-039, SRC-046 | - | - | unverified | - |
| MOD-007 | Prime MX App Orchestrator + CLI Commands | CLI | MUST | SRC-001, SRC-002, SRC-003, SRC-040, SRC-041, SRC-042 | - | - | unverified | - |
| MOD-008 | Capture Pipeline Orchestrator (Screen + Audio + Metadata + Segmenting) | Background Worker | MUST | SRC-008, SRC-020, SRC-028, SRC-031, SRC-051, SRC-058 | - | - | unverified | - |
| MOD-009 | Screen Capture Backend DXCAM (Primary) | Library | MUST | SRC-051, SRC-020 | - | - | unverified | - |
| MOD-010 | Screen Capture Backend MSS (Fallback) | Library | MUST | SRC-051, SRC-020 | - | - | unverified | - |
| MOD-011 | Duplicate Detector (Frame Hash + pHash + Dedupe Grouping) | Business Logic | MUST | SRC-020, SRC-050 | SAMPLE-002 | - | unverified | - |
| MOD-012 | Segment Recorder (FFmpeg, NVENC Optional) + Segment Manifest | Background Worker | MUST | SRC-020, SRC-058 | - | - | unverified | - |
| MOD-013 | Foreground Context Tracker (App/Title/URL/Domain) | Background Worker | MUST | SRC-021, SRC-020 | - | - | unverified | - |
| MOD-014 | Raw Input Listener + Idle Gate | Background Worker | MUST | SRC-021, SRC-020 | - | - | unverified | - |
| MOD-015 | Runtime Governor (Modes + Pause Latch Semantics) | Business Logic | MUST | SRC-054, SRC-021 | SAMPLE-007 | - | unverified | - |
| MOD-016 | Privacy Policy Evaluator and Local Sensitivity Tagging | Business Logic | MUST | SRC-031, SRC-055, SRC-028, SRC-026 | SAMPLE-010 | - | unverified | - |
| MOD-017 | OCR Extractor (Local) Producing OCRSpan and Normalized Index Text | Background Worker | MUST | SRC-023, SRC-049, SRC-050 | - | - | unverified | - |
| MOD-018 | VLM Extractor (Local) for Structured Screen Understanding | Background Worker | MUST | SRC-023, SRC-020, SRC-050 | - | - | unverified | - |
| MOD-019 | Embedding Service (Fastembed + SentenceTransformer Fallback) | Background Worker | MUST | SRC-023, SRC-056 | - | - | unverified | - |
| MOD-020 | Vector Index Adapter (Local Default, Qdrant Optional) | Data Store | MUST | SRC-015, SRC-023, SRC-057 | - | - | unverified | - |
| MOD-021 | Lexical Index (SQLite FTS5 + Deterministic Fallback) | Data Store | MUST | SRC-015, SRC-023, SRC-050 | - | - | unverified | - |
| MOD-022 | Spans Store (Citable Spans, BBoxes, Provenance) | Data Store | MUST | SRC-049, SRC-050 | - | - | unverified | - |
| MOD-023 | Hybrid Retrieval Engine (Time Intent + Filters + Fusion + Rerank) | Business Logic | MUST | SRC-010, SRC-023, SRC-050, SRC-053 | SAMPLE-003 | - | unverified | - |
| MOD-024 | Answer Builder + Validators (No-Evidence, Provenance, Entailment, Conflict, Integrity) | Business Logic | MUST | SRC-024, SRC-010, SRC-050 | SAMPLE-004 | - | unverified | - |
| MOD-025 | Citation Renderer + Overlay Evidence API | API Endpoint | MUST | SRC-014, SRC-024, SRC-049 | - | - | unverified | - |
| MOD-026 | Deterministic Time Intent Parser (Basic + Advanced) | Business Logic | MUST | SRC-059, SRC-041 | SAMPLE-001 | - | unverified | - |
| MOD-027 | Gateway Stage Router + LLM Client (Local/Cloud via Policy) | API Endpoint | MUST | SRC-016, SRC-019, SRC-030, SRC-034 | - | - | unverified | - |
| MOD-028 | Egress Gateway + Sanitizer (ReasoningPacketV1) | Business Logic | MUST | SRC-028, SRC-033, SRC-034, SRC-036, SRC-037, SRC-047 | SAMPLE-005 | - | unverified | - |
| MOD-029 | Memory Service (Local Store + API) | API Endpoint | MUST | SRC-016, SRC-053 | - | - | unverified | - |
| MOD-030 | Exporter/Importer (Autocapture-Compatible ZIP + Roundtrip) | Business Logic | MUST | SRC-009, SRC-018, SRC-052 | SAMPLE-006 | - | unverified | - |
| MOD-031 | MX Plugin Manager (Discovery + Policy + Settings + Enable/Disable) | Library | MUST | SRC-011, SRC-043, SRC-044 | SAMPLE-008 | - | unverified | - |
| MOD-032 | FastAPI Server (Core + Events + UX + Plugins + Storage + Query) | API Endpoint | MUST | SRC-012, SRC-025, SRC-053 | - | - | unverified | - |
| MOD-033 | UI/UX Layer (Web UI + UX Facade) | Other | MUST | SRC-013, SRC-025 | - | - | unverified | - |
| MOD-034 | Overlay Tracker + Citation Overlay Rendering | Other | MUST | SRC-014, SRC-025 | - | - | unverified | - |
| MOD-035 | Doctor & Diagnostics (Full Parity) | CLI | MUST | SRC-027, SRC-059, SRC-042 | - | - | unverified | - |
| MOD-036 | Observability (Redacted JSONL Logs + Metrics) | Library | MUST | SRC-027, SRC-059 | - | - | unverified | - |
| MOD-037 | Evaluation Harness + CI Gates (Retrieval, PromptOps, No-Evidence) | CLI | MUST | SRC-002, SRC-024 | - | - | unverified | - |
| MOD-038 | Installer + Infra (Qdrant/Prometheus/Loki/Grafana + Windows Setup) | Other | MUST | SRC-017, SRC-057 | - | - | unverified | - |
| MOD-039 | Typed Storage + Migrations (Metadata, Indexes, Spans) | Data Store | MUST | SRC-022, SRC-048, SRC-050 | - | - | unverified | - |
| MOD-040 | Retention, Deletion Semantics, and Archive (Tombstone-First) | Business Logic | MUST | SRC-022, SRC-032 | SAMPLE-011 | - | unverified | - |

## ADRs

| ADR | Title | Sources | I-Refs | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
| ADR-001 | Prime is the successor vehicle implementing all Autocapture ideas with full parity | SRC-001, SRC-002, SRC-003, SRC-004, SRC-005, SRC-006 | - | unverified | - |
| ADR-002 | Dual-layer plugin architecture (NX kernel plugins + MX app/plugin manager) | SRC-007, SRC-011, SRC-043, SRC-044 | - | unverified | - |
| ADR-003 | Privacy posture reconciliation: local capture is unmodified; privacy is enforced at egress and UI surfaces | SRC-028, SRC-031, SRC-055, SRC-026 | - | unverified | - |
| ADR-004 | Evidence-first answering with claim-level citations and strict provenance validation | SRC-010, SRC-024, SRC-049, SRC-050 | - | unverified | - |
| ADR-005 | Export/import format compatibility with Autocapture ZIP bundles | SRC-009, SRC-018, SRC-052 | - | unverified | - |
| ADR-006 | Implement Gateway model as first-class Prime component | SRC-016, SRC-019, SRC-030, SRC-034 | - | unverified | - |
| ADR-007 | Retention and deletion semantics are tombstone-first with no physical deletion of local evidence | SRC-032, SRC-022 | - | unverified | - |
| ADR-008 | Egress sanitization uses typed tokens + glossary with leak-check blocking | SRC-033, SRC-034, SRC-036, SRC-037, SRC-047 | - | unverified | - |
| ADR-009 | Journal + Ledger are pinned contracts for auditability | SRC-038, SRC-039, SRC-045, SRC-046 | - | unverified | - |
| ADR-010 | Vector index backend defaults local; Qdrant is optional opt-in | SRC-057, SRC-015 | - | unverified | - |

## SRC Index (from BLUEPRINT)
