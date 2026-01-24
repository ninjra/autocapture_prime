# Autocapture NX Blueprint

_Date: 2026-01-24_

## Scope

This blueprint defines a **single-user**, **single-machine** Autocapture system optimized for:

- **User:** Justin only  
- **OS:** Windows 11 64-bit  
- **Hardware:** 64 GB RAM, RTX 4090  

Primary purpose: **full-fidelity personal memory**. The system must capture, store, process, and keep searchable **everything visible/typed/heard on the machine**, without local sanitization, filtering, replacement, or deletion.

Cloud usage is optional, but **any data that leaves the machine must be sanitized by default** via a privacy egress layer that replaces sensitive entities with non-reversible tokens while preserving intent.

---

## Pillars

Autocapture NX treats each pillar as a set of **executable invariants** enforced in runtime and CI.

### P1 Performant

**Invariant P1.1 Capture never stops silently**  
Capture runs continuously. Under load, the system may reduce capture quality, but must not silently stop. If capture cannot continue due to hard resource exhaustion (e.g., disk full), the system must alert immediately and require explicit user action.

**Invariant P1.2 Foreground compute isolation**  
When the user is actively using the machine, all non-capture compute is stopped within a fixed deadline. Capture remains active.

**Invariant P1.3 No user-visible lag**  
Capture must not introduce input/UI lag. Backpressure must be absorbed by deterministic quality adaptation and buffering.

**Invariant P1.4 Explicit user intent can spend resources**  
On a user query, the system may run heavier decode/extraction even if the user is active, bounded by budgets.

### P2 Accurate

**Invariant P2.1 Full-fidelity local evidence**  
Locally stored evidence must be exact and unredacted. No “privacy transformations” are applied to local capture, storage, or indexing.

**Invariant P2.2 Deterministic interpretation**  
Time parsing, query planning, retrieval tie-breaks, citation mapping, and sanitization must be deterministic for identical inputs.

**Invariant P2.3 High recall by design**  
If some evidence is not yet extracted/indexed, queries must trigger targeted on-demand extraction so recent activity remains searchable.

### P3 Secure

**Invariant P3.1 Encrypted at rest**  
All persisted evidence (media + metadata) is encrypted by default.

**Invariant P3.2 Sanitized egress by default**  
Any outbound network request is routed through a mandatory egress gateway that sanitizes payloads unless explicitly overridden.

**Invariant P3.2.1 No raw evidence to cloud by default**  
Cloud providers receive only a **sanitized reasoning packet** (structured facts + typed tokens), not raw screenshots, raw OCR text dumps, or raw input streams.

**Invariant P3.3 No plugin network bypass**  
Plugins do not get direct network access. Only the egress gateway can perform outbound requests.

**Invariant P3.4 Auditability**  
All significant actions affecting evidence, processing, retrieval, and egress are recorded in an append-only ledger.

### P4 Citable

**Invariant P4.1 Claim-level citations**  
Answers are emitted as claims with citations referencing immutable local evidence spans.

**Invariant P4.2 Tamper-evident provenance**  
All pipeline actions are recorded in a hash-chained ledger with periodic anchoring.

**Invariant P4.3 Reproducible retrieval**  
Given the same query and the same stores, retrieval produces stable results within defined tie-break rules and versioned indices.

---

## Non-negotiables for the Justin profile

- Capture and retain **all** screens, windows, audio, and input events available to the system.  
- Do not locally mask, filter, redact, replace, or delete evidence.  
- Do not “helpfully” suppress sensitive content in local answers.  
- Egress sanitization is default and mandatory for any cloud/provider calls.

---

## Design decisions and gates

Each decision includes the required enforcement metadata.

### D1 Egress sanitization replaces local sanitization

**Decision**  
Remove privacy sanitization and exclusion from capture/processing. Introduce a dedicated **privacy egress layer** that sanitizes outbound requests by tokenizing entities while preserving intent. Local evidence remains full-fidelity.

Cloud calls use a **sanitized reasoning packet** built locally. Retrieval, citation construction, and final answer assembly remain local.

Semantic contract: sanitization must preserve **100% user-visible functionality** by using reversible local detokenization and typed placeholders so cloud reasoning can operate on structure and intent without raw personal values.

**Claims**
- **INFERENCE:** Local full-fidelity capture is required for Justin’s memory use-case.  
- **INFERENCE:** Sanitized tokenization can preserve intent better than removal for cloud reasoning.  

**Pillars improved**
- P2 Accurate, P4 Citable: no local evidence loss; citations remain faithful.
- P3 Secure: prevents accidental leakage to cloud by default.
- P1 Performant: avoids expensive real-time sanitization work.

**Pillars risked**
- P3 Secure: any sanitization bug can leak data.
- P2 Accurate: tokenization may reduce cloud model quality if poorly formatted.

**Enforcement location**
- Kernel network router (mandatory).
- `egress.gateway` plugin (only component allowed to use network).
- `privacy.egress_sanitizer` plugin (tokenization + policies).

**Regression detection**
- Semantic preservation tests: tokenized prompts must remain solvable (golden set) and detokenization must restore originals.
- “Canary secret” tests: inject unique secrets into local evidence; verify they never appear in outbound payloads.
- Network sandbox test: any plugin attempt to open a socket fails.
- Round-trip tests: sanitize → cloud-simulated response → detokenize reproduces original entities.

### D2 Explicit time model with timezone and DST rules

**Decision**  
Define and enforce a time model that stores UTC plus capture-time timezone metadata, with deterministic parsing rules for relative times and DST edges.

**Claims**
- **INFERENCE:** Without explicit timezone semantics, “yesterday 3pm” can be ambiguous.

**Pillars improved**
- P2 Accurate, P4 Citable: correct time windows and stable citations.
- P1 Performant: fewer wasted escalations due to mis-scoped retrieval.

**Pillars risked**
- P2 Accurate: incorrect DST tie-break rules can misplace events.

**Enforcement location**
- Kernel time-intent parser and query planner.
- Metadata schema fields: `ts_utc`, `tzid`, `offset_minutes`.

**Regression detection**
- Golden tests for DST transitions and ambiguous local times.
- Parse-stability tests: same input string → same interpretation JSON.

### D3 Versioned journal and ledger schemas with canonical serialization

**Decision**  
Define `journal_v1` and `ledger_v1` schemas and a strict `canonical_json` function used for hashing.

**Claims**
- **INFERENCE:** Without canonicalization, hash chains can differ across platforms/implementations.

**Pillars improved**
- P4 Citable: reproducible provenance hashes.
- P2 Accurate: deterministic replay and repair.
- P3 Secure: stronger tamper evidence.

**Pillars risked**
- P1 Performant: over-validating in hot path could add overhead.

**Enforcement location**
- Kernel-owned append-only writers: `journal.writer`, `ledger.writer`.
- Schema validation at ingest boundary, not inside capture loop.

**Regression detection**
- Cross-implementation hash fixture tests.
- Crash-replay tests: power-loss mid-write; repair is deterministic.

### D4 Separate CPU preemption from GPU VRAM release

**Decision**  
Foreground preemption is split into: (1) stop compute now, (2) release VRAM according to policy. GPU workloads run in an isolated worker group.

**Claims**
- **INFERENCE:** Suspending a process stops scheduling but does not guarantee VRAM is freed.

**Pillars improved**
- P1 Performant: reduces GPU contention during work/gaming.
- P3 Secure: minimizes GPU-resident sensitive data lifetime.

**Pillars risked**
- P1 Performant: GPU worker restart can add latency on resume.
- P2 Accurate: model warm caches lost.

**Enforcement location**
- Kernel runtime governor.
- GPU workers isolated in a dedicated process group.

**Regression detection**
- Mode transition tests: worker suspended within deadline; GPU allocations drop below threshold if measurable.
- Bench: resume latency bounded.

### D5 Encryption is deterministic and always available on the target machine

**Decision**  
On Windows 11, the system ships a deterministic encrypted metadata store and encrypted media store. No “where available” ambiguity.

**Claims**
- **NO EVIDENCE:** Packaging details for SQLCipher and Windows deployment are not proven in this document; treated as an implementation requirement.

**Pillars improved**
- P3 Secure: consistent encrypted-at-rest posture.
- P4 Citable: tamper/corruption detection improves.

**Pillars risked**
- P1 Performant: encryption overhead.
- P2 Accurate: corruption risk if key handling is wrong.

**Enforcement location**
- `storage.metadata_store` must be encrypted (SQLCipher or equivalent).
- Media envelopes always encrypted.

**Regression detection**
- Tests: DB cannot be opened without keys; media decrypts only with keys.
- Bench: DB throughput budget; media read/write throughput budget.

### D6 Key hierarchy, separation, rotation, backup

**Decision**  
Define a key hierarchy with separation between stores, deterministic derivation, and rotation recorded in the ledger.

**Claims**
- **INFERENCE:** Key separation reduces blast radius of compromise.

**Pillars improved**
- P3 Secure: safer cryptographic boundaries.
- P4 Citable: rotation events auditable.
- P2 Accurate: fewer “mystery decrypt failures”.

**Pillars risked**
- P1 Performant: re-encryption work during rotation.
- P2 Accurate: complexity increases bug surface.

**Enforcement location**
- `token_vault` and encryption envelope code.
- Rotation implemented as an IDLE-only job.

**Regression detection**
- Nonce uniqueness tests.
- Rotate-then-decrypt test suite.
- Backup/export/import key restore tests.

### D7 No deletion of local evidence, only additive derivatives and egress views

**Decision**  
Remove media TTL and deletion features for local evidence. Any “sanitization” is implemented as **derived egress/export views** that do not mutate or remove local evidence.

**Claims**
- **INFERENCE:** Automatic deletion conflicts with “memory layer” reliability.

**Pillars improved**
- P2 Accurate, P4 Citable: evidence remains available for verification.
- P1 Performant: no retention sweeps deleting data.

**Pillars risked**
- P1 Performant: storage growth can degrade IO and query speed.
- P3 Secure: larger sensitive corpus at rest increases impact of key theft.

**Enforcement location**
- Retention manager is disabled for evidence stores.
- Disk pressure manager produces alerts and requires explicit user action for any archiving.

**Regression detection**
- Tests: no retention job runs; no evidence file deletion events appear in ledger.
- Disk-pressure simulations: alerts trigger; capture quality adapts; system fails closed if disk full.

### D8 Plugin permissions, compatibility, and deny-by-default network

**Decision**  
Extend plugin manifests with explicit permissions. Network is denied to all plugins except the egress gateway. Add compatibility constraints and dependency locking.

**Claims**
- **INFERENCE:** Explicit permissions prevent accidental privilege creep.

**Pillars improved**
- P3 Secure: enforceable least privilege and egress control.
- P2 Accurate: deterministic startup and dependency resolution.

**Pillars risked**
- P1 Performant: small startup overhead.
- P2 Accurate: compatibility matrix complexity.

**Enforcement location**
- Kernel plugin registry and loader.
- Plugin host sandbox configuration.

**Regression detection**
- Tests: plugin requesting network fails unless it is `egress.gateway`.
- Lockfile mismatch fails closed.
- Contract tests for plugin RPC schemas.

### D9 Deterministic backpressure controller with hysteresis

**Decision**  
Define a deterministic backpressure controller that adapts capture quality under load without thrashing.

**Claims**
- **INFERENCE:** Without hysteresis, capture can oscillate quality rapidly.

**Pillars improved**
- P1 Performant: stable overhead under load.
- P2 Accurate: fewer hard gaps from queue overflow.

**Pillars risked**
- P2 Accurate: quality reduction can make some text harder to OCR.
- P1 Performant: controller bugs can worsen performance.

**Enforcement location**
- Kernel runtime governor controls capture settings.
- Capture source plugins must accept real-time policy updates.

**Regression detection**
- Soak tests under synthetic CPU/GPU/IO load: bounded toggles/minute and bounded queue depth.
- Regression bench: dropped frame rates within expected envelope.

### D10 Observability policy prevents leakage in logs and metrics

**Decision**  
Introduce an observability data policy that forbids evidence text/pixels in logs/metrics by default and enforces attribute allowlists.

**Claims**
- **INFERENCE:** Metrics labels and exception strings are common leakage vectors.

**Pillars improved**
- P3 Secure: reduces accidental leakage to logs.
- P1 Performant: avoids high-cardinality metrics overhead.
- P4 Citable: audit artifacts are shareable without exposing evidence.

**Pillars risked**
- P2 Accurate: debugging becomes harder without opt-in diagnostics.

**Enforcement location**
- Logging wrappers, metrics registry, OTel instrumentation layer.
- CI scanner validates callsites.

**Regression detection**
- Canary secret scan across logs/metrics/traces.
- CI fails on disallowed logging patterns.

### D11 Loopback UI security with CSRF and origin pinning

**Decision**  
Local UI and API enforce loopback binding, strict origin checks, CSRF protection, and audited config changes.

**Claims**
- **INFERENCE:** Loopback alone does not eliminate browser-based cross-origin attacks.

**Pillars improved**
- P3 Secure: reduces local attack surface.
- P4 Citable: config changes become auditable.

**Pillars risked**
- P1 Performant: minor auth overhead.
- P2 Accurate: auth/session complexity.

**Enforcement location**
- Kernel HTTP middleware.
- `ui.web` plugin uses short-lived session tokens.

**Regression detection**
- Security tests: CSRF attempts fail; origin mismatch fails.
- Gate: config write without ledger entry fails.

### D12 Retrieval determinism and embedding versioning

**Decision**  
Define tie-break rules, version indices, and enforce consistent embedding model versions per index.

**Claims**
- **INFERENCE:** Mixed embedding versions can cause unstable retrieval.

**Pillars improved**
- P2 Accurate: stable results and explainability.
- P4 Citable: reproducible evidence selection.

**Pillars risked**
- P1 Performant: re-embedding costs.
- P2 Accurate: partial migrations can cause mixed states.

**Enforcement location**
- Retrieval strategy plugin + index builders.
- Ledger records index build versions.

**Regression detection**
- Golden query suite with stable expected evidence sets.
- Mixed-index guard tests.

### D13 Windows 11 permissions and degraded modes

**Decision**  
Explicitly define required Windows capabilities and deterministic degraded behavior when unavailable.

**Claims**
- **NO EVIDENCE:** Exact permission prompts and OS policies are not proven here; treated as a deployment requirement.

**Pillars improved**
- P2 Accurate: predictable evidence coverage (no silent failure).
- P3 Secure: avoids unsafe privilege escalation.

**Pillars risked**
- P2 Accurate: degraded capture reduces recall.
- P1 Performant: extra checks at startup.

**Enforcement location**
- Doctor command and startup self-tests.
- Capability flags stored in runtime state.

**Regression detection**
- Tests with simulated capture backend failure: system surfaces actionable error and continues in best-effort mode.

### D14 Ledger anchoring in a second trust domain

**Decision**  
Anchor ledger head hashes periodically in a second storage domain to improve tamper evidence.

**Claims**
- **INFERENCE:** Local hash chain alone is weaker if an attacker can rewrite both data and ledger.

**Pillars improved**
- P4 Citable: stronger tamper evidence.
- P3 Secure: improved compromise detection.

**Pillars risked**
- P1 Performant: minimal overhead.
- P2 Accurate: additional complexity.

**Enforcement location**
- Ledger writer + anchor writer + doctor verifier.

**Regression detection**
- Tamper simulation tests: rewrite DB+ledger but not anchor → detection triggers.
- Gate: citation emission requires ledger+anchor verification.

---

## System architecture

### High-level shape

- **Kernel**: authoritative scheduler, policy enforcement, routing, and invariants.
- **Plugins**: isolated service extensions for capture, processing, retrieval, UI, and providers.
- **Stores**:
  - encrypted metadata store
  - encrypted media store
  - append-only journal files
  - append-only ledger files
  - anchor store


### Plugin system

Plugins are mandatory for extensibility, but the kernel remains the enforcement boundary.

Plugin kinds:
- `capture.source`
- `capture.audio`
- `tracking.input`
- `vision.extractor`
- `ocr.engine`
- `embedder.text`
- `retrieval.strategy`
- `reranker`
- `verifier`
- `ui.web`
- `ui.overlay`
- `storage.metadata_store`
- `storage.media_store`
- `journal.writer`
- `ledger.writer`
- `egress.gateway`
- `privacy.egress_sanitizer`

Manifest minimum fields:
- `plugin_id`, `version`, `enabled`
- `entrypoints[]`: `{ kind, id, rpc_service }`
- `permissions`: `{ filesystem, gpu, raw_input, network }` (deny by default)
- `compat`: `{ requires_kernel>=, requires_schema_versions[] }`
- `depends_on[]`
- `hash_lock`: `{ manifest_sha256, artifact_sha256 }`

Hard rules:
- `network` permission is granted only to `egress.gateway`.
- Any plugin hash change fails closed until re-approved.
- Plugins run out-of-process by default; only a tiny set of audited built-ins may run in-proc.

Pillars improved
- P3 Secure: enforceable least privilege and no network bypass.
- P2 Accurate: deterministic dependency resolution.

Pillars risked
- P1 Performant: extra IPC overhead if contracts are too chatty.

Enforcement location
- Kernel plugin loader and router.
- OS sandbox / firewall rules for plugin hosts.

Regression detection
- Integration tests that attempt direct network from non-egress plugins.
- Contract tests for RPC schema compatibility.


### Runtime modes

- `ACTIVE_CAPTURE_ONLY`: capture + minimal journaling only.
- `IDLE_DRAIN`: enrichment/indexing jobs may run, bounded by budgets.
- `USER_QUERY`: targeted on-demand decode/extract/retrieve/answer allowed under explicit user intent.

Mode transitions are governed by deterministic signals (input idle timers, fullscreen state, queue depths).

---

## Data model

### Evidence atoms

Local evidence is stored as immutable “atoms”. Derived artifacts are additive.

Atom categories:
- `media.segment`: encrypted video segment file reference
- `media.audio`: encrypted audio segment
- `frame.keyframe`: extracted still frame for indexing, derived
- `text.ocr_span`: OCR text + offsets, derived
- `text.vlm_span`: VLM extracted UI text/layout, derived
- `input.raw_event`: raw input event stream record
- `window.meta`: window title/app/rect/monitor focus events

### Identifiers

- `atom_id`: ULID or UUIDv7 (time-sortable)
- `stable_device_id`: random on install, stored in vault, never sent outbound unless explicitly enabled

### Journal schema `journal_v1`

Journal is an append-only ingestion buffer.

Required fields:
- `schema_version: 1`
- `event_id`
- `sequence`
- `ts_utc`
- `tzid`
- `offset_minutes`
- `event_type`
- `payload` (event-type specific)

### Ledger schema `ledger_v1`

Ledger is append-only provenance.

Required fields:
- `schema_version: 1`
- `entry_id`
- `ts_utc`
- `stage` (capture, extract, index, retrieve, answer, egress)
- `inputs[]` (atom_ids / hashes)
- `outputs[]` (atom_ids / hashes)
- `policy_snapshot_hash`
- `prev_hash`
- `entry_hash`

Hash chain:
- `entry_hash = SHA256(canonical_json(entry_without_entry_hash) || prev_hash)`

### Reasoning packet schema `reasoning_packet_v1`

Used only for outbound requests to cloud providers.

Fields:
- `schema_version: 1`
- `query_sanitized`
- `time_window`
- `facts[]`: each fact is `{type, ts_utc, fields}` where `fields` is a map and all user-derived string values are tokenized.
- `intent`: optional task tag for cloud model.
- `output_contract`: JSON schema or function signature required of the model.

Pillars improved
- P3 Secure: prevents raw evidence egress.
- P2 Accurate: preserves user-visible functionality by detokenization and local verification.

Pillars risked
- P2 Accurate: cloud may underperform without raw context.

Enforcement location
- Context pack builder + egress gateway.

Regression detection
- Gate tests: outbound payload must match schema and contain no raw values.

### `canonical_json`

Rules:
- UTF-8
- object keys sorted ascending
- arrays preserve order
- no NaN/Inf
- stable float encoding (or disallow floats in hashed fields)
- normalized unicode (NFC)
- no whitespace differences

---

## Capture subsystem

### Capture goals

- Full-fidelity capture of what is visible, plus audio and input events as available.
- Minimal interference during foreground use.
- Crash tolerance: on restart, journals and partially written segments are recoverable.

### Windows capture backends

Preferred:
- Desktop Duplication capture to GPU surface, encoded with NVENC.

Fallbacks:
- If Desktop Duplication fails, use a fallback backend (implementation-specific).

**Claims**
- **NO EVIDENCE:** Exact backend availability and behavior under all Windows configurations must be validated by an integration test matrix.

### Video segmentation

- Segment duration is fixed (e.g., 30–120 seconds) and encoded once.
- Segment metadata is journaled:
  - segment start/end timestamps
  - monitors captured
  - encoder settings used
  - file hash of encrypted blob

### Backpressure controller

Controller inputs:
- capture loop step latency
- encode queue depth
- disk write latency
- CPU utilization
- GPU utilization (if available)
- fullscreen or high-priority app signal (optional)

Controller outputs:
- `fps_target`
- `bitrate_target`
- `keyframe_interval`
- `segment_seconds`
- optional downscale factor for new segments

Stability rules:
- minimum dwell time per setting (hysteresis)
- bounded step changes per decision interval
- never reduce below a minimum “audit” quality threshold unless disk is critically low

Pillars improved
- P1 Performant: bounded overhead, avoids thrashing.
- P2 Accurate: prevents hard capture gaps.

Pillars risked
- P2 Accurate: lower quality can reduce OCR accuracy.

Enforcement location
- Kernel governor; capture plugin applies updates.

Regression detection
- Soak tests under synthetic load with bounded toggles and bounded dropped frames.

### Audio capture

- Capture system audio and microphone as separate streams where possible.
- Synchronize via shared monotonic clock converted to UTC timestamps.

### Input capture

Modes:
- `raw`: record key press/release, mouse events, and modifiers.
- `activity_only`: record only coarse activity signals (no key codes).
- `off`

Justin profile default: `raw` (full memory), with explicit “leak to cloud protection” via egress sanitizer.

### Window and focus metadata

Record:
- active window title
- process name
- window rect
- monitor id
- z-order changes if available

Used for:
- fast timeline navigation
- coarse search even before OCR/VLM extraction

Pillars improved
- P2 Accurate: preserves full raw evidence for later extraction.
- P4 Citable: enables provenance linking from windows to segments.

Pillars risked
- P1 Performant: high-fidelity capture can increase IO/encode load.

Enforcement location
- Kernel governor + capture source plugin.
- Journal writer.

Regression detection
- Bench: capture loop latency and dropped frames under load.
- Soak: restart recovery from journals.

---

## Processing pipeline

### Scheduling

- In `ACTIVE_CAPTURE_ONLY`: no extraction or indexing.
- In `IDLE_DRAIN`: run backlog jobs, GPU-accelerated.
- In `USER_QUERY`: run targeted extraction for query window if needed.

### Extractors

Default chain:
1. VLM UI extractor for layout and text
2. OCR engine fallback for high-density text areas
3. Optional code/table extractors for structured artifacts

All derived outputs are stored as new immutable atoms linked to source segments/frames.

---

## Model strategy

Default posture: run **local models** on the RTX 4090 for OCR, VLM extraction, embeddings, and (optionally) answer generation. Cloud models are optional and always routed through egress sanitization.

**Claims**
- **NO EVIDENCE:** Exact model choices and runtimes (TensorRT, DirectML, CUDA) are implementation-dependent; treated as pluggable.

Recommended default plugin kinds:
- `vision.extractor`: local GPU VLM
- `ocr.engine`: local OCR
- `embedder.text`: local embedding model
- `llm.provider`: local LLM for draft/judge
- `llm.provider`: optional cloud LLM, sanitized

Pillars improved
- P1 Performant: avoids network latency; uses GPU during IDLE and USER_QUERY.
- P3 Secure: minimizes need to send context to cloud.
- P2 Accurate: enables richer extraction with on-demand escalation.

Pillars risked
- P1 Performant: local model load time and VRAM pressure.
- P2 Accurate: local models may underperform some cloud models.

Enforcement location
- Kernel model registry and stage router.
- GPU worker isolation and VRAM release policy.

Regression detection
- Bench: model load and first-token latency.
- Tests: ensure local stages run without network; ensure cloud stages are sanitized.

### Indexing

- Lexical index over extracted spans and window metadata.
- Vector embeddings over extracted spans and summaries.
- Versioned indices; rebuildable without mutating atoms.

Pillars improved
- P2 Accurate: richer extraction increases recall.
- P1 Performant: idle gating prevents foreground impact.

Pillars risked
- P1 Performant: extraction backlog can grow if idle is rare.

Enforcement location
- Scheduler policy + job leases.
- Runtime mode gates.

Regression detection
- Backlog growth tests and micro-idle scheduling tests.

---

## Retrieval and answering

### Time intent parsing

Input: natural language time constraints and query text.  
Output: deterministic `time_window` object with explicit timezone assumptions.

Rules:
- Resolve relative times in configured user timezone (default: capture-time tz unless overridden).
- DST ambiguity resolved by explicit tie-break rule stored in interpretation.

### Tiered retrieval planner

Tiers:
- Tier 0: window metadata + lexical search over already extracted spans
- Tier 1: vector search over embeddings
- Tier 2: targeted decode/extract for missing windows
- Tier 3: optional rerankers/verifiers

Planner is deterministic and emits a retrieval trace.

### Tie-break rules

Stable ordering:
1. score descending
2. timestamp descending
3. atom_id ascending

### Answer graph and citations

- Produce claim objects with citations referencing immutable text spans.
- Validator fails closed if citations cannot be resolved.

Pillars improved
- P4 Citable: claim-level citations are verifiable.
- P2 Accurate: tiered retrieval reduces misses.

Pillars risked
- P1 Performant: USER_QUERY decode/extract can be expensive.

Enforcement location
- Retrieval planner + answer graph validators.

Regression detection
- Golden query suite and citation validation suite.

---

## Privacy egress layer

### Goals

- Never leak raw personal data to cloud by default.
- Preserve intent and task functionality for cloud reasoning.
- Enable local de-tokenization so Justin sees original values.
- No telemetry or background network traffic by default. Any network use is explicit and routed through the egress gateway.

### Network egress architecture

- All outbound requests must go through `egress.gateway`.
- All provider plugins are “networkless”; they call the gateway.
- Gateway applies:
  - payload sanitization
  - allow/deny policies
  - request logging without payload content

Cloud provider requests are formed from a `reasoning_packet_v1` object:
- `query_sanitized`
- `facts[]` (structured events/actions; all variable strings tokenized)
- `time_window`
- `constraints`
- optional `citations_stub[]` (IDs only, no raw text)

Rule: the gateway rejects any outbound payload that contains raw evidence fields unless `allow_raw_egress=true`.

### Secure entity tokenization

Sanitization is implemented as an ordered **egress transform chain**:

1. `entity.tokenize` (default, mandatory)
2. Optional transforms (user-enabled):
   - `strip.social_handles`
   - `strip.credit_cards`
   - `strip.emails`
   - `strip.addresses`
   - custom regex transforms

Rules:
- Transforms only affect **egress payloads**.
- Local stores remain full-fidelity.
- If transforms would remove task-critical structure, they must instead token-replace with typed placeholders.


Entity extraction sources:
- query text
- context pack text
- optional local entity table derived from OCR/VLM outputs

Token format:
- `⟦ENT:<type>:<token>⟧`

Token generation:
- `token_full = HMAC-SHA256(entity_secret, canonical_entity_value || entity_type || scope)`
- `token = BASE32(token_full[0:16])`  # 128-bit truncated token for low collision risk

Collision rule:
- If a generated token already exists with a different original value, extend truncation length (e.g., 20 bytes) deterministically until unique.

Scope options:
- per-machine (default)
- per-provider
- per-session

Mapping:
- local entity map stores `{token -> original_value, type, first_seen_ts}` encrypted at rest.

### Egress sanitization algorithm

1. Build entity candidates from payload using a deterministic recognizer stack:
   - Tier A: regex and checksum validators (SSN, credit card, email, phone)
   - Tier B: local NER model for names/addresses/orgs (runs locally)
   - Tier C: optional local LLM-based PII detector for hard cases (runs locally)
   - Tier D: user-configured custom regex and allow/deny lists
2. Replace exact matches with typed tokens.
3. Add a minimal entity glossary to the payload so the cloud model retains intent:
   - example: “⟦ENT:SSN:abc⟧ is an SSN identifier”
4. Run a final leak check: ensure no original entity values remain.
5. If sanitization cannot prove it removed all known sensitive values, **block egress** and fall back to a local model path (default) or require explicit override.
6. Emit ledger entry of type `egress.sanitize` with hashes only.

### Cloud responses

- Cloud responses may contain tokens.
- Before display or storage, detokenize tokens back to original values locally.
- If cloud returns any raw sensitive values that match local entity map originals, treat as a sanitizer failure and block.

### Cloud images

Default posture:
- Do not send raw screenshots to cloud.
If enabled:
- Prefer sending structured local extracts (layout + sanitized text) instead of pixels.
- If pixels must be sent, generate a derived sanitized image view that replaces detected sensitive text regions with typed tokens. This derived view is never used for local memory; it is egress-only.

Pillars improved
- P3 Secure: prevents raw leakage to cloud by default.
- P2 Accurate: detokenization preserves local answers.

Pillars risked
- P2 Accurate: cloud reasoning quality may drop if tokens are mishandled.

Enforcement location
- Egress gateway + sanitizer + leak checker.

Regression detection
- Canary secret egress tests; detokenization correctness tests.

---

## Storage

### Retention

Justin profile:
- Evidence retention is indefinite.
- No automatic deletion of evidence.

Disk pressure behavior:
- Alerts at configurable thresholds.
- Quality adapts for new capture if necessary.
- If disk becomes full, capture fails closed with an immediate on-screen alert requiring user action. No silent deletion.

### Metadata store

- Encrypted by default.
- Contains:
  - atoms table
  - spans and offsets
  - embeddings with `embedding_model_id`
  - retrieval traces
  - query history
  - entity token map

### Media store

- Encrypted blobs on filesystem.
- Content hash refers to encrypted blob bytes plus envelope metadata.

### Ledger and anchors

- Ledger is stored as append-only NDJSON.
- Anchor store records periodic `(ts_utc, ledger_head_hash, anchor_seq)` entries in a second domain.

Windows anchor implementation options (choose one):
- DPAPI-protected registry value with monotonic `anchor_seq`
- Windows Credential Manager secret with last-seen head hash
- separate DPAPI-protected file outside the main data directory

Pillars improved
- P4 Citable: stronger provenance verification.
- P2 Accurate: indefinite retention preserves recall.

Pillars risked
- P1 Performant: storage growth can slow queries.

Enforcement location
- Storage layer + doctor checks.

Regression detection
- DB performance benches at increasing sizes.
- Integrity and anchor verification tests.

---

## Security and operations

### Key hierarchy

Root material:
- `K_root` stored in Windows Credential Manager or DPAPI-protected vault file.

Derived keys:
- `K_media = HKDF(K_root, info="media")`
- `K_meta  = HKDF(K_root, info="metadata")`
- `K_entity = HKDF(K_root, info="entity_tokens")`

Per-object media key:
- `K_obj = HKDF(K_media, info=object_id)`
- AES-GCM nonce is generated randomly per object and stored in envelope metadata.

Separation rules:
- Never reuse the same derived key across media, metadata, and entity tokenization.
- Entity token HMAC uses `K_entity` only.

Rotation:
- Rotation creates a new `K_root'` and re-wraps or re-encrypts stores in `IDLE_DRAIN`.
- Rotation events are recorded in the ledger and anchored.

Pillars improved
- P3 Secure: blast-radius reduction via key separation.
- P4 Citable: auditable rotation.

Pillars risked
- P1 Performant: rotation is expensive.

Enforcement location
- Vault + crypto envelope implementation.
- Rotation job runner in IDLE mode.

Regression detection
- Nonce uniqueness tests; rotate-and-decrypt tests.

### Plugin sandboxing

Windows-first posture:
- plugin hosts run with restricted filesystem access
- no direct network access unless plugin_id is `egress.gateway`
- process isolation by default

### Local UI and API

- Loopback binding only by default.
- Session-based auth tokens in vault.
- CSRF and origin checks for browser UI.
- Config changes always recorded to ledger.

### Observability

- Metrics and traces avoid evidence payloads by default.
- Optional debug session mode requires explicit unlock and is time-limited.

### Doctor command

Deterministic checks:
- capture backend operational
- encryption enabled
- plugin lockfile valid
- ledger integrity + anchor verification
- egress gateway enforcement active
- disk headroom above threshold

### CI gates

- Pillar gates P1–P4
- Provenance gate
- Leak-prevention gate for egress
- Latency and capture overhead benches
- Frozen surface gates for:
  - schemas
  - canonical_json
  - time intent parser outputs
  - token formats and sanitizer behavior


Pillars improved
- P3 Secure: explicit enforcement and verification.
- P4 Citable: frozen surfaces keep outputs reproducible.

Pillars risked
- P1 Performant: more gates add CI time (not runtime).

Enforcement location
- CI pipeline + kernel runtime checks.

Regression detection
- Gate failures on any schema/time/sanitizer drift.

---

## Redteam scenarios

This section is from the “Justin memory layer” perspective.

### R1 Missing capture

Failure modes:
- capture backend crashes
- encoder stalls
- disk full

Mitigations:
- journal-first design with restart replay
- supervisor restarts capture process
- disk pressure alerts and quality adaptation
- explicit failure signaling in UI

Regression detection:
- long-run soak tests with forced backend crashes
- disk-fill simulation tests

### R2 Unsanitized egress

Failure modes:
- provider plugin bypasses gateway
- sanitizer misses an entity pattern
- logs accidentally contain evidence

Mitigations:
- deny-by-default network permissions
- mandatory gateway routing
- layered recognizers + canary secret tests
- observability allowlists

Regression detection:
- integration tests that inspect outbound requests for canary secrets
- static scanning of logging calls

### R3 “Searchable at all times” violated

Failure modes:
- user queries immediately after activity; extraction backlog not processed

Mitigations:
- USER_QUERY mode triggers targeted on-demand extraction for the requested time window
- planner reports coverage and may widen compute budgets only on explicit intent

Regression detection:
- tests that query the last N minutes and assert retrieval includes those minutes even when idle processing is disabled

### R4 Provenance corruption

Failure modes:
- DB corruption
- ledger rewrite

Mitigations:
- encrypted stores
- hash-chained ledger
- anchor verification

Regression detection:
- tamper simulation tests and doctor verification tests

### R5 Tokenization harms cloud reasoning quality

Failure modes:
- cloud model treats tokens as noise
- coreference breaks across turns

Mitigations:
- typed token format with stable delimiters
- include entity glossary with types and constraints
- require JSON-structured outputs where tokens must be echoed exactly
- local fallback: rerun answer using local LLM if cloud output quality gates fail

Regression detection:
- golden “tokenized prompt” eval set with expected structural outputs
- detokenization success rate must be 100% for required tokens

### R6 Entity map corruption or loss

Failure modes:
- token map lost → detokenization impossible
- mismatched tokens across stores

Mitigations:
- entity map is stored encrypted in metadata store
- periodic snapshots hashed into the ledger
- export/backup includes the entity map

Regression detection:
- restore-from-backup tests: token map restores and detokenization succeeds

### R7 Time intent misinterpretation

Failure modes:
- DST ambiguity selects wrong hour
- travel changes timezone unexpectedly

Mitigations:
- interpretation JSON always shown in UI before expensive escalation
- store both capture-time tz and user-config tz
- frozen-surface tests for parser outputs

Regression detection:
- DST golden tests and property tests across time windows

### R8 GPU contention during active work

Failure modes:
- extraction job forgets to release VRAM
- encode competes with active GPU workload

Mitigations:
- GPU work only in GPU worker group
- ACTIVE transition enforces suspend + VRAM release deadline
- capture encode settings adapt under fullscreen/high GPU load

Regression detection:
- bench: VRAM release within deadline
- soak: no dropped input frames while GPU saturated

### R9 Index drift reduces recall

Failure modes:
- embeddings model updated without rebuild
- mixed versions in one index

Mitigations:
- embedding version is stored per row
- index builder refuses mixed versions
- rebuild scheduled in IDLE only

Regression detection:
- golden query recall suites across upgrades

---

---

## Default configuration

```yaml
profile: justin_full_fidelity

runtime:
  timezone: "America/Denver"
  active_window_s: 3
  idle_window_s: 45
  mode_enforcement:
    suspend_workers: true
    suspend_deadline_ms: 100
  gpu:
    release_vram_on_active: true
    release_vram_deadline_ms: 250

capture:
  video:
    enabled: true
    backend: desktop_duplication_nvenc
    segment_seconds: 60
    fps_target: 30
    resolution: native
  audio:
    system_audio: true
    microphone: true
  window_metadata:
    enabled: true
    sample_hz: 5
  input_tracking:
    mode: raw
    flush_interval_ms: 250

processing:
  idle:
    max_concurrency_gpu: 1
    max_concurrency_cpu: 2
  on_query:
    allow_decode_extract: true
    max_window_minutes: 120

storage:
  encryption_required: true
  retention:
    evidence: infinite
  disk_pressure:
    warn_free_gb: 200
    critical_free_gb: 50

privacy:
  egress:
    enabled: true
    default_sanitize: true
    allow_raw_egress: false
    reasoning_packet_only: true
    token_scope: per_provider
    recognizers:
      ssn: true
      credit_card: true
      email: true
      phone: true
      custom_regex: []
  cloud:
    enabled: false
    allow_images: false

plugins:
  safe_mode: false
  permissions:
    network_allowed_plugin_ids:
      - "builtin.egress.gateway"
  locks:
    enforce: true
```

---

## Repository layout

```text
autocapture_nx/
  kernel/
  plugins/
    builtin/
      capture/
      extract/
      retrieval/
      ui/
      egress/
      storage/
  storage/
    schemas/
    migrations/
  tests/
    unit/
    integration/
    gates/
  bench/
  docs/
```
