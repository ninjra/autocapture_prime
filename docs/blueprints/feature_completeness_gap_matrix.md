# Feature completeness gap matrix

Purpose: map MOD-001..MOD-040 to repo evidence for the Prime feature completeness spec.

Authoritative sources:
- `docs/spec/feature_completeness_spec.md`
- `docs/blueprints/feature_completeness_blueprint.txt`

Method:
- Parsed `Object_ID` blocks in the spec for MOD-###, extracted `Object_Name`, `Sources`, and interface class symbols (fallback to function symbols if no classes).
- Searched repo for interface symbols using `rg -n -i "\bclass\s+<Symbol>\b|\bdef\s+<Symbol>\b"` scoped to source dirs (autocapture_nx, autocapture, plugins).
- Status is **partial** when symbol hits exist; **missing** when none were found (may still exist under different names).

Entrypoint + plugin artifacts:
- CLI entrypoint: pyproject.toml: autocapture = autocapture_nx.cli:main
- Plugin lockfile: `config/plugin_locks.json`
- Plugin manifest schema: `contracts/plugin_manifest.schema.json`
- Plugin manifests: `plugins/builtin/*/plugin.json`

## Module coverage

| MOD | Name | Status | Evidence (rg hits) | Notes |
| --- | --- | --- | --- | --- |
| MOD-001 | NX Kernel Boot & Effective Config Builder | partial | autocapture_nx/kernel/loader.py:32:class KernelBootArgs:<br>autocapture_nx/kernel/loader.py:39:class EffectiveConfig:<br>autocapture_nx/kernel/loader.py:45:class Kernel: | Symbols: KernelBootArgs, EffectiveConfig, Kernel |
| MOD-002 | NX Plugin Registry, Allowlist, Hash Locks, Safe Mode Loader | partial | autocapture_nx/plugin_system/manifest.py:11:class PluginEntrypoint:<br>autocapture_nx/plugin_system/manifest.py:19:class PluginPermissions:<br>autocapture_nx/plugin_system/manifest.py:27:class PluginCompat:<br>autocapture_nx/plugin_system/manifest.py:33:class PluginHashLock:<br>autocapture/plugins/manifest.py:24:class PluginManifest: | Symbols: PluginEntrypoint, PluginPermissions, PluginCompat, PluginHashLock, PluginManifest, Plugin, PluginRegistry |
| MOD-003 | Capability Broker and System Container | partial | autocapture_nx/kernel/system.py:12:class System: | Symbols: System |
| MOD-004 | Keyring, Key Derivation, and Key Rotation (Ledger + Anchor) | partial | autocapture_nx/kernel/keyring.py:164:class KeyringStatus:<br>autocapture_nx/kernel/keyring.py:58:class KeyRing:<br>autocapture_nx/kernel/keyring.py:169:class Keyring(KeyRing): | Symbols: KeyringStatus, Keyring |
| MOD-005 | Journal Writer (Append-Only JSONL + Schema) | partial | plugins/builtin/journal_basic/plugin.py:17:class JournalEvent:<br>plugins/builtin/journal_basic/plugin.py:28:class JournalWriter(PluginBase): | Symbols: JournalEvent, JournalWriter |
| MOD-006 | Ledger Writer (Hash-Chained Canonical JSON) + Anchor Store | partial | plugins/builtin/ledger_basic/plugin.py:17:class LedgerEntryV1:<br>plugins/builtin/ledger_basic/plugin.py:30:class LedgerWriter(PluginBase):<br>plugins/builtin/anchor_basic/plugin.py:14:class AnchorWriter(PluginBase): | Symbols: LedgerEntryV1, LedgerWriter, AnchorWriter |
| MOD-007 | Prime MX App Orchestrator + CLI Commands | partial | autocapture_nx/cli.py:26:def cmd_doctor(args: argparse.Namespace) -> int:<br>autocapture_nx/cli.py:38:def cmd_config_show(_args: argparse.Namespace) -> int:<br>autocapture_nx/cli.py:45:def cmd_config_reset(_args: argparse.Namespace) -> int:<br>autocapture_nx/cli.py:52:def cmd_config_restore(_args: argparse.Namespace) -> int:<br>autocapture_nx/cli.py:59:def cmd_plugins_list(args: argparse.Namespace) -> int: | Symbols: cmd_doctor, cmd_config_show, cmd_config_reset, cmd_config_restore, cmd_plugins_list, cmd_plugins_approve, cmd_run, cmd_query, cmd_devtools_diffusion, cmd_devtools_ast_ir, cmd_keys_rotate |
| MOD-008 | Capture Pipeline Orchestrator (Screen + Audio + Metadata + Segmenting) | partial | autocapture/capture/pipelines.py:22:class CapturePipeline: | Symbols: CaptureFrame, CapturePipeline |
| MOD-009 | Screen Capture Backend DXCAM (Primary) | missing |  | Symbols: ScreenCaptureBackend, DXCAMBackend |
| MOD-010 | Screen Capture Backend MSS (Fallback) | missing |  | Symbols: MSSBackend |
| MOD-011 | Duplicate Detector (Frame Hash + pHash + Dedupe Grouping) | missing |  | Symbols: DedupeDecision, DuplicateDetector |
| MOD-012 | Segment Recorder (FFmpeg, NVENC Optional) + Segment Manifest | missing |  | Symbols: SegmentRecord, SegmentRecorder |
| MOD-013 | Foreground Context Tracker (App/Title/URL/Domain) | missing |  | Symbols: ForegroundContext, ForegroundTracker |
| MOD-014 | Raw Input Listener + Idle Gate | missing |  | Symbols: InputState, RawInputListener |
| MOD-015 | Runtime Governor (Modes + Pause Latch Semantics) | partial | autocapture/runtime/governor.py:21:class RuntimeGovernor:<br>plugins/builtin/runtime_governor/plugin.py:17:class RuntimeGovernor(PluginBase): | Symbols: RuntimeModeTransition, RuntimeGovernor |
| MOD-016 | Privacy Policy Evaluator and Local Sensitivity Tagging | missing |  | Symbols: PrivacyDecision, PrivacyPolicy |
| MOD-017 | OCR Extractor (Local) Producing OCRSpan and Normalized Index Text | missing |  | Symbols: OCRSpan, OCRDocument, OcrExtractor |
| MOD-018 | VLM Extractor (Local) for Structured Screen Understanding | missing |  | Symbols: VlmExtraction, VlmExtractor |
| MOD-019 | Embedding Service (Fastembed + SentenceTransformer Fallback) | missing |  | Symbols: EmbeddingResult, Embedder |
| MOD-020 | Vector Index Adapter (Local Default, Qdrant Optional) | partial | autocapture/indexing/vector.py:83:class VectorHit:<br>autocapture/indexing/vector.py:88:class VectorIndex: | Symbols: VectorPoint, VectorHit, VectorIndex |
| MOD-021 | Lexical Index (SQLite FTS5 + Deterministic Fallback) | partial | autocapture/indexing/lexical.py:10:class LexicalIndex: | Symbols: LexicalHit, LexicalIndex |
| MOD-022 | Spans Store (Citable Spans, BBoxes, Provenance) | missing |  | Symbols: SpansStore |
| MOD-023 | Hybrid Retrieval Engine (Time Intent + Filters + Fusion + Rerank) | missing |  | Symbols: ScoreBreakdown, RetrievalResult, RetrievalEngine |
| MOD-024 | Answer Builder + Validators (No-Evidence, Provenance, Entailment, Conflict, Integrity) | partial | plugins/builtin/answer_basic/plugin.py:10:class AnswerBuilder(PluginBase): | Symbols: EvidenceItem, Claim, Answer, AnswerBuilder, ClaimValidators |
| MOD-025 | Citation Renderer + Overlay Evidence API | missing |  | Symbols: CitationOverlayItem, CitationOverlayService |
| MOD-026 | Deterministic Time Intent Parser (Basic + Advanced) | partial | plugins/builtin/time_basic/plugin.py:11:class TimeIntentParser(PluginBase):<br>plugins/builtin/time_advanced/plugin.py:19:class TimeIntentParser(PluginBase): | Symbols: TimeWindow, TimeIntentResult, TimeIntentParser |
| MOD-027 | Gateway Stage Router + LLM Client (Local/Cloud via Policy) | missing |  | Symbols: ModelStage, StageRouter, LlmClient |
| MOD-028 | Egress Gateway + Sanitizer (ReasoningPacketV1) | partial | autocapture/ux/redaction.py:10:class EgressSanitizer:<br>plugins/builtin/egress_sanitizer/plugin.py:51:class EgressSanitizer(PluginBase):<br>plugins/builtin/egress_gateway/plugin.py:16:class EgressGateway(PluginBase): | Symbols: SanitizationResult, EgressSanitizer, ReasoningPacketV1, EgressGateway |
| MOD-029 | Memory Service (Local Store + API) | missing |  | Symbols: MemorySnapshot, MemoryService |
| MOD-030 | Exporter/Importer (Autocapture-Compatible ZIP + Roundtrip) | missing |  | Symbols: ExportOptions, ExportResult, ExportService, ImportService |
| MOD-031 | MX Plugin Manager (Discovery + Policy + Settings + Enable/Disable) | partial | autocapture_nx/plugin_system/manager.py:17:class PluginStatus:<br>autocapture/plugins/manager.py:24:class PluginManager:<br>autocapture_nx/plugin_system/manager.py:27:class PluginManager: | Symbols: PluginStatus, PluginManager |
| MOD-032 | FastAPI Server (Core + Events + UX + Plugins + Storage + Query) | missing |  | Symbols: create_app |
| MOD-033 | UI/UX Layer (Web UI + UX Facade) | missing |  | Symbols: (none extracted) |
| MOD-034 | Overlay Tracker + Citation Overlay Rendering | missing |  | Symbols: OverlayRect, OverlayLabel, OverlayTracker |
| MOD-035 | Doctor & Diagnostics (Full Parity) | missing |  | Symbols: DoctorCheckResult, DoctorService |
| MOD-036 | Observability (Redacted JSONL Logs + Metrics) | partial | autocapture/web/routes/metrics.py:12:def metrics(): | Symbols: Logger, Metrics |
| MOD-037 | Evaluation Harness + CI Gates (Retrieval, PromptOps, No-Evidence) | missing |  | Symbols: EvalCase, EvalMetrics, EvalRunner, CiGate |
| MOD-038 | Installer + Infra (Qdrant/Prometheus/Loki/Grafana + Windows Setup) | missing |  | Symbols: (none extracted) |
| MOD-039 | Typed Storage + Migrations (Metadata, Indexes, Spans) | missing |  | Symbols: MigrationResult, MetadataStore |
| MOD-040 | Retention, Deletion Semantics, and Archive (Tombstone-First) | missing |  | Symbols: DeletePreview, RetentionService |

## Next implementation order (from blueprint milestones)
1) Contracts + effective config + kernel boot
2) Plugin registry + allowlist/hash locks + safe mode
3) Network guard + egress-only routing
4) Journal/ledger/anchor + keyring/rotation
5) Typed storage + migrations + tombstones
6) Capture orchestration + runtime governor + privacy
7) OCR/VLM + spans
8) Embeddings + lexical/vector indexes
9) Time intent + retrieval + answer builder
10) Egress gateway/sanitizer + reasoning packets
11) FastAPI + UI/overlay
12) Export/import + doctor/observability + eval gates
