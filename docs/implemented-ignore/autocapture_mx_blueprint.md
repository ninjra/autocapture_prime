# Autocapture MX Blueprint (Rock-Solid, Plugin-First, Local-First)

**Document version:** 1.0  
**Date:** 2026-01-25  
**Target:** Implement a fully feature-complete Autocapture MX superset inside the repository represented by `repomix-output.xml` (referred to below as **NX repo**).  
**Compatibility baseline:** Ninjra Autocapture plugin + policy patterns (manifests, policy gate, retrieval tiering, PromptOps, CI gates), extended and enforced for the Autocapture “4 Pillars”.

---

## 0) Non‑negotiables (Project Facts)

These are invariants. Any implementation that violates them does not ship.

### 0.1 Local capture + privacy posture
- **Capture everything locally** (no masking, filtering, replacement, or deletion on the local machine).
- **Cloud never sees raw PII.** Cloud egress is allowed only when payloads are **sanitized** (entity hashing for text; redaction pipeline for images/audio if enabled).
- **User-visible + user-controlled.** Defaults are capture-all locally; sanitization occurs only on egress.

### 0.2 Platform and UI
- **Windows-first.**
- **Headless core + Web Console** (served via **FastAPI**) is the only first-class UI.
- **UI/CLI parity**: both call the same **UX Facade** module functions.

### 0.3 Performance + scheduling
- While the user is actively interacting with the computer:
  - The system is effectively invisible.
  - No OCR, embeddings, VLM, conversion, indexing, or other heavy processing.
- Heavy processing occurs:
  - On explicit user commands, or
  - During low-impact windows (idle), with immediate ramp-down on user input.

### 0.4 Architecture principles
- **Plugin-first architecture**: even core functionality is implemented as replaceable plugins.
- Plugins hot-swap automatically for non-core plugins.

### 0.5 4 Pillars (design optimization targets)
- **P1 Performant**: bounded overhead and adaptive budgets.
- **P2 Accurate**: deterministic pipelines, verifiable results, conflict awareness.
- **P3 Secure**: strong at-rest encryption, policy gate for egress, least privilege, safe mode.
- **P4 Citable**: deterministic evidence + claim-level citations, validation, and provenance ledger.

---

## 1) Definitions

- **NX repo**: the codebase represented by `repomix-output.xml`.
- **MX**: the new target state (superset) implemented in NX repo.
- **Evidence**: captured artifacts + derived spans that can be cited.
- **Span**: a minimal citable unit (text range + optional bounding box + origin metadata).
- **Claim**: an atomic statement in an answer that must be supported by citations.
- **Ledger**: append-only, hash-chained provenance log for critical outputs (captures, spans, queries, answers, exports).

---

## 2) System Overview

### 2.1 Component diagram (logical)

```
[Capture Plugins] --> [Spool/Queue] --> [Ingest Plugins] --> [Span Store] --> [Indexes]
                                                |                |             |
                                                |                v             v
                                                |            [Ledger]     [Retrieval]
                                                v                               |
                                     [Archive/Bundle Export]                     v
                                                          <-- [Gateway] <-- [Answer Orchestrator]
                                                                           |
                                                                           v
                                                                      [Web Console]
```

### 2.2 Mandatory boundary points
- **All network egress** is mediated by **PolicyGate + EgressClient**.
- **All user-facing answers** pass through **Citations + Validation + Ledger append**.
- **All heavy work** is gated by **RuntimeGovernor** and its activity signal.

---

## 3) Repository Contract (What “Feature Complete” Means)

MX is considered complete when **Codex** validates all requirements in the embedded spec (Appendix A) with status **PASS**.

This blueprint defines:
- the exact subsystems,
- file/module responsibilities,
- runtime invariants,
- validation methods Codex executes to prove completeness.

Codex is part of MX and is required for “rock solid” operation.

---

## 4) Directory Layout (Target State)

The exact top-level folder names can be adapted to the NX repo, but Codex validation is path-based. The following layout is the canonical target:

```
/autocapture/
  __init__.py
  app.py
  config/
    __init__.py
    models.py
    load.py
    defaults.py
  codex/
    __init__.py
    cli.py
    spec.py
    validators.py
    report.py
  core/
    __init__.py
    ids.py
    hashing.py
    time.py
    errors.py
    jsonschema.py
    http.py
  pillars/
    __init__.py
    gates.py
    privacy.py
    accuracy.py
    performance.py
    citable.py
  plugins/
    __init__.py
    kinds.py
    manifest.py
    manager.py
    policy_gate.py
    sandbox.py
  runtime/
    __init__.py
    governor.py
    activity.py
    budgets.py
    scheduler.py
    leases.py
  storage/
    __init__.py
    database.py
    models.py
    migrations/
    media_store.py
    blob_store.py
    sqlcipher.py
    keys.py
    archive.py
  capture/
    __init__.py
    models.py
    spool.py
    pipelines.py
  ingest/
    __init__.py
    normalizer.py
    spans.py
  indexing/
    __init__.py
    lexical.py
    vector.py
    graph.py
  retrieval/
    __init__.py
    tiers.py
    fusion.py
    rerank.py
    signals.py
  rules/
    __init__.py
    schema.py
    ledger.py
    store.py
    cli.py
  memory/
    __init__.py
    context_pack.py
    answer_orchestrator.py
    citations.py
    verifier.py
    conflict.py
    entities.py
  gateway/
    __init__.py
    app.py
    router.py
    schemas.py
  ux/
    __init__.py
    facade.py
    models.py
    settings_schema.py
    preview_tokens.py
    redaction.py
  web/
    __init__.py
    api.py
    routes/
      settings.py
      query.py
      capture.py
      citations.py
      plugins.py
      health.py
      metrics.py
    static/
  promptops/
    __init__.py
    models.py
    sources.py
    propose.py
    evaluate.py
    patch.py
    github.py
    validate.py
  training/
    __init__.py
    pipelines.py
    lora.py
    dpo.py
    datasets.py
  research/
    __init__.py
    scout.py
    diff.py
    cache.py
  tools/
    pillar_gate.py
    privacy_scanner.py
    provenance_gate.py
    coverage_gate.py
    latency_gate.py
    retrieval_sensitivity.py
    conflict_gate.py
    integrity_gate.py
    vendor_windows_binaries.py
/tests/
  ...
/autocapture_plugins/
  <plugin_id>.yaml
  <plugin_id>/
    assets/...
/docs/
  ...
/pyproject.toml
```

Notes:
- `autocapture_plugins/` follows the Ninjra-style manifest convention.
- Plugin code can live in core package or separate wheels; manifests are the single discovery surface.

---

## 5) Plugin System (MX Superset)

MX implements a strict plugin system compatible with Ninjra’s extension kinds and extends it for capture + runtime governance.

### 5.1 Extension kinds
MX supports (at minimum) the following kinds (superset of Ninjra’s list):

- `llm.provider`
- `embedder.text`
- `reranker.provider`
- `ocr.engine`
- `vision.extractor`
- `table.extractor`
- `compressor`
- `verifier`
- `retrieval.strategy`
- `vector.backend`
- `spans_v2.backend`
- `graph.adapter`
- `decode.backend`
- `training.pipeline`
- `research.source`
- `research.watchlist`
- `agent.job`
- `prompt.bundle`
- `ui.panel`
- `ui.overlay`

MX extensions (required):
- `capture.source`
- `capture.encoder`
- `activity.signal`
- `egress.sanitizer`
- `export.bundle`
- `import.bundle`
- `storage.blob_backend`
- `storage.media_backend`

### 5.2 Manifest schema
Each manifest file is YAML with:
- `schema_version` (int)
- `plugin_id` (string, stable)
- `version` (semver)
- `display_name`
- `description`
- `extensions`: list of extension records:
  - `kind`
  - `factory` (python import path `module:callable`)
  - `name`
  - `version`
  - `caps`: declared capabilities (strings)
  - `pillars`: per-extension declaration

#### 5.2.1 Pillars declaration for extensions
Every extension declares a `pillars` object that is enforced:

- `data_handling`:
  - `local_only: true|false`
  - `egress`:
    - `allow_cloud: true|false`
    - `allow_cloud_images: true|false`
    - `require_sanitizer: true|false`
    - `sanitizer_kind: egress.sanitizer` (reference)
- `performance`:
  - `qos_class`: `realtime | interactive | background`
  - `cpu_budget_ms_p95`
  - `io_budget_mb_s`
- `accuracy`:
  - `deterministic`: true|false
  - `validation_level`: `none | schema | strict`
- `security`:
  - `network_access`: `none | localhost | lan | internet`
  - `secrets_access`: `none | read`
  - `sandbox`: `process | inproc`
- `citable`:
  - `produces_citations`: true|false
  - `citation_granularity`: `event | span | claim`

### 5.3 Plugin discovery + enablement
- Discovery reads manifest YAML without importing plugin code.
- Enablement is explicit via settings (`settings.json`) or UX Facade.
- Enabled extensions are instantiated lazily on first use.

### 5.4 Hot-swap
Non-core plugins are hot-swappable by:
- watching manifest timestamps,
- unloading prior extension instances,
- reloading factories via `importlib.reload` for local-module plugins,
- restarting sandboxed processes for process-isolated plugins.

Hot-swap never occurs mid-request; swaps occur at safe points (between jobs) and require lease release.

### 5.5 Safe mode
Safe mode is enforced when:
- environment variable `AUTOCAPTURE_SAFE_MODE=1`, or
- config `security.safe_mode=true`.

In safe mode:
- only built-in plugins with `security.sandbox=inproc` and `network_access=none|localhost` are enabled,
- all cloud egress is blocked regardless of user settings,
- plugin manifests from external directories are ignored.

### 5.6 PolicyGate (hard enforcement)
PolicyGate is an in-process component that enforces:
- offline mode (`config.offline=true`) blocks all non-localhost network.
- cloud egress is blocked unless:
  - `privacy.cloud_enabled=true`, and
  - request payload is sanitized, and
  - extension’s `pillars.data_handling.egress.allow_cloud=true`.

PolicyGate also blocks:
- sending images to non-local providers unless `allow_cloud_images=true` and an image sanitizer is configured and executed.

All outbound requests use `core.http.EgressClient` which consults PolicyGate.

---

### 5.7 Built-in plugin suite (required)

MX ships with a complete built-in plugin set so the system is usable without any external installs.
All built-in plugin manifests live in `autocapture_plugins/` and are enabled by default unless blocked
by PolicyGate (for example, cloud providers).

Required built-in plugin IDs (minimum set):

- `mx.core.capture_win`
  - kinds: `capture.source`, `capture.encoder`, `activity.signal`
- `mx.core.storage_sqlite`
  - kinds: `storage.blob_backend`, `storage.media_backend`, `spans_v2.backend`
- `mx.core.ocr_local`
  - kinds: `ocr.engine`
- `mx.core.llm_local`
  - kinds: `llm.provider`, `decode.backend`
- `mx.core.llm_openai_compat`
  - kinds: `llm.provider` (internet egress blocked by default; requires explicit enable + sanitization)
- `mx.core.embed_local`
  - kinds: `embedder.text`
- `mx.core.vector_local`
  - kinds: `vector.backend` (qdrant sidecar + sqlite fallback)
- `mx.core.retrieval_tiers`
  - kinds: `retrieval.strategy`, `reranker.provider`
- `mx.core.compression_and_verify`
  - kinds: `compressor`, `verifier`
- `mx.core.egress_sanitizer`
  - kinds: `egress.sanitizer`
- `mx.core.export_import`
  - kinds: `export.bundle`, `import.bundle`
- `mx.core.web_ui`
  - kinds: `ui.panel`, `ui.overlay`
- `mx.prompts.default`
  - kinds: `prompt.bundle`
- `mx.training.default`
  - kinds: `training.pipeline`
- `mx.research.default`
  - kinds: `research.source`, `research.watchlist`

Each built-in manifest declares pillar metadata and is covered by Codex validation.



## 6) Storage (Encrypted, Citable, Deterministic)

### 6.1 Storage layers
- **Metadata DB**: SQLite + SQLCipher encryption (at-rest).
- **Blob store**: append-only content-addressed store for large artifacts (images/audio/video) with AEAD encryption.
- **Index store**:
  - Lexical: SQLite FTS5 tables
  - Vector: Qdrant (local sidecar) or SQLite-vec fallback
  - Graph: optional adapter-backed store (local)

### 6.2 Deterministic IDs
MX uses deterministic IDs to maximize cache hits and citation stability:
- `event_id = blake3(capture_hash + ts_bucket + process + window_title)`
- `span_id = blake3(event_id + start + end + bbox + text_hash)`
- `artifact_id = blake3(blob_bytes)`

A canonical JSON serializer is used for hashing to guarantee stable digests across platforms.

### 6.3 Provenance ledger (append-only)
Ledger entries are NDJSON with:
- `ts`
- `type` (capture|span|query|answer|export|import|plugin_change|settings_change)
- `id`
- `prev_hash`
- `hash`
- `payload` (redacted for UI display; full stored locally)

Ledger hashing:
- `hash = blake3(prev_hash + canonical_json(payload) + ts + type + id)`

Ledger guarantees:
- tamper evidence,
- traceability from answer → citations → spans → captures → blobs.

Ledger verification is available via CLI and Codex.

### 6.4 Keys
- Master key stored using Windows DPAPI; fallback to file with strict ACL if DPAPI unavailable.
- Portable key export/import uses password-based key derivation (scrypt) and encrypts a key bundle.

---

## 7) Runtime Governor and Scheduler (Invisibility Guarantees)

### 7.1 Activity signal
An `activity.signal` plugin provides:
- idle time in seconds,
- last input timestamp,
- foreground app/process,
- fullscreen indicator,
- optional CPU/GPU load signals.

### 7.2 Governor states
The governor publishes a `RuntimeState`:
- `ACTIVE_INTERACTION` (user input recently)
- `IDLE_LIGHT` (idle but system busy)
- `IDLE_DEEP` (idle and low utilization)

### 7.3 Work classes
Jobs are classified:
- `realtime`: capture sources only
- `interactive`: user query path
- `background`: ingestion, OCR, embeddings, indexing, summarization, cleanup, archive

Rules:
- During `ACTIVE_INTERACTION`, only `realtime` runs.
- During `IDLE_*`, background jobs run with strict budgets and immediate cancellation on new input.

### 7.4 Budgets + deterministic degrade markers
Every stage has:
- wall-clock budget,
- CPU budget,
- max records per batch,
- max tokens.

If a stage is skipped due to governor, MX records a deterministic degrade marker:
- stored in DB (job_run table),
- appended to ledger,
- included in context pack signals.

---

## 8) Capture Pipeline (Plugin-First)

### 8.1 Core capture record
A capture record includes:
- `capture_id`
- `captured_at_utc`
- `monitor_id`
- `frame_size` (w,h)
- `foreground_process`
- `foreground_window`
- `is_fullscreen`
- `artifact_id` for screenshot blob
- optional: `audio_artifact_id`, `video_artifact_id`
- `status` for downstream processing

### 8.2 Capture sources
Required built-in capture sources:
- Screen frames (MSS or Desktop Duplication API wrapper)
- Foreground window/process (Win32 APIs)
- Input activity signal (Win32 low-level hooks with minimal metadata; no keystroke text capture)

Optional capture sources (implemented, default off):
- Audio (WASAPI loopback)
- Browser URL collector (UIAutomation)
- App-specific collectors (e.g., VS Code via local logs) as plugins

### 8.3 Spool
Capture writes to a durable spool:
- on-disk queue directory with atomic file moves,
- DB record created before blob commit,
- idempotent reprocessing by capture_id.

---

## 9) Ingest + Spans (Citable Units)

### 9.1 Ingest stages
- Decode screenshot blob → image array (only in background or user-requested path).
- OCR extract → raw text spans with bbox.
- Normalize spans → canonical ordering, bbox normalization, stable span IDs.
- Persist spans in DB and optionally spans_v2 backend.

### 9.2 UI grounding extraction (implemented, default off)
A vision extractor can produce `ui_elements` tags with:
- schema validation,
- normalized coordinates,
- stable IDs,
- stored as event tags.

This runs only under `IDLE_DEEP` or explicit user command.

### 9.3 Table extraction
Table extractor works for:
- CSV/XLSX/JSON sources (direct parsing),
- HTML tables (parser),
- OCR-based tables from images (layout detection + cell reconstruction),
- PDF tables when text-based (pdfplumber strategy) with fallback to OCR strategy.

All extracted tables produce spans with `kind=table_cell` and citations map back to source bbox or cell coordinates.

---

## 10) Indexing

### 10.1 Lexical indexing
- SQLite FTS5 for events and threads.
- Upserts are idempotent.
- Query returns hits with stable ranking and bm25 scores.

### 10.2 Vector indexing
- Embedding service via `embedder.text` plugin.
- Vector backend via `vector.backend` plugin:
  - default: local Qdrant sidecar
  - fallback: SQLite vector table

Embeddings are computed only when:
- governor allows, or
- user query explicitly requests deep search.

### 10.3 Graph indexing
Graph adapters transform events into entities/edges.
Graph retrieval participates as an optional retrieval tier.
Graph build runs only under idle windows.

---

## 11) Retrieval (Tiered, Deterministic, Logged)

### 11.1 Tier planner
Retrieval runs as a tiered pipeline:
1. FAST: lexical search only
2. FUSION: lexical + vector + graph with reciprocal rank fusion
3. RERANK: cross-encoder reranker on fused candidates

Tier planner decides escalation based on:
- evidence count,
- score gaps,
- time budget,
- governor state.

### 11.2 Deterministic fusion + tie-breakers
RRF fusion is deterministic:
- primary: fused score
- secondary: best rank across engines
- tertiary: stable id

All tier decisions and skipped reasons are logged and stored in `retrieval_hit` table.

### 11.3 Retrieval signals
The context pack includes retrieval signals:
- tier used
- per-engine scores/ranks
- candidate set size
- skipped tiers with reasons
- latency and budget consumption

---

## 12) Context Pack (Citable, Sanitizable, Token-Efficient)

### 12.1 Format
Context pack supports:
- JSON (canonical schema)
- TRON (token-efficient text format)

### 12.2 Evidence item structure
Each evidence item includes:
- event metadata (timestamp, app, window, domain)
- snippet text
- spans with bbox/bbox_norm
- artifact references (local paths only)
- retrieval scores
- sanitation flag and entity token map

### 12.3 Sanitization
When cloud egress is enabled:
- entity hashing replaces detected entities deterministically (PERSON_XXXX, ORG_XXXX, EMAIL_XXXX, etc).
- original entity map is kept locally only.

Sanitization is performed by `egress.sanitizer` plugin and recorded in ledger with a stable run id.

---

## 13) Answer Orchestration (Claim-Level Citations + Verification)

### 13.1 Answer contract
Every answer returned to user contains:
- `answer_text`
- `claims`: list of claims
- `citations`: claim → list of span references
- `confidence` per claim
- `no_evidence` flag when applicable
- `provenance`: ledger ids for query and answer

### 13.2 Claim generation
Answer generation uses a strict schema output enforced by Gateway:
- model must output structured JSON with claims and citations.
- citations reference span_ids only (not raw text).

### 13.3 Citation validation gate
Before returning an answer:
- verify cited span_ids exist,
- verify span text range matches snippet bounds,
- verify bbox coordinates are valid,
- compute coverage score (claims with at least one valid citation).

If validation fails:
- either re-ask the model with stricter instructions (local only), or
- return a deterministic NO EVIDENCE response.

### 13.4 Entailment verifier
A verifier plugin checks each claim against cited spans:
- local LLM or ruleset,
- returns supported/unsupported/uncertain.

Unsupported claims are removed or rewritten with qualifiers; the final answer cannot include unsupported claims.

### 13.5 Conflict awareness
If conflict detector finds contradictory evidence:
- answer must explicitly present the conflict,
- include timestamps and citations for both sides,
- avoid silently choosing one side.

---

## 14) Gateway (Single Enforcement Point)

MX includes an OpenAI-compatible gateway service:
- enforces stage policy (local vs cloud allowed),
- enforces strict JSON schema outputs,
- enforces max tokens and safety constraints,
- routes to `llm.provider` and `decode.backend` plugins.

Gateway also provides:
- request/response logging with redaction,
- per-request provenance ledger entries.

---

## 15) Web Console (FastAPI) + UX Facade

### 15.1 UX Facade
All user actions are implemented in `ux.facade`:
- query execution
- settings preview/apply
- plugin enable/disable
- export/import
- doctor report
- storage dashboard

CLI and Web API call these same functions.

### 15.2 Settings schema (tiered)
Settings schema is generated dynamically and returned via `/api/settings/schema`.
Tiers:
- guided: safe defaults
- advanced: additional tuning
- expert: requires confirmation phrase (used for cloud enablement and other risky changes)

Settings changes require:
- preview id token,
- diff display,
- explicit confirmation when tier requires it.

### 15.3 Citation overlay
Web routes support:
- returning citation overlay images (bbox highlighting)
- returning raw span metadata for UI rendering

---

## 16) Export / Import (Encrypted Bundles)

### 16.1 Export bundles
Export produces:
- a manifest JSON (schema versioned)
- DB extracts (events/spans) in JSONL
- blobs optionally included
- optional decrypted blobs for portability
- optional zip container
- optional encryption layer (bundle-level)

Every export appends a ledger entry.

### 16.2 Import bundles
Import validates:
- manifest schema
- hashes of included files
- bundle encryption if present
- merges into local DB with stable ids preserved

---

## 17) PromptOps (MX Enhanced)

PromptOps is a first-class subsystem for improving prompts safely and deterministically.

### 17.1 Capabilities
- Snapshot sources: local files, docs, evaluation logs, gated web sources (explicit command only).
- Propose prompt updates using an LLM (local by default).
- Validate proposals:
  - Jinja2 sandbox rules
  - size and token budget limits
  - banned patterns (network exfil, tool override)
- Evaluate with harness:
  - offline test set
  - regression thresholds
  - citation coverage metrics
- Apply updates:
  - local patch application
  - optional GitHub PR creation (explicit opt-in)

### 17.2 Prompt provenance
Every prompt proposal includes:
- source snapshot hashes
- evaluation results
- diff artifact

These are stored locally and optionally appended to the repo ledger (.memory) for development traceability.

---

## 18) Training Pipelines (Implemented, Optional Dependencies)

Training is implemented as plugins:
- LoRA/QLoRA finetuning
- DPO preference training
- dataset validators and packers
- reproducible run manifests (JSON with hashes)

Training is local-only by default and respects governor budgets (never runs during active interaction unless explicitly commanded).

---

## 19) Research Scout (Model + Paper Watch)

Research scout:
- tracks watchlists (tags, sources)
- fetches updates when explicitly run and network allowed
- caches results for offline runs
- computes diffs and thresholds
- emits machine-readable report JSON and human-readable summary

---

## 20) Observability (Single-Machine Production)

MX includes:
- OpenTelemetry traces for major stages
- Prometheus metrics endpoint
- structured logs with redaction
- dashboards as JSON artifacts

Observability data is local by default; exports require explicit user action and sanitization.

---

## 21) Pillar Gates + CI

MX ships the following gates as runnable tools and Codex-integrated checks:
- privacy regression scanner
- provenance chain verifier
- citation integrity simulation
- retrieval sensitivity regression
- latency budget regression
- conflict scenario suite
- coverage regression

CI runs:
- lint + format
- unit tests
- pillar gates
- codex validate

Any failure blocks shipping.

---

## 22) Codex CLI (Dynamic Validation)

Codex is the enforcement tool that validates repository completeness against the embedded spec.

### 22.1 Commands
- `autocapture codex validate`  
  Produces a JSON report and non-zero exit code on failures.
- `autocapture codex explain <REQ_ID>`  
  Shows rationale, pillar mapping, and how it is validated.
- `autocapture codex list`  
  Lists all requirements with status.
- `autocapture codex pillar-gates`  
  Runs pillar gate suite and stores artifacts.

### 22.2 Validation sources
Codex validates using:
- file/path existence
- python import checks
- plugin manifest loading
- schema validation (Pydantic/JSONSchema)
- ephemeral runtime spin-up to test API endpoints
- deterministic output checks (golden fixtures)

Codex produces:
- `artifacts/codex_report.json`
- `artifacts/pillar_reports/*.json`

---

## Appendix A) Codex Requirement Spec (Machine‑Readable)

This YAML block is authoritative for Codex. Any change to requirements must update this block.

```yaml
codex_spec_version: 1
blueprint_id: autocapture_mx_blueprint_2026_01_25

requirements:

  - id: MX-CONFIG-0001
    title: Configuration loader with safe defaults (offline, cloud disabled)
    pillars: [P1, P3]
    artifacts:
      - autocapture/config/models.py
      - autocapture/config/load.py
      - autocapture/config/defaults.py
    validators:
      - type: python_import
        target: autocapture.config.load:load_config
      - type: unit_test
        target: tests/test_config_defaults.py


  - id: MX-RETENTION-0001
    title: Archive-only user data management (no delete or purge surfaces)
    pillars: [P3, P4]
    artifacts:
      - autocapture/ux/facade.py
      - autocapture/web/api.py
    validators:
      - type: cli_output_regex_absent
        command: ["autocapture", "--help"]
        patterns:
          - "\\bdelete\\b"
          - "\\bpurge\\b"
          - "\\bwipe\\b"
      - type: http_routes_absent
        must_not_include_paths:
          - "/api/delete"
          - "/api/purge"
          - "/api/wipe"

  - id: MX-CORE-0001
    title: Deterministic IDs + canonical hashing utilities
    pillars: [P1, P2, P4]
    artifacts:
      - autocapture/core/hashing.py
      - autocapture/core/ids.py
      - autocapture/core/jsonschema.py
    validators:
      - type: unit_test
        target: tests/test_hashing_canonical.py
      - type: unit_test
        target: tests/test_ids_stable.py

  - id: MX-PLUGIN-0001
    title: Plugin manifest schema + manager + discovery
    pillars: [P1, P2, P3, P4]
    artifacts:
      - autocapture/plugins/manifest.py
      - autocapture/plugins/manager.py
      - autocapture/plugins/kinds.py
    validators:
      - type: python_import
        target: autocapture.plugins.manager:PluginManager
      - type: python_import
        target: autocapture.plugins.manifest:ExtensionManifest
      - type: unit_test
        target: tests/test_plugin_discovery_no_import.py
      - type: cli_json
        command: ["autocapture", "plugins", "list", "--json"]
        must_contain_json_keys: ["plugins", "extensions"]


  - id: MX-KINDS-0001
    title: Plugin kind registry includes required baseline and MX kinds
    pillars: [P2, P3]
    artifacts:
      - autocapture/plugins/kinds.py
    validators:
      - type: unit_test
        target: tests/test_plugin_kinds_registry.py


  - id: MX-PLUGSET-0001
    title: Built-in plugin set covers essential kinds and is enabled by default
    pillars: [P1, P2, P3, P4]
    artifacts:
      - autocapture_plugins/
    validators:
      - type: plugins_have_ids
        required_plugin_ids:
          - mx.core.capture_win
          - mx.core.storage_sqlite
          - mx.core.ocr_local
          - mx.core.llm_local
          - mx.core.llm_openai_compat
          - mx.core.embed_local
          - mx.core.vector_local
          - mx.core.retrieval_tiers
          - mx.core.compression_and_verify
          - mx.core.egress_sanitizer
          - mx.core.export_import
          - mx.core.web_ui
          - mx.prompts.default
          - mx.training.default
          - mx.research.default
      - type: plugins_have_kinds
        required_kinds:
          - capture.source
          - capture.encoder
          - activity.signal
          - storage.blob_backend
          - storage.media_backend
          - spans_v2.backend
          - ocr.engine
          - llm.provider
          - decode.backend
          - embedder.text
          - vector.backend
          - retrieval.strategy
          - reranker.provider
          - compressor
          - verifier
          - egress.sanitizer
          - export.bundle
          - import.bundle
          - ui.panel
          - ui.overlay
          - prompt.bundle
          - training.pipeline
          - research.source
          - research.watchlist
      - type: cli_exit
        command: ["autocapture", "plugins", "verify-defaults"]
        expected_exit_code: 0

  - id: MX-PLUGIN-0002
    title: Plugin hot-swap for non-core plugins
    pillars: [P1, P2]
    artifacts:
      - autocapture/plugins/manager.py
    validators:
      - type: unit_test
        target: tests/test_plugin_hotswap.py

  - id: MX-PLUGIN-0003
    title: Safe mode restricts external plugins and blocks cloud egress
    pillars: [P3]
    artifacts:
      - autocapture/plugins/manager.py
      - autocapture/plugins/policy_gate.py
    validators:
      - type: unit_test
        target: tests/test_safe_mode.py

  - id: MX-POLICY-0001
    title: PolicyGate enforced network egress control
    pillars: [P1, P3]
    artifacts:
      - autocapture/plugins/policy_gate.py
      - autocapture/core/http.py
    validators:
      - type: python_import
        target: autocapture.plugins.policy_gate:PolicyGate
      - type: unit_test
        target: tests/test_policy_gate.py

  - id: MX-SAN-0001
    title: Egress sanitizer with deterministic entity hashing for text
    pillars: [P2, P3, P4]
    artifacts:
      - autocapture/memory/entities.py
      - autocapture/ux/redaction.py
    validators:
      - type: unit_test
        target: tests/test_entity_hashing_stable.py
      - type: unit_test
        target: tests/test_sanitizer_no_raw_pii.py

  - id: MX-GOV-0001
    title: RuntimeGovernor blocks heavy work during active interaction
    pillars: [P1, P3]
    artifacts:
      - autocapture/runtime/governor.py
      - autocapture/runtime/activity.py
      - autocapture/runtime/scheduler.py
      - autocapture/runtime/budgets.py
    validators:
      - type: unit_test
        target: tests/test_governor_gating.py

  - id: MX-LEASE-0001
    title: Work leases prevent duplicate processing and support cancellation
    pillars: [P1, P2]
    artifacts:
      - autocapture/runtime/leases.py
    validators:
      - type: unit_test
        target: tests/test_work_leases.py

  - id: MX-STORE-0001
    title: Encrypted metadata DB + media blob encryption + portable keys
    pillars: [P1, P3, P4]
    artifacts:
      - autocapture/storage/database.py
      - autocapture/storage/sqlcipher.py
      - autocapture/storage/keys.py
      - autocapture/storage/media_store.py
      - autocapture/storage/blob_store.py
    validators:
      - type: unit_test
        target: tests/test_key_export_import_roundtrip.py
      - type: unit_test
        target: tests/test_sqlcipher_roundtrip.py
      - type: unit_test
        target: tests/test_blob_encryption_roundtrip.py

  - id: MX-LEDGER-0001
    title: Provenance ledger hash chain + verification CLI
    pillars: [P2, P4]
    artifacts:
      - autocapture/pillars/citable.py
      - autocapture/core/hashing.py
      - autocapture/storage/archive.py
    validators:
      - type: unit_test
        target: tests/test_provenance_chain.py
      - type: cli_exit
        command: ["autocapture", "provenance", "verify"]
        expected_exit_code: 0


  - id: MX-RULES-0001
    title: Append-only rules ledger with state rebuild and query integration
    pillars: [P2, P4]
    artifacts:
      - autocapture/rules/ledger.py
      - autocapture/rules/store.py
      - autocapture/rules/schema.py
      - autocapture/rules/cli.py
    validators:
      - type: unit_test
        target: tests/test_rules_ledger_append_only.py
      - type: unit_test
        target: tests/test_rules_state_rebuild.py

  - id: MX-CAPTURE-0001
    title: Capture pipeline writes durable spool records and encrypted screenshots
    pillars: [P1, P3, P4]
    artifacts:
      - autocapture/capture/spool.py
      - autocapture/capture/pipelines.py
      - autocapture/capture/models.py
    validators:
      - type: unit_test
        target: tests/test_capture_spool_idempotent.py

  - id: MX-INGEST-0001
    title: Ingest pipeline produces normalized spans with stable IDs
    pillars: [P1, P2, P4]
    artifacts:
      - autocapture/ingest/normalizer.py
      - autocapture/ingest/spans.py
    validators:
      - type: unit_test
        target: tests/test_span_ids_stable.py
      - type: unit_test
        target: tests/test_span_bbox_norm.py

  - id: MX-TABLE-0001
    title: Table extractor supports structured + image + pdf strategies
    pillars: [P2, P4]
    artifacts:
      - autocapture/plugins/kinds.py
    validators:
      - type: unit_test
        target: tests/test_table_extractor_strategies.py

  - id: MX-INDEX-0001
    title: Lexical indexing via SQLite FTS5 for events and threads
    pillars: [P1, P2]
    artifacts:
      - autocapture/indexing/lexical.py
    validators:
      - type: unit_test
        target: tests/test_fts_query_returns_hits.py

  - id: MX-INDEX-0002
    title: Vector indexing using embedder plugins and vector backend
    pillars: [P1, P2]
    artifacts:
      - autocapture/indexing/vector.py
    validators:
      - type: unit_test
        target: tests/test_vector_index_roundtrip.py

  - id: MX-INDEX-0003
    title: Local Qdrant sidecar supported as vector backend
    pillars: [P1]
    artifacts:
      - autocapture/indexing/vector.py
      - autocapture/tools/vendor_windows_binaries.py
    validators:
      - type: unit_test
        target: tests/test_qdrant_sidecar_healthcheck.py

  - id: MX-GRAPH-0001
    title: Graph adapter interface + optional retrieval tier integration
    pillars: [P2]
    artifacts:
      - autocapture/indexing/graph.py
    validators:
      - type: unit_test
        target: tests/test_graph_adapter_contract.py

  - id: MX-RETR-0001
    title: Tiered retrieval (FAST/FUSION/RERANK) + deterministic fusion
    pillars: [P1, P2, P4]
    artifacts:
      - autocapture/retrieval/tiers.py
      - autocapture/retrieval/fusion.py
      - autocapture/retrieval/rerank.py
      - autocapture/retrieval/signals.py
    validators:
      - type: unit_test
        target: tests/test_rrf_fusion_determinism.py
      - type: unit_test
        target: tests/test_tier_planner_escalation.py

  - id: MX-CTX-0001
    title: Context pack JSON + TRON formats with retrieval signals
    pillars: [P1, P4]
    artifacts:
      - autocapture/memory/context_pack.py
      - autocapture/retrieval/signals.py
    validators:
      - type: unit_test
        target: tests/test_context_pack_formats.py

  - id: MX-ANS-0001
    title: Claim-level citations + citation validation + verifier enforced
    pillars: [P2, P4]
    artifacts:
      - autocapture/memory/answer_orchestrator.py
      - autocapture/memory/citations.py
      - autocapture/memory/verifier.py
      - autocapture/memory/conflict.py
    validators:
      - type: unit_test
        target: tests/test_citation_validation.py
      - type: unit_test
        target: tests/test_verifier_enforced.py
      - type: unit_test
        target: tests/test_conflict_reporting.py

  - id: MX-GATEWAY-0001
    title: OpenAI-compatible gateway enforces schema + stage routing + policy gate
    pillars: [P1, P2, P3, P4]
    artifacts:
      - autocapture/gateway/app.py
      - autocapture/gateway/router.py
      - autocapture/gateway/schemas.py
    validators:
      - type: unit_test
        target: tests/test_gateway_schema_enforced.py
      - type: unit_test
        target: tests/test_gateway_policy_block_cloud_default.py

  - id: MX-UX-0001
    title: UX Facade is the single surface for UI and CLI parity
    pillars: [P2, P3]
    artifacts:
      - autocapture/ux/facade.py
      - autocapture/ux/models.py
    validators:
      - type: python_import
        target: autocapture.ux.facade:UXFacade
      - type: unit_test
        target: tests/test_ux_facade_parity.py

  - id: MX-SETTINGS-0001
    title: Tiered settings schema + preview tokens + apply confirmation
    pillars: [P3]
    artifacts:
      - autocapture/ux/settings_schema.py
      - autocapture/ux/preview_tokens.py
      - autocapture/web/routes/settings.py
    validators:
      - type: unit_test
        target: tests/test_settings_preview_tokens.py
      - type: http_endpoint
        method: GET
        path: /api/settings/schema
        expects_json_keys: ["schema_version", "tiers", "sections"]

  - id: MX-WEB-0001
    title: Web Console API routes present and return validated schemas
    pillars: [P1, P3, P4]
    artifacts:
      - autocapture/web/api.py
      - autocapture/web/routes/query.py
      - autocapture/web/routes/citations.py
      - autocapture/web/routes/plugins.py
      - autocapture/web/routes/health.py
      - autocapture/web/routes/metrics.py
    validators:
      - type: http_endpoint
        method: GET
        path: /api/health
        expects_json_keys: ["ok", "generated_at_utc"]
      - type: http_endpoint
        method: POST
        path: /api/query
        expects_json_keys: ["answer", "citations", "provenance"]

  - id: MX-CIT-OVERLAY-0001
    title: Citation overlay API for bounding boxes and source rendering
    pillars: [P4]
    artifacts:
      - autocapture/web/routes/citations.py
    validators:
      - type: unit_test
        target: tests/test_citation_overlay_contract.py

  - id: MX-DOCTOR-0001
    title: Doctor report summarizes environment and binary availability
    pillars: [P1, P3]
    artifacts:
      - autocapture/ux/models.py
      - autocapture/web/routes/health.py
    validators:
      - type: unit_test
        target: tests/test_doctor_report_schema.py

  - id: MX-OBS-0001
    title: Observability via OTel traces and Prometheus metrics
    pillars: [P1, P2]
    artifacts:
      - autocapture/web/routes/metrics.py
    validators:
      - type: unit_test
        target: tests/test_metrics_endpoint_exposes_counters.py

  - id: MX-EXPORT-0001
    title: Export/import bundles with manifest + hash verification
    pillars: [P2, P3, P4]
    artifacts:
      - autocapture/storage/archive.py
    validators:
      - type: unit_test
        target: tests/test_export_import_roundtrip.py

  - id: MX-VENDOR-0001
    title: Vendor binaries tool supports Qdrant and FFmpeg with hash verification
    pillars: [P1, P3]
    artifacts:
      - autocapture/tools/vendor_windows_binaries.py
    validators:
      - type: unit_test
        target: tests/test_vendor_binaries_hashcheck.py

  - id: MX-PROMPTOPS-0001
    title: PromptOps propose/validate/evaluate/apply with deterministic diffs
    pillars: [P2, P3, P4]
    artifacts:
      - autocapture/promptops/propose.py
      - autocapture/promptops/validate.py
      - autocapture/promptops/evaluate.py
      - autocapture/promptops/patch.py
      - autocapture/promptops/github.py
    validators:
      - type: unit_test
        target: tests/test_promptops_validation.py

  - id: MX-TRAIN-0001
    title: Training pipelines (LoRA + DPO) with reproducible manifests
    pillars: [P1, P2, P3]
    artifacts:
      - autocapture/training/pipelines.py
      - autocapture/training/lora.py
      - autocapture/training/dpo.py
      - autocapture/training/datasets.py
    validators:
      - type: unit_test
        target: tests/test_training_manifest_schema.py

  - id: MX-RESEARCH-0001
    title: Research scout with caching and diff thresholding
    pillars: [P1, P2]
    artifacts:
      - autocapture/research/scout.py
      - autocapture/research/cache.py
      - autocapture/research/diff.py
    validators:
      - type: unit_test
        target: tests/test_research_scout_cache.py

  - id: MX-GATE-0001
    title: Pillar gate suite available and wired to codex
    pillars: [P1, P2, P3, P4]
    artifacts:
      - autocapture/tools/pillar_gate.py
      - autocapture/tools/privacy_scanner.py
      - autocapture/tools/provenance_gate.py
      - autocapture/tools/coverage_gate.py
      - autocapture/tools/latency_gate.py
      - autocapture/tools/retrieval_sensitivity.py
      - autocapture/tools/conflict_gate.py
      - autocapture/tools/integrity_gate.py
    validators:
      - type: cli_exit
        command: ["autocapture", "codex", "pillar-gates"]
        expected_exit_code: 0

  - id: MX-CODEX-0001
    title: Codex CLI validates against this blueprint spec
    pillars: [P2, P4]
    artifacts:
      - autocapture/codex/cli.py
      - autocapture/codex/spec.py
      - autocapture/codex/validators.py
      - autocapture/codex/report.py
    validators:
      - type: cli_exit
        command: ["autocapture", "codex", "validate", "--json"]
        expected_exit_code: 0
```

---

## Appendix B) Acceptance Criteria Summary

MX is accepted when:
- Codex validate passes all requirements in Appendix A.
- All pillar gates pass.
- A user query produces claim-level citations with valid span IDs and overlays.
- Heavy work is blocked during active interaction and resumes during idle.
- Cloud egress is blocked by default and cannot send raw PII.
- At-rest encryption is enabled and key export/import works.

