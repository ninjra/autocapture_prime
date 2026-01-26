# Autocapture NX Blueprint (P1–P4 Optimized)

> Rule: If any pillar regresses under the listed regression detection, do not ship.

## Pillars

- **P1 Performant**: minimize user-visible completion time; optimize end-to-end flow; keep capture invisible while user active.
- **P2 Accurate**: do not exceed evidence; no hidden assumptions; deterministic IDs/time handling; no lossy overwrite of evidence.
- **P3 Secure**: offline-by-default; network only when policy allows; fail closed for encryption/auth; least privilege for plugins.
- **P4 Citable**: every non-trivial output must be traceable to immutable evidence with verifiable provenance (hashes, ledger, anchors).

## Non-negotiable invariants

- **Plugin-first**: core behavior implemented as replaceable plugins; kernel is a minimal orchestrator.
- **Local-first capture**: capture everything locally; sanitize only on egress; cloud never sees raw PII.
- **Invisibility while active**: no OCR/VLM/embeddings/indexing/conversion while user is actively interacting; only ingest allowed.
- **Append-only evidence**: primary evidence is immutable; derived artifacts are separate records linked to parents.
- **Deterministic, verifiable provenance**: hash-chained ledger + anchors + verification CLI.

## Standard implementation patterns

These patterns are referenced by work items to avoid repetition while preserving behavior.

### Pattern A — Evidence object (immutable)

- Evidence record is **append-only** and **never overwritten**.
- Fields (minimum): `evidence_id`, `run_id`, `type`, `ts_start_utc`, `ts_end_utc`, `content_hash`, `locator`, `schema_version`.
- Stored as canonical JSON (no floats/bytes) + separate encrypted media blobs where needed.
- Ledger entry written for: `evidence.write` (includes hashes + locator digest).

### Pattern B — Derived artifact (non-destructive)

- Derived record references `parent_evidence_id` and a precise `span_ref` (time/frame/offset).
- Stored as its own immutable record; never mutates parent metadata.
- Ledger entry written for: `derived.write` (includes parent hash + method + model identity).

### Pattern C — Ledger + anchor

- Ledger is a hash chain over canonical JSON payloads.
- Anchors are periodic signed/HMAC heads of the ledger to enable tamper detection.
- Verification commands recompute chain and validate anchors.

### Pattern D — Scheduler / governor (activity-authoritative)

- User activity signal is authoritative.
- ACTIVE: ingest only. IDLE: enrichment allowed within budgets.
- All heavy work is cancellable, chunked, and preemptible.

### Pattern E — Network policy

- Kernel process is network-denied by default.
- Network is allowed only for explicitly policy-approved, subprocess-hosted plugins.
- All outbound is sanitized by default; unsanitized egress requires explicit dangerous-op enablement.

### Pattern F — Gates and regression detection

- Add gates in `tools/` that run in CI and locally via `doctor`/`verify`.
- Gates must be deterministic and have golden tests.

## Phases

Phases are ordered; later phases may start only when earlier phase exit criteria are met.

- **Phase 0: Scaffolding and gates** — Introduce CI/doctor/verify scaffolding, packaging/path hygiene, deterministic hashing.
- **Phase 1: Correctness + immutability blockers** — Fix correctness/security breakers; establish run_id + ID discipline; stop evidence mutation.
- **Phase 2: Capture pipeline refactor** — Streaming capture, backpressure, bounded memory, accurate timestamps, and correlation signals.
- **Phase 3: Storage scaling + durability** — SQLCipher/indices, binary encrypted blobs, atomic writes, recovery, compaction for derived.
- **Phase 4: Retrieval + provenance + citations** — Deterministic retrieval, derived artifacts, citation resolver, proof bundles, replay.
- **Phase 5: Scheduler/governor** — Activity-authoritative gating, budgets, preemption, telemetry integration.
- **Phase 6: Security + egress hardening** — Least privilege plugins, subprocess sandbox, key separation/rotation, egress ledgering.
- **Phase 7: FastAPI UX facade + Web Console** — Canonical UI, UX facade parity for CLI, approval workflows.
- **Phase 8: Optional expansion plugins** — Clipboard, file activity, hot-reload; only after core verification is solid.

## Coverage index (items 001–130)

Each item appears exactly once in the phase details below.

- [ ] **I001** (Phase 1) — [Eliminate floats from journal/ledger payloads](#i001)
- [ ] **I002** (Phase 1) — [Make backpressure actually affect capture rate](#i002)
- [ ] **I003** (Phase 1) — [Stop buffering whole segments in RAM; stream segments](#i003)
- [ ] **I004** (Phase 1) — [Do not write to storage from realtime audio callback](#i004)
- [ ] **I005** (Phase 1) — [Stop mutating primary evidence metadata during query](#i005)
- [ ] **I006** (Phase 1) — [Introduce globally unique run/session identifier; prefix all record IDs](#i006)
- [ ] **I007** (Phase 1) — [Make ledger writing thread-safe](#i007)
- [ ] **I008** (Phase 1) — [Make journal writing thread-safe; centralize sequences](#i008)
- [ ] **I009** (Phase 1) — [Fail closed if DPAPI protection fails when encryption_required](#i009)
- [ ] **I010** (Phase 1) — [Sort all store keys deterministically](#i010)
- [ ] **I011** (Phase 1) — [Use monotonic clocks for segment duration](#i011)
- [ ] **I012** (Phase 1) — [Align default config with implemented capture backend](#i012)
- [ ] **I013** (Phase 1) — [Remove hard-coded model paths; config-driven + portable](#i013)
- [ ] **I014** (Phase 1) — [Enforce plugin compat.requires_kernel / schema versions](#i014)
- [ ] **I015** (Phase 1) — [Verify contract lock at boot/doctor](#i015)
- [ ] **I016** (Phase 2) — [Split capture into grab → encode/pack → encrypt/write pipeline](#i016)
- [ ] **I017** (Phase 2) — [Bounded queues with explicit drop policies](#i017)
- [ ] **I018** (Phase 2) — [Replace zip-of-JPEG with real video container for primary artifact](#i018)
- [ ] **I019** (Phase 2) — [Add GPU-accelerated capture/encode backend (NVENC/DD)](#i019)
- [ ] **I020** (Phase 2) — [Record segment start/end timestamps](#i020)
- [ ] **I021** (Phase 2) — [Record capture parameters per segment](#i021)
- [ ] **I022** (Phase 2) — [Correlate frames with active window via synchronized timeline](#i022)
- [ ] **I023** (Phase 2) — [Add cursor/input correlation timeline references](#i023)
- [ ] **I024** (Phase 2) — [Disk pressure degrades capture quality before stopping](#i024)
- [ ] **I025** (Phase 2) — [Atomic segment writes (temp + os.replace)](#i025)
- [ ] **I026** (Phase 3) — [Default to SQLCipher for metadata when available](#i026)
- [ ] **I027** (Phase 3) — [Add DB indexes on ts_utc, record_type, run_id](#i027)
- [ ] **I028** (Phase 3) — [Store media in binary encrypted format (not base64 JSON)](#i028)
- [ ] **I029** (Phase 3) — [Stream encryption (avoid whole-segment in memory)](#i029)
- [ ] **I030** (Phase 3) — [Immutability/versioning in stores (put_new vs put_replace)](#i030)
- [ ] **I031** (Phase 3) — [Make record ID encoding reversible (no lossy mapping)](#i031)
- [ ] **I032** (Phase 3) — [Shard media/metadata directories by date/run](#i032)
- [ ] **I033** (Phase 3) — [Add per-run storage manifest records](#i033)
- [ ] **I034** (Phase 3) — [Configurable fsync policy (critical vs bulk)](#i034)
- [ ] **I035** (Phase 4) — [Replace full-scan query with tiered indexed retrieval](#i035)
- [ ] **I036** (Phase 4) — [Deterministic retrieval ordering (stable sort keys)](#i036)
- [ ] **I037** (Phase 4) — [Candidate-first extraction (retrieve then extract)](#i037)
- [ ] **I038** (Phase 4) — [Derived artifact records for OCR/VLM outputs](#i038)
- [ ] **I039** (Phase 4) — [Ledger query executions (inputs/outputs)](#i039)
- [ ] **I040** (Phase 4) — [Ledger extraction operations (inputs/outputs)](#i040)
- [ ] **I041** (Phase 4) — [Citations point to immutable evidence IDs + spans](#i041)
- [ ] **I042** (Phase 4) — [Citation resolver validates hashes/anchors/spans](#i042)
- [ ] **I043** (Phase 4) — [Fail closed if citations do not resolve](#i043)
- [ ] **I044** (Phase 5) — [Real scheduler plugin gates heavy work on user activity](#i044)
- [ ] **I045** (Phase 5) — [Input tracker exposes activity signals (not only journal)](#i045)
- [ ] **I046** (Phase 5) — [Capture emits telemetry (queues, drops, lag, CPU)](#i046)
- [ ] **I047** (Phase 5) — [Governor outputs feed backpressure and job admission](#i047)
- [ ] **I048** (Phase 5) — [Immediate ramp down on user input (cancel/deprioritize heavy jobs)](#i048)
- [ ] **I049** (Phase 6) — [Egress gateway must be subprocess-hosted; kernel network-denied](#i049)
- [ ] **I050** (Phase 6) — [Minimize inproc_allowlist; prefer subprocess hosting](#i050)
- [ ] **I051** (Phase 6) — [Capability bridging for subprocess plugins (real capability plumbing)](#i051)
- [ ] **I052** (Phase 6) — [Enforce least privilege per plugin manifest](#i052)
- [ ] **I053** (Phase 6) — [Enforce filesystem permission policy declared by plugins](#i053)
- [ ] **I054** (Phase 6) — [Strengthen Windows job object restrictions (limits)](#i054)
- [ ] **I055** (Phase 6) — [Sanitize subprocess env; pin caches; disable proxies](#i055)
- [ ] **I056** (Phase 6) — [Plugin RPC timeouts and watchdogs](#i056)
- [ ] **I057** (Phase 6) — [Max message size limits in plugin RPC protocol](#i057)
- [ ] **I058** (Phase 6) — [Harden hashing against symlinks / filesystem nondeterminism](#i058)
- [ ] **I059** (Phase 6) — [Secure vault file permissions (Windows ACLs)](#i059)
- [ ] **I060** (Phase 6) — [Separate keys by purpose (metadata/media/tokenization/anchor)](#i060)
- [ ] **I061** (Phase 6) — [Anchor signing (HMAC/signature) with separate key domain](#i061)
- [ ] **I062** (Phase 6) — [Add verify commands (ledger/anchors/evidence)](#i062)
- [ ] **I063** (Phase 6) — [Audit security events in ledger (key rotations, lock updates, config)](#i063)
- [ ] **I064** (Phase 6) — [Dependency pinning + hash checking (supply chain)](#i064)
- [ ] **I065** (Phase 4) — [Define canonical evidence model (EvidenceObject)](#i065)
- [ ] **I066** (Phase 4) — [Hash everything that matters (media/metadata/derived)](#i066)
- [ ] **I067** (Phase 4) — [Ledger every state transition](#i067)
- [ ] **I068** (Phase 4) — [Anchor on schedule (N entries or M minutes)](#i068)
- [ ] **I069** (Phase 4) — [Immutable per-run manifest (config+locks+versions)](#i069)
- [ ] **I070** (Phase 4) — [Citation objects carry verifiable pointers](#i070)
- [ ] **I071** (Phase 4) — [Citation resolver CLI/API](#i071)
- [ ] **I072** (Phase 4) — [Metadata immutable by default; derived never overwrites](#i072)
- [ ] **I073** (Phase 4) — [Persist derivation graphs (parent→child links)](#i073)
- [ ] **I074** (Phase 4) — [Record model identity for ML outputs](#i074)
- [ ] **I075** (Phase 4) — [Deterministic text normalization before hashing](#i075)
- [ ] **I076** (Phase 4) — [Proof bundles export (evidence + ledger slice + anchors)](#i076)
- [ ] **I077** (Phase 4) — [Replay mode validates citations without model calls](#i077)
- [ ] **I078** (Phase 7) — [FastAPI UX facade as canonical interface](#i078)
- [ ] **I079** (Phase 7) — [CLI parity: CLI calls shared UX facade functions](#i079)
- [ ] **I080** (Phase 7) — [Web Console UI (status/timeline/query/proof/plugins/keys)](#i080)
- [ ] **I081** (Phase 7) — [Alerts panel driven by journal events](#i081)
- [ ] **I082** (Phase 7) — [Local-only auth boundary (bind localhost + token)](#i082)
- [ ] **I083** (Phase 7) — [Websocket for live telemetry](#i083)
- [ ] **I084** (Phase 0) — [Split heavy ML dependencies into optional extras](#i084)
- [ ] **I085** (Phase 0) — [Make resource paths package-safe (no CWD dependence)](#i085)
- [ ] **I086** (Phase 0) — [Use OS-appropriate default data/config dirs (platformdirs)](#i086)
- [ ] **I087** (Phase 0) — [Package builtin plugins as package data](#i087)
- [ ] **I088** (Phase 0) — [Add reproducible dependency lockfile (hash-locked)](#i088)
- [ ] **I089** (Phase 0) — [Add canonical-json safety tests for journal/ledger payloads](#i089)
- [ ] **I090** (Phase 0) — [Add concurrency tests for ledger/journal append correctness](#i090)
- [ ] **I091** (Phase 0) — [Add golden chain test: ledger verify + anchor verify](#i091)
- [ ] **I092** (Phase 0) — [Add performance regression tests (capture latency/memory/query latency)](#i092)
- [ ] **I093** (Phase 0) — [Add security regression tests (DPAPI fail-closed, network guard, no raw egress)](#i093)
- [ ] **I094** (Phase 0) — [Static analysis: ruff + typing + vuln scan](#i094)
- [ ] **I095** (Phase 0) — [Doctor validates locks, storage, anchors, and network policy](#i095)
- [ ] **I096** (Phase 1) — [Fail loud on decrypt errors when encryption_required](#i096)
- [ ] **I097** (Phase 1) — [Add record type fields everywhere](#i097)
- [ ] **I098** (Phase 1) — [Add unified EventBuilder helper](#i098)
- [ ] **I099** (Phase 1) — [Stamp every journal event with run_id](#i099)
- [ ] **I100** (Phase 1) — [Cache policy snapshot hashing per run](#i100)
- [ ] **I101** (Phase 3) — [Add content_hash to metadata for every media put](#i101)
- [ ] **I102** (Phase 3) — [Track partial failures explicitly in journal/ledger](#i102)
- [ ] **I103** (Phase 3) — [Add segment sealing ledger entry after successful write](#i103)
- [ ] **I104** (Phase 3) — [Add startup recovery scanner to reconcile stores](#i104)
- [ ] **I105** (Phase 2) — [If keeping zips, use ZIP_STORED for JPEG frames](#i105)
- [ ] **I106** (Phase 2) — [If keeping zips, stream ZipFile writes to a real file](#i106)
- [ ] **I107** (Phase 2) — [Batch input events to reduce write overhead](#i107)
- [ ] **I108** (Phase 3) — [Add compact binary input log (derived) + JSON summary](#i108)
- [ ] **I109** (Phase 2) — [Add WASAPI loopback option for system audio capture](#i109)
- [ ] **I110** (Phase 2) — [Store audio as PCM/FLAC/Opus derived artifact](#i110)
- [ ] **I111** (Phase 2) — [Normalize active window process paths (device → drive paths)](#i111)
- [ ] **I112** (Phase 2) — [Capture window.rect and monitor mapping](#i112)
- [ ] **I113** (Phase 2) — [Optional cursor position+shape capture](#i113)
- [ ] **I114** (Phase 8) — [Clipboard capture plugin (local-only, append-only)](#i114)
- [ ] **I115** (Phase 8) — [File activity capture plugin (USN journal / watcher)](#i115)
- [ ] **I116** (Phase 5) — [Model execution budgets per idle window](#i116)
- [ ] **I117** (Phase 5) — [Preemption/chunking for long jobs](#i117)
- [ ] **I118** (Phase 4) — [Index versioning for retrieval reproducibility](#i118)
- [ ] **I119** (Phase 6) — [Persist entity-tokenizer key id/version; version tokenization](#i119)
- [ ] **I120** (Phase 6) — [Ledger sanitized egress packets (hash + schema version)](#i120)
- [ ] **I121** (Phase 7) — [Egress approval workflow in UI](#i121)
- [ ] **I122** (Phase 8) — [Plugin hot-reload with hash verification and safe swap](#i122)
- [ ] **I123** (Phase 1) — [Write kernel boot ledger entry system.start](#i123)
- [ ] **I124** (Phase 1) — [Write kernel shutdown ledger entry system.stop](#i124)
- [ ] **I125** (Phase 1) — [Write crash ledger entry on next startup](#i125)
- [ ] **I126** (Phase 0) — [Make sha256_directory path sorting deterministic across OSes](#i126)
- [ ] **I127** (Phase 4) — [Record python/OS/package versions into run manifest](#i127)
- [ ] **I128** (Phase 3) — [Tooling to migrate data_dir safely (copy+verify, no delete)](#i128)
- [ ] **I129** (Phase 3) — [Disk usage forecasting (days remaining) + alerts](#i129)
- [ ] **I130** (Phase 3) — [Storage compaction for derived artifacts only](#i130)

## Phase 0: Scaffolding and gates

Introduce CI/doctor/verify scaffolding, packaging/path hygiene, deterministic hashing.

**Entry criteria:** repo builds and tests run at least once on target machine.

**Exit criteria (minimum):**

- All items in this phase have tests/gates in place and passing.
- No pillar regression under the listed regression detection.
- Doctor reports clean or only explicitly acknowledged warnings.

### Work items

<a id="i084"></a>
### I084 — Split heavy ML dependencies into optional extras

- **Pillars improved (P+):** P1, P3
- **Pillars risked (P-):** P2
- **Enforcement location:**
  - pyproject.toml extras
  - plugin import boundaries (no unconditional torch/transformers imports)
  - builtin plugin manifests declare optional deps
- **Regression detection:**
  - CI matrix: minimal install runs capture+stores without ML deps
  - CI matrix: extras[vision]/[embeddings]/[sqlcipher] enable corresponding plugins
  - Gate: import-time scan ensures no heavy deps imported in ACTIVE ingest path
- **Implementation notes:**
  - Split ML plugins into separate builtin plugins: `vlm_*`, `ocr_*`, `embedder_*`.
  - Move heavy imports inside plugin `start()` or worker code, not module import.
  - Define clear capability flags: `supports_vlm`, `supports_ocr`, `supports_embed`.
  - When extras missing, plugin is unavailable and scheduler marks jobs as NO_EVIDENCE.
- **Acceptance criteria:**
  - Base installation captures and queries metadata without importing heavy ML deps.
  - Installing extras enables the associated plugins with no code changes.

<a id="i085"></a>
### I085 — Make resource paths package-safe (no CWD dependence)

- **Pillars improved (P+):** P2, P3, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - Replace relative paths with `importlib.resources` for packaged assets
  - `autocapture_nx/kernel/paths.py` (new) centralizes path resolution
- **Regression detection:**
  - Test: run from arbitrary CWD and verify default.json/contracts/plugins load
  - Wheel install test: builtin plugins discoverable and loadable
- **Implementation notes:**
  - Create `paths.py` that resolves: config dir, data dir, asset dir, plugin dir.
  - Load `config/default.json` and `contracts/*.json` via package resources.
  - For editable dev mode, support override via env var but keep defaults safe.
- **Acceptance criteria:**
  - Running from any directory yields identical behavior and finds assets.

<a id="i086"></a>
### I086 — Use OS-appropriate default data/config dirs (platformdirs)

- **Pillars improved (P+):** P1, P2, P3
- **Pillars risked (P-):** None
- **Enforcement location:**
  - Use `platformdirs` to pick Windows-first locations
  - Config schema: `paths.config_dir`, `paths.data_dir` resolved at boot
- **Regression detection:**
  - Test matrix: Windows/Linux/WSL path resolution produces valid dirs
  - Doctor check: directories exist and are writable; vault is restricted
- **Implementation notes:**
  - Adopt OS-specific defaults: `%APPDATA%/Autocapture` (config),
  - `%LOCALAPPDATA%/Autocapture` (data), with overrides in config.
  - Avoid mixing Linux paths under WSL with Windows AppData paths.
- **Acceptance criteria:**
  - Default paths are correct on Windows and do not depend on CWD.

<a id="i087"></a>
### I087 — Package builtin plugins as package data

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - Packaging: include `plugins/builtin/**` as package data
  - Plugin discovery uses package resources when installed
- **Regression detection:**
  - Wheel install test: `autocapture doctor` lists builtin plugins
  - Gate: plugin lock hashing includes packaged plugin files
- **Implementation notes:**
  - Update build config to include plugin files in sdist/wheel.
  - Modify registry to support builtin plugins shipped inside the package.
  - Keep repo-layout discovery for dev, but prefer packaged assets in prod.
- **Acceptance criteria:**
  - Installed wheel runs with builtin plugins without requiring repo checkout.

<a id="i088"></a>
### I088 — Add reproducible dependency lockfile (hash-locked)

- **Pillars improved (P+):** P3, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - Dependency lock: `requirements.lock` or `uv.lock` with hashes
  - CI verifies lock integrity and matches pyproject constraints
- **Regression detection:**
  - Gate: lock drift check fails if deps change without lock update
  - Supply-chain test: install from lock only; run smoke tests
- **Implementation notes:**
  - Adopt a single locking tool and commit lockfile.
  - Require hashes for all wheels/sdists.
  - Document the update workflow in `docs/deps.md`.
- **Acceptance criteria:**
  - CI can build and install deterministically from lockfile.

<a id="i089"></a>
### I089 — Add canonical-json safety tests for journal/ledger payloads

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - Unit tests for canonical-json compliance across all event builders
  - Gate: `tools/gate_canon.py` runs in CI
- **Regression detection:**
  - Test: generate sample events from each plugin; validate canonical JSON
  - Gate: fail on floats/bytes/non-UTC timestamps
- **Implementation notes:**
  - Create test fixture that calls EventBuilder for each event type.
  - Validate: no floats, no bytes; timestamps ISO UTC; deterministic key order.
- **Acceptance criteria:**
  - All emitted events pass canonical-json validation in CI.

<a id="i090"></a>
### I090 — Add concurrency tests for ledger/journal append correctness

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - Thread-safety tests for ledger/journal writers
  - Gate: `tools/gate_concurrency.py`
- **Regression detection:**
  - Test: multi-thread append; verify entry count and stable chain
  - Test: forced thread interleavings do not corrupt files
- **Implementation notes:**
  - Use a shared writer lock; ensure atomic append + flush semantics.
  - Add tests that run with many threads and randomized scheduling.
- **Acceptance criteria:**
  - Ledger/journal remain valid under concurrent writes.

<a id="i091"></a>
### I091 — Add golden chain test: ledger verify + anchor verify

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - Golden test corpus for ledger chain + anchors
  - Gate: `tools/gate_ledger.py` verifies replay
- **Regression detection:**
  - Test: produce N entries; verify chain and anchor head deterministically
  - Test: tamper with one entry; verification fails
- **Implementation notes:**
  - Add deterministic test keys for anchor signing in test env only.
  - Commit small golden ledgers in `tests/golden/`.
- **Acceptance criteria:**
  - Verification reliably detects tampering and passes on untampered goldens.

<a id="i092"></a>
### I092 — Add performance regression tests (capture latency/memory/query latency)

- **Pillars improved (P+):** P1
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - Perf suite: capture tick latency, memory ceiling, query latency
  - Gate: `tools/gate_perf.py` with thresholds
- **Regression detection:**
  - Bench: sustained capture at configured fps; assert bounded RAM
  - Bench: query over N records completes under budget
- **Implementation notes:**
  - Define benchmark scenarios with fixed settings and sample data.
  - Record baseline budgets and fail on regressions beyond allowed delta.
- **Acceptance criteria:**
  - Perf gate is deterministic and prevents accidental regressions.

<a id="i093"></a>
### I093 — Add security regression tests (DPAPI fail-closed, network guard, no raw egress)

- **Pillars improved (P+):** P3
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - Security test suite run in CI
  - Gate: `tools/gate_security.py`
- **Regression detection:**
  - Test: DPAPI failure with encryption_required causes hard failure
  - Test: kernel process cannot open network sockets
  - Test: unsanitized egress blocked unless dangerous_ops enabled
- **Implementation notes:**
  - Add unit/integration tests for keyring, network guard, egress gateway.
  - Add mock egress plugin to prove policy enforcement.
- **Acceptance criteria:**
  - Security regressions are caught automatically.

<a id="i094"></a>
### I094 — Static analysis: ruff + typing + vuln scan

- **Pillars improved (P+):** P2, P3
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - Static analysis in CI (lint, type checks, dependency scan)
- **Regression detection:**
  - CI fails on new lint/type errors
  - CI fails on high-severity dependency vulnerabilities (policy-defined)
- **Implementation notes:**
  - Adopt ruff; adopt a type checker; integrate vulnerability scanning.
  - Keep ruleset minimal and enforceable; ban broad ignores.
- **Acceptance criteria:**
  - Main branch stays lint/type clean; security issues surfaced early.

<a id="i095"></a>
### I095 — Doctor validates locks, storage, anchors, and network policy

- **Pillars improved (P+):** P2, P3, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - `autocapture doctor` (new) + `tools/gate_doctor.py`
- **Regression detection:**
  - Test: doctor detects missing lockfile, plugin hash mismatch, bad perms
  - Test: doctor output is stable (snapshot test)
- **Implementation notes:**
  - Doctor validates: contract lock, plugin locks, storage encryption,
  - anchor signing availability, network policy, path resolution.
  - Doctor must be non-destructive and provide actionable fixes.
- **Acceptance criteria:**
  - Doctor reliably detects misconfigurations before runtime failures.

<a id="i126"></a>
### I126 — Make sha256_directory path sorting deterministic across OSes

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** None
- **Enforcement location:**
  - `autocapture_nx/kernel/hashing.py` sha256_directory ordering
  - Used by plugin hashing + contract lock hashing
- **Regression detection:**
  - Test: same directory hashed on Windows/Linux yields identical digest
  - Gate: plugin lock update is deterministic on same content
- **Implementation notes:**
  - Normalize to relative POSIX path strings (`/` separators).
  - Sort by normalized path; ignore platform-specific metadata.
- **Acceptance criteria:**
  - Hashing is deterministic across OS and filesystem orderings.


## Phase 1: Correctness + immutability blockers

Fix correctness/security breakers; establish run_id + ID discipline; stop evidence mutation.

**Entry criteria:** Phase 0 exit criteria met; relevant gates passing.

**Exit criteria (minimum):**

- All items in this phase have tests/gates in place and passing.
- No pillar regression under the listed regression detection.
- Doctor reports clean or only explicitly acknowledged warnings.

### Work items

<a id="i001"></a>
### I001 — Eliminate floats from journal/ledger payloads

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** None
- **Enforcement location:**
  - EventBuilder + canonical_json encoder
  - All plugin event payloads
- **Regression detection:**
  - Gate-CANON: reject floats/bytes; unit tests for all event types
  - Test: capture disk-pressure event emits integer bytes, not floats
- **Implementation notes:**
  - Replace `*_gb` float fields with integer `*_bytes` or stringified decimals.
  - If human-readable values needed, compute at presentation time (UI).
- **Acceptance criteria:**
  - No runtime path emits floats into canonical JSON; CI enforces.

<a id="i002"></a>
### I002 — Make backpressure actually affect capture rate

- **Pillars improved (P+):** P1, P2
- **Pillars risked (P-):** None
- **Enforcement location:**
  - capture_windows pipeline timing loop
  - runtime governor → capture fps/quality controller
- **Regression detection:**
  - Test: backpressure changes fps target and measured interval responds
  - Perf: capture tick p95 stays within budget under disk pressure
- **Implementation notes:**
  - Replace fixed-interval generator with loop reading mutable `fps_target`.
  - Implement controller that adjusts fps/quality based on backlog/disk/CPU.
  - Log changes as journal events (`capture.rate_change`).
- **Acceptance criteria:**
  - When disk/queue pressure rises, capture rate drops within 1 second.

<a id="i003"></a>
### I003 — Stop buffering whole segments in RAM; stream segments

- **Pillars improved (P+):** P1, P2, P3
- **Pillars risked (P-):** None
- **Enforcement location:**
  - capture_windows: segment packer/writer
  - media store write path supports streaming
- **Regression detection:**
  - Perf: sustained capture uses bounded RAM (ceiling configured)
  - Test: segments written continuously without OOM on large resolutions
- **Implementation notes:**
  - Implement streaming packer: frame → encoder/container writer → encrypted writer.
  - Use bounded ring buffer for transient frames only.
  - Record dropped frames and encoder lag in metadata.
- **Acceptance criteria:**
  - Capture can run indefinitely without unbounded memory growth.

<a id="i004"></a>
### I004 — Do not write to storage from realtime audio callback

- **Pillars improved (P+):** P1, P2
- **Pillars risked (P-):** None
- **Enforcement location:**
  - audio_windows: callback produces into queue only
  - audio writer thread performs storage IO
- **Regression detection:**
  - Test: callback path performs no disk IO (mock store asserts not called)
  - Perf: audio capture has no xruns under load (best-effort check)
- **Implementation notes:**
  - Use lock-free or low-lock queue from callback to writer thread.
  - Writer batches writes into derived artifact blocks; ledger/journal at batch boundaries.
- **Acceptance criteria:**
  - Audio callback is realtime-safe and never blocks on IO.

<a id="i005"></a>
### I005 — Stop mutating primary evidence metadata during query

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - query pipeline (`autocapture_nx/kernel/query.py`)
  - metadata store API: forbid overwrites for primary evidence
- **Regression detection:**
  - Gate-IMMUT: detect `put_replace` on evidence types
  - Test: extraction creates `derived.*` record; parent unchanged (hash stable)
- **Implementation notes:**
  - Introduce evidence/derived record types; enforce immutability for evidence.
  - Extraction writes derived records (Pattern B) and links to parent via derivation graph.
- **Acceptance criteria:**
  - No query path mutates primary evidence; citations remain stable over time.

<a id="i006"></a>
### I006 — Introduce globally unique run/session identifier; prefix all record IDs

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** None
- **Enforcement location:**
  - kernel run manager (new): run_id creation and propagation
  - all plugins include run_id in IDs and events
- **Regression detection:**
  - Test: two runs produce non-colliding IDs even with same sequences
  - Gate: lint rule forbids bare `segment_0` style IDs in plugins
- **Implementation notes:**
  - Create `run_id` as ULID/UUIDv7 at boot or capture start.
  - Prefix all record IDs with `run_id/` and use monotonic seq per type.
  - Store run manifest linking run_id to config/locks hashes.
- **Acceptance criteria:**
  - Replaying a second run never overwrites or collides with prior data.

<a id="i007"></a>
### I007 — Make ledger writing thread-safe

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - ledger writer: single-writer lock + atomic append semantics
- **Regression detection:**
  - Concurrency tests (Phase 0 I090) validate chain under multi-threading
- **Implementation notes:**
  - Add process-level file lock or per-writer mutex.
  - Ensure append writes are atomic and flushed per entry (policy-driven).
- **Acceptance criteria:**
  - Ledger chain remains valid under concurrent plugin writes.

<a id="i008"></a>
### I008 — Make journal writing thread-safe; centralize sequences

- **Pillars improved (P+):** P1, P2, P4
- **Pillars risked (P-):** None
- **Enforcement location:**
  - journal writer centralizes sequencing and timestamps
  - plugins stop maintaining their own `seq += 1` counters
- **Regression detection:**
  - Test: concurrent writes produce strictly increasing per-stream sequence
  - Snapshot: journal schema stable and contains run_id
- **Implementation notes:**
  - Move sequencing into JournalWriter; expose `append(event_type, payload)` API.
  - Add optional batching API for high-frequency events (see I107).
- **Acceptance criteria:**
  - All plugins emit events through EventBuilder+JournalWriter with stable schema.

<a id="i009"></a>
### I009 — Fail closed if DPAPI protection fails when encryption_required

- **Pillars improved (P+):** P3, P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - keyring DPAPI unprotect path
  - config: `storage.encryption_required` hard requirement
- **Regression detection:**
  - Security test: DPAPI fail leads to startup failure when encryption_required
  - Doctor reports actionable remediation (recreate vault, permissions, etc.)
- **Implementation notes:**
  - On DPAPI failure: raise a typed exception and stop.
  - Provide explicit recovery: rotate/recreate key material with user command.
- **Acceptance criteria:**
  - No path silently falls back to unprotected key bytes when encryption_required.

<a id="i010"></a>
### I010 — Sort all store keys deterministically

- **Pillars improved (P+):** P2, P4, P1
- **Pillars risked (P-):** None
- **Enforcement location:**
  - store implementations: keys() ordering and iteration
- **Regression detection:**
  - Test: repeated `keys()` calls return identical order
  - Gate: retrieval is deterministic given identical data
- **Implementation notes:**
  - Sort key lists lexicographically by canonical ID form.
  - For large stores, implement paged iteration with stable ordering.
- **Acceptance criteria:**
  - Iteration order is stable and deterministic across runs.

<a id="i011"></a>
### I011 — Use monotonic clocks for segment duration

- **Pillars improved (P+):** P2, P1
- **Pillars risked (P-):** None
- **Enforcement location:**
  - capture timing: use monotonic for intervals; UTC timestamps for provenance
- **Regression detection:**
  - Test: system clock changes do not break segment scheduling
- **Implementation notes:**
  - Use `time.monotonic()` to drive capture loop and durations.
  - Use `datetime.now(timezone.utc)` only to stamp event times.
- **Acceptance criteria:**
  - Capture schedule is robust to wall-clock adjustments.

<a id="i012"></a>
### I012 — Align default config with implemented capture backend

- **Pillars improved (P+):** P2, P1
- **Pillars risked (P-):** None
- **Enforcement location:**
  - config/default.json + config schema
  - capture plugin selection logic
- **Regression detection:**
  - Doctor warns if config selects unsupported backend
  - Test: default config runs capture without unsupported backend errors
- **Implementation notes:**
  - Set default backend to implemented option (e.g., `mss` based) OR
  - implement the configured default backend fully.
- **Acceptance criteria:**
  - Out-of-the-box config matches real implementation.

<a id="i013"></a>
### I013 — Remove hard-coded model paths; config-driven + portable

- **Pillars improved (P+):** P2, P3, P1
- **Pillars risked (P-):** None
- **Enforcement location:**
  - ML plugins: model cache/weights paths in config
  - doctor validates paths exist or can be downloaded
- **Regression detection:**
  - Test: no absolute host-specific paths in repo
  - Doctor: warns when model missing; offers download command
- **Implementation notes:**
  - Introduce `models.dir` and per-model entries with digests.
  - Support inbound download jobs via policy-approved downloader plugin (Phase 6).
- **Acceptance criteria:**
  - Repo works on fresh machine without editing hard-coded paths.

<a id="i014"></a>
### I014 — Enforce plugin compat.requires_kernel / schema versions

- **Pillars improved (P+):** P2, P3, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - plugin loader enforces compat fields at load time
  - contracts define schema versions and kernel ABI
- **Regression detection:**
  - Test: incompatible plugin is refused with clear error
  - Doctor: lists plugin compat mismatches
- **Implementation notes:**
  - Define kernel ABI version and schema versions in `contracts/`.
  - Require plugins to declare required versions; loader refuses mismatches.
- **Acceptance criteria:**
  - No plugin can run against incompatible kernel/schema without explicit override.

<a id="i015"></a>
### I015 — Verify contract lock at boot/doctor

- **Pillars improved (P+):** P3, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - contract lock verification at boot and doctor
  - `contracts/lock.json` must match hashes of contract files
- **Regression detection:**
  - Gate: contract lock verify in CI and on startup
  - Test: modifying contract file without lock update fails
- **Implementation notes:**
  - Implement `contracts.verify_lock()` using deterministic hashing (I126).
  - Make boot fail closed if contracts do not verify (unless dev override).
- **Acceptance criteria:**
  - Contracts cannot drift silently; every drift is detected.

<a id="i096"></a>
### I096 — Fail loud on decrypt errors when encryption_required

- **Pillars improved (P+):** P2, P3
- **Pillars risked (P-):** None
- **Enforcement location:**
  - Encrypted stores: decrypt error handling under encryption_required
- **Regression detection:**
  - Test: corrupted ciphertext causes explicit error, not silent default
  - Doctor: can detect corruption and suggest recovery steps
- **Implementation notes:**
  - Differentiate: missing key vs corrupted blob vs wrong key id.
  - When `encryption_required=true`, never return partial/empty records.
- **Acceptance criteria:**
  - Corruption is surfaced deterministically and does not produce false data.

<a id="i097"></a>
### I097 — Add record type fields everywhere

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** None
- **Enforcement location:**
  - All event/record schemas include `record_type` or `event_type`
- **Regression detection:**
  - Schema tests ensure `record_type` present for all stored records
- **Implementation notes:**
  - Define enum of record types and enforce via EventBuilder.
  - Use record_type for indexing and retrieval routing.
- **Acceptance criteria:**
  - Every stored record can be typed without inspecting arbitrary fields.

<a id="i098"></a>
### I098 — Add unified EventBuilder helper

- **Pillars improved (P+):** P2, P4, P1
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - New `autocapture_nx/kernel/event_builder.py`
  - All plugins use EventBuilder for journal/ledger payloads
- **Regression detection:**
  - Gate: forbid direct JournalWriter/LedgerWriter calls outside EventBuilder
  - Test: EventBuilder outputs canonical-json-safe payloads
- **Implementation notes:**
  - EventBuilder provides constructors for each event type.
  - Centralize: run_id, timestamps, schema_version, record_type.
- **Acceptance criteria:**
  - Plugins emit consistent, validated events via a single API.

<a id="i099"></a>
### I099 — Stamp every journal event with run_id

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** None
- **Enforcement location:**
  - JournalWriter automatically inserts run_id (from run manager)
- **Regression detection:**
  - Test: all journal events include run_id
- **Implementation notes:**
  - JournalWriter reads current run_id from kernel context.
  - Reject event appends if run_id is missing (unless in bootstrap mode).
- **Acceptance criteria:**
  - Journal is always partitionable by run_id.

<a id="i100"></a>
### I100 — Cache policy snapshot hashing per run

- **Pillars improved (P+):** P1, P4
- **Pillars risked (P-):** None
- **Enforcement location:**
  - policy snapshot hashing computed once per run and reused
  - capture records store `policy_hash` only
- **Regression detection:**
  - Perf test: capture loop no longer recomputes policy hash per segment
  - Test: policy hash stable for a run and changes when config changes
- **Implementation notes:**
  - Compute `policy_hash = sha256(canonical_json(policy_snapshot))` at run start.
  - Store it in run manifest and reference it in evidence records.
- **Acceptance criteria:**
  - Policy hashing overhead is removed from hot path.

<a id="i123"></a>
### I123 — Write kernel boot ledger entry system.start

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - kernel boot sequence writes `system.start` ledger entry
- **Regression detection:**
  - Golden ledger test includes start entry
  - Doctor verifies presence of start entry for completed runs
- **Implementation notes:**
  - At boot/capture start, write ledger entry including hashes:
  - config hash, plugin lock hash, contract lock hash, kernel version.
- **Acceptance criteria:**
  - Every run has a verifiable origin entry in the ledger.

<a id="i124"></a>
### I124 — Write kernel shutdown ledger entry system.stop

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - kernel shutdown writes `system.stop` ledger entry with final head hash
- **Regression detection:**
  - Test: graceful shutdown emits stop entry
- **Implementation notes:**
  - On controlled shutdown, write final ledger entry referencing last head.
  - Include run duration and summary counters (drops, errors).
- **Acceptance criteria:**
  - Every clean run has an explicit termination entry.

<a id="i125"></a>
### I125 — Write crash ledger entry on next startup

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - startup recovery writes `system.crash_detected` if prior run missing stop
- **Regression detection:**
  - Test: simulate crash (no stop) then restart emits crash entry
- **Implementation notes:**
  - On startup, detect last run without stop entry; emit crash marker.
  - Link to last known ledger head and recovery actions taken (I104).
- **Acceptance criteria:**
  - Crashes are recorded and do not silently break provenance.


## Phase 2: Capture pipeline refactor

Streaming capture, backpressure, bounded memory, accurate timestamps, and correlation signals.

**Entry criteria:** Phase 1 exit criteria met; relevant gates passing.

**Exit criteria (minimum):**

- All items in this phase have tests/gates in place and passing.
- No pillar regression under the listed regression detection.
- Doctor reports clean or only explicitly acknowledged warnings.

### Work items

<a id="i016"></a>
### I016 — Split capture into grab → encode/pack → encrypt/write pipeline

- **Pillars improved (P+):** P1, P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - capture_windows plugin refactor into 3-stage pipeline
  - interfaces: grabber, encoder/packer, encrypted writer
- **Regression detection:**
  - Perf: capture tick p95 within budget while pipeline backlog grows
  - Test: pipeline stages can be independently throttled/cancelled
- **Implementation notes:**
  - Create bounded queues between stages; stage 1 never blocks on disk.
  - Stage 2 encodes/containers frames with deterministic timestamps.
  - Stage 3 encrypts+writes atomically and emits evidence+ledger entries.
- **Acceptance criteria:**
  - Capture remains stable under load and isolates slow disk/encode paths.

<a id="i017"></a>
### I017 — Bounded queues with explicit drop policies

- **Pillars improved (P+):** P1, P2, P4
- **Pillars risked (P-):** P2
- **Enforcement location:**
  - queue primitives in capture/audio/input pipelines
  - drop policy documented and recorded
- **Regression detection:**
  - Test: queue never grows beyond configured max
  - Test: drops are recorded in metadata and journal
- **Implementation notes:**
  - Define per-queue size limits and what to drop (oldest vs newest).
  - Prefer dropping derived/per-frame detail over dropping segment boundaries.
  - Emit `capture.drop`/`audio.drop` events with counters.
- **Acceptance criteria:**
  - System remains bounded; any fidelity loss is explicit and auditable.

<a id="i018"></a>
### I018 — Replace zip-of-JPEG with real video container for primary artifact

- **Pillars improved (P+):** P1, P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - media container format for primary capture evidence
  - segment format versioning
- **Regression detection:**
  - Test: segment decode/extract works on all supported OS targets
  - Test: container metadata timestamps align with recorded ts_start/end
- **Implementation notes:**
  - Adopt a segment container with: time base, frame timestamps, keyframes.
  - Store container as encrypted blob; store index/headers in metadata for fast seek.
  - Keep legacy zip path only behind compatibility flag (I105/I106).
- **Acceptance criteria:**
  - Primary capture evidence is efficient to store and seek deterministically.

<a id="i019"></a>
### I019 — Add GPU-accelerated capture/encode backend (NVENC/DD)

- **Pillars improved (P+):** P1
- **Pillars risked (P-):** P2, P3
- **Enforcement location:**
  - New capture backend plugin(s): Desktop Duplication + NVENC
  - Config: `capture.backend` selects backend
- **Regression detection:**
  - Perf: CPU usage drops vs mss baseline at target resolution/fps
  - Security: subprocess sandbox for encoder if using external binaries
- **Implementation notes:**
  - Implement Windows Desktop Duplication capture and NVENC encode.
  - Fallback to mss backend when GPU unavailable.
  - Record backend choice per segment (I21).
- **Acceptance criteria:**
  - On capable GPUs, capture runs with minimal CPU while maintaining fidelity.

<a id="i020"></a>
### I020 — Record segment start/end timestamps

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** None
- **Enforcement location:**
  - capture metadata schema includes `ts_start_utc` and `ts_end_utc`
- **Regression detection:**
  - Test: segments always have valid start/end with end >= start
- **Implementation notes:**
  - At segment open: stamp start UTC; at segment seal: stamp end UTC.
  - Use monotonic for duration and derive end timestamp consistently.
- **Acceptance criteria:**
  - Every segment is time-bounded and usable for timeline queries.

<a id="i021"></a>
### I021 — Record capture parameters per segment

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - capture metadata includes capture parameters and achieved metrics
- **Regression detection:**
  - Schema test ensures required capture params exist
- **Implementation notes:**
  - Store: backend, target_fps, achieved_fps, resolution, quality/bitrate,
  - monitor layout, drop counts, encoder lag, policy_hash (I100).
- **Acceptance criteria:**
  - Segments are self-describing for reproducibility and debugging.

<a id="i022"></a>
### I022 — Correlate frames with active window via synchronized timeline

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - window timeline store + correlation logic in retrieval
- **Regression detection:**
  - Test: given window-change events, frame-to-window mapping is correct
- **Implementation notes:**
  - Model window changes as a timeline with `ts_utc` and `window_id` state.
  - Join frames/segments by timestamp range at query time (Pattern A/B).
- **Acceptance criteria:**
  - Answers can cite which window/app a frame belonged to at a time.

<a id="i023"></a>
### I023 — Add cursor/input correlation timeline references

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - input events and cursor state exposed as timelines
  - correlation references stored in derived artifacts
- **Regression detection:**
  - Test: correlation graph includes references from text/citation to input bursts
- **Implementation notes:**
  - Batch input into time buckets (I107) and index by time.
  - If cursor capture enabled (I113), store cursor timeline with timestamps.
- **Acceptance criteria:**
  - Investigations can align what was seen with what was done (time-synced).

<a id="i024"></a>
### I024 — Disk pressure degrades capture quality before stopping

- **Pillars improved (P+):** P1, P2
- **Pillars risked (P-):** None
- **Enforcement location:**
  - disk pressure controller in capture pipeline
  - policy thresholds in config
- **Regression detection:**
  - Test: under simulated low disk, capture degrades (fps/quality) before stop
  - Journal: emits `disk.pressure` and `capture.degrade` events
- **Implementation notes:**
  - Define thresholds: warn/soft/critical.
  - At soft: reduce fps/quality; at critical: stop only if cannot write safely.
- **Acceptance criteria:**
  - Capture fails gracefully and predictably under storage pressure.

<a id="i025"></a>
### I025 — Atomic segment writes (temp + os.replace)

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - all store writes are atomic (temp + replace)
  - manifest and seal records only written after success
- **Regression detection:**
  - Test: crash mid-write does not produce partially visible evidence
  - Recovery scanner (I104) reconciles temp artifacts safely
- **Implementation notes:**
  - Write to temp path; fsync as configured; rename atomically.
  - Write segment seal entry only after both media and metadata committed.
- **Acceptance criteria:**
  - No partial evidence becomes 'valid' without explicit seal.

<a id="i105"></a>
### I105 — If keeping zips, use ZIP_STORED for JPEG frames

- **Pillars improved (P+):** P1
- **Pillars risked (P-):** P2
- **Enforcement location:**
  - legacy zip segment path (if retained) uses ZIP_STORED
- **Regression detection:**
  - Perf: segment packing CPU drops vs deflate for JPEG frames
- **Implementation notes:**
  - JPEG is already compressed; store frames without deflate.
  - Keep as compatibility mode only; prefer container format (I18).
- **Acceptance criteria:**
  - Legacy zip path is less CPU-expensive and remains correct.

<a id="i106"></a>
### I106 — If keeping zips, stream ZipFile writes to a real file

- **Pillars improved (P+):** P1, P2
- **Pillars risked (P-):** None
- **Enforcement location:**
  - legacy zip writer streams to file (no BytesIO)
- **Regression detection:**
  - Perf: no large in-memory segment buffers
  - Test: zip is valid and contains expected files
- **Implementation notes:**
  - Open a temp file; write ZipFile entries incrementally; close; encrypt/write.
  - Prefer direct encrypted writer streaming where possible.
- **Acceptance criteria:**
  - Zip mode does not require segment-sized RAM buffers.

<a id="i107"></a>
### I107 — Batch input events to reduce write overhead

- **Pillars improved (P+):** P1, P2, P4
- **Pillars risked (P-):** None
- **Enforcement location:**
  - input_windows batches events by time window (e.g., 100–250ms)
  - JournalWriter supports batch append
- **Regression detection:**
  - Perf: input plugin reduces write rate under heavy input
  - Test: event ordering within batch preserved and timestamped
- **Implementation notes:**
  - Accumulate raw events in memory for a short window; flush as one record.
  - Use canonical schema: `input.batch` with start/end time and list of events.
- **Acceptance criteria:**
  - Input capture is scalable without overwhelming IO.

<a id="i109"></a>
### I109 — Add WASAPI loopback option for system audio capture

- **Pillars improved (P+):** P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - audio_windows supports WASAPI loopback capture mode
  - Config selects microphone vs loopback
- **Regression detection:**
  - Test: device enumeration deterministic; loopback selection works on CI mocks
- **Implementation notes:**
  - Implement loopback capture path on Windows.
  - Record device identity and mode in derived artifact metadata.
- **Acceptance criteria:**
  - System audio can be captured as a first-class source when enabled.

<a id="i110"></a>
### I110 — Store audio as PCM/FLAC/Opus derived artifact

- **Pillars improved (P+):** P1, P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - audio stored as derived artifact blocks with clear encoding
- **Regression detection:**
  - Test: audio roundtrip decode yields expected sample count
- **Implementation notes:**
  - Primary: store raw PCM blocks (int16) for fidelity or use FLAC/Opus for size.
  - Treat audio as derived artifact if sourced from callback stream; ledger derivation.
- **Acceptance criteria:**
  - Audio artifacts are decodable, time-aligned, and provenance-tracked.

<a id="i111"></a>
### I111 — Normalize active window process paths (device → drive paths)

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** None
- **Enforcement location:**
  - window metadata plugin normalizes process paths
- **Regression detection:**
  - Test: device path conversion deterministic given known mappings
- **Implementation notes:**
  - Convert NT device paths to drive-letter paths where possible.
  - Store both raw and normalized forms; hash normalization deterministically.
- **Acceptance criteria:**
  - Process paths are searchable and consistent across sessions.

<a id="i112"></a>
### I112 — Capture window.rect and monitor mapping

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - window metadata schema includes rect and monitor mapping
- **Regression detection:**
  - Test: rect fields present and valid; monitor id matches layout snapshot
- **Implementation notes:**
  - Capture window rectangle in screen coordinates and monitor id mapping.
  - Record monitor layout snapshot periodically or per segment (if changes).
- **Acceptance criteria:**
  - Window location can be correlated with capture frames deterministically.

<a id="i113"></a>
### I113 — Optional cursor position+shape capture

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1, P3
- **Enforcement location:**
  - optional cursor capture plugin or extension to capture_windows
- **Regression detection:**
  - Test: cursor capture disabled by default; when enabled, schema valid
  - Security: ensure cursor capture does not leak privileged info beyond local store
- **Implementation notes:**
  - Record cursor position and (if available) cursor shape id at sampled rate.
  - Store as timeline records; correlate via timestamps (Pattern A).
- **Acceptance criteria:**
  - Cursor timeline is accurate when enabled and has bounded overhead.


## Phase 3: Storage scaling + durability

SQLCipher/indices, binary encrypted blobs, atomic writes, recovery, compaction for derived.

**Entry criteria:** Phase 2 exit criteria met; relevant gates passing.

**Exit criteria (minimum):**

- All items in this phase have tests/gates in place and passing.
- No pillar regression under the listed regression detection.
- Doctor reports clean or only explicitly acknowledged warnings.

### Work items

<a id="i026"></a>
### I026 — Default to SQLCipher for metadata when available

- **Pillars improved (P+):** P1, P2, P3
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - storage backend selection: prefer SQLCipher for metadata
  - config: `storage.metadata_backend=sqlcipher|encrypted_fs`
- **Regression detection:**
  - Test: metadata queries faster than directory scan at N records
  - Security: DB file encrypted and unreadable without key
- **Implementation notes:**
  - Define a metadata store interface; implement SQLCipher store fully.
  - Provide migration tool from fs-json to SQLCipher (append-only copy).
  - Keep AES-GCM fs store as fallback when SQLCipher unavailable.
- **Acceptance criteria:**
  - Metadata operations scale; encryption remains enforced.

<a id="i027"></a>
### I027 — Add DB indexes on ts_utc, record_type, run_id

- **Pillars improved (P+):** P1, P2
- **Pillars risked (P-):** None
- **Enforcement location:**
  - SQLCipher schema: indexes on `ts_utc`, `record_type`, `run_id`
- **Regression detection:**
  - EXPLAIN-based test: queries use indexes for common patterns
- **Implementation notes:**
  - Add composite indexes aligned to time-window + type filters.
  - Ensure UTC timestamps stored as sortable integer or ISO string consistently.
- **Acceptance criteria:**
  - Time-bounded queries are sub-linear and predictable.

<a id="i028"></a>
### I028 — Store media in binary encrypted format (not base64 JSON)

- **Pillars improved (P+):** P1, P3, P4
- **Pillars risked (P-):** None
- **Enforcement location:**
  - media store format: binary encrypted files with versioned header
- **Regression detection:**
  - Test: media blobs are not valid JSON and have expected magic/version
  - Test: decrypt+verify hash roundtrip works
- **Implementation notes:**
  - Define binary header: magic, version, key_id, nonce, chunking params.
  - Store ciphertext and auth tags; include content hash in metadata (I101).
- **Acceptance criteria:**
  - Media storage is efficient and unambiguous; supports streaming.

<a id="i029"></a>
### I029 — Stream encryption (avoid whole-segment in memory)

- **Pillars improved (P+):** P1, P3
- **Pillars risked (P-):** P2
- **Enforcement location:**
  - media encryption writer supports streaming/chunking
- **Regression detection:**
  - Perf: writing large segments does not allocate segment-sized RAM
  - Test: chunk boundaries validate and reject tampering
- **Implementation notes:**
  - Adopt chunked AEAD: each chunk uses derived nonce (base + counter).
  - Persist chunk sizes and tags; verify during read.
- **Acceptance criteria:**
  - Large artifacts are written/read with bounded memory and strong integrity.

<a id="i030"></a>
### I030 — Immutability/versioning in stores (put_new vs put_replace)

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - store APIs: `put_new()` for immutable; `put_replace()` only for caches
  - kernel enforces type-based mutability rules
- **Regression detection:**
  - Gate-IMMUT: evidence types cannot call replace; tests enforce
- **Implementation notes:**
  - Add mutability policy by record_type: evidence immutable; derived immutable;
  - indexes/caches rebuildable and replaceable.
- **Acceptance criteria:**
  - Evidence immutability is enforced by API, not convention.

<a id="i031"></a>
### I031 — Make record ID encoding reversible (no lossy mapping)

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** None
- **Enforcement location:**
  - record ID encoding/locator encoding is reversible
- **Regression detection:**
  - Test: encode→decode roundtrip yields same ID for all legal IDs
- **Implementation notes:**
  - Stop lossy `/`→`_` mapping; use percent-encoding or a structured directory layout.
  - Ensure IDs are safe on Windows filenames while preserving reversibility.
- **Acceptance criteria:**
  - IDs remain canonical and collision-free while being filesystem-safe.

<a id="i032"></a>
### I032 — Shard media/metadata directories by date/run

- **Pillars improved (P+):** P1
- **Pillars risked (P-):** P2
- **Enforcement location:**
  - storage layout: shard by run/date to limit directory sizes
- **Regression detection:**
  - Perf test: listing/iterating keys remains fast at large scale
- **Implementation notes:**
  - Directory schema: `media/{run_id}/{type}/{yyyy-mm-dd}/...` etc.
  - Stores must support deterministic iteration across shards.
- **Acceptance criteria:**
  - Storage remains performant as record count grows.

<a id="i033"></a>
### I033 — Add per-run storage manifest records

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - per-run manifest records (Pattern A) stored and ledgered
- **Regression detection:**
  - Test: manifest exists for each run and includes expected hashes
- **Implementation notes:**
  - Manifest includes: run_id, start/stop timestamps, config hash, locks hashes,
  - store versions, counters, policy_hash (I100), platform/version info (I127).
- **Acceptance criteria:**
  - Each run is reproducible/auditable from a single manifest.

<a id="i034"></a>
### I034 — Configurable fsync policy (critical vs bulk)

- **Pillars improved (P+):** P1, P2, P4
- **Pillars risked (P-):** None
- **Enforcement location:**
  - fsync policy config applied in writers
- **Regression detection:**
  - Crash test: critical records survive; bulk media may lag but seals prevent inconsistency
- **Implementation notes:**
  - Define fsync levels: journal+ledger always fsync; evidence seals fsync; bulk media optional.
  - Expose settings and document durability tradeoffs explicitly.
- **Acceptance criteria:**
  - Durability is explicit, configurable, and does not compromise provenance.

<a id="i101"></a>
### I101 — Add content_hash to metadata for every media put

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - media store returns content_hash; metadata stores it for every blob
- **Regression detection:**
  - Test: content_hash present and matches recomputed hash after decrypt
- **Implementation notes:**
  - Compute streaming SHA-256 on plaintext and store in metadata evidence record.
  - Ledger includes content_hash and locator digest.
- **Acceptance criteria:**
  - Evidence can be verified end-to-end by hash.

<a id="i102"></a>
### I102 — Track partial failures explicitly in journal/ledger

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - all failures emit typed journal/ledger events
- **Regression detection:**
  - Test: injected failures produce explicit failure records
- **Implementation notes:**
  - Standardize failure events: `evidence.write_failed`, `encode.failed`, etc.
  - Include error class, stage, retryability, and affected IDs.
- **Acceptance criteria:**
  - Failures are visible, auditable, and do not silently corrupt state.

<a id="i103"></a>
### I103 — Add segment sealing ledger entry after successful write

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - segment lifecycle includes explicit `segment.sealed` ledger entry
- **Regression detection:**
  - Test: sealed only after media+metadata committed and hashes known
- **Implementation notes:**
  - Write evidence record(s) then seal with final hashes, durations, and counters.
  - Seal references all constituent blob hashes and derived indexes (if any).
- **Acceptance criteria:**
  - A segment is only considered valid if sealed.

<a id="i104"></a>
### I104 — Add startup recovery scanner to reconcile stores

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - startup recovery scanner reconciles temp/partial artifacts
  - writes recovery actions to ledger/journal
- **Regression detection:**
  - Crash simulation: partial writes detected and repaired/quarantined
- **Implementation notes:**
  - Scan for temp files/unsealed evidence.
  - Either complete commit (if possible) or quarantine and emit recovery events.
- **Acceptance criteria:**
  - System self-heals from crashes without silently losing provenance.

<a id="i108"></a>
### I108 — Add compact binary input log (derived) + JSON summary

- **Pillars improved (P+):** P1, P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - input pipeline writes compact binary derived log + JSON summary records
- **Regression detection:**
  - Test: binary log roundtrip decode; JSON summary matches counts/time range
- **Implementation notes:**
  - Binary log stores dense events for replay; JSON summary is searchable/indexed.
  - Link binary blob evidence to summary record via derivation graph (I73).
- **Acceptance criteria:**
  - Input data scales without losing queryability or provenance.

<a id="i128"></a>
### I128 — Tooling to migrate data_dir safely (copy+verify, no delete)

- **Pillars improved (P+):** P1, P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - CLI/API command: `storage.migrate` copy+verify strategy
- **Regression detection:**
  - Test: migrate copies all evidence and manifests; verification passes
- **Implementation notes:**
  - Implement copy to new data_dir; verify hashes; switch pointer atomically.
  - Never delete source automatically; provide explicit cleanup command gated as dangerous op.
- **Acceptance criteria:**
  - Users can move data safely without data loss or provenance breakage.

<a id="i129"></a>
### I129 — Disk usage forecasting (days remaining) + alerts

- **Pillars improved (P+):** P1, P2
- **Pillars risked (P-):** None
- **Enforcement location:**
  - telemetry + alerts: disk usage trends and days remaining estimate
- **Regression detection:**
  - Test: forecasting produces deterministic output for fixed input series
- **Implementation notes:**
  - Track bytes/day for evidence and derived separately.
  - Compute conservative estimate; emit alerts at configured thresholds.
- **Acceptance criteria:**
  - System warns before disk exhaustion and informs mitigation choices.

<a id="i130"></a>
### I130 — Storage compaction for derived artifacts only

- **Pillars improved (P+):** P1
- **Pillars risked (P-):** P2, P4
- **Enforcement location:**
  - compaction applies only to derived artifacts and rebuildable indexes
- **Regression detection:**
  - Gate-IMMUT: compaction never touches primary evidence
  - Test: compaction reduces size; citations still resolve
- **Implementation notes:**
  - Define derived compaction strategies: recompress text indexes, prune caches,
  - dedupe derived blobs using content hashes.
- **Acceptance criteria:**
  - Storage is optimized without compromising evidence immutability or citations.


## Phase 4: Retrieval + provenance + citations

Deterministic retrieval, derived artifacts, citation resolver, proof bundles, replay.

**Entry criteria:** Phase 3 exit criteria met; relevant gates passing.

**Exit criteria (minimum):**

- All items in this phase have tests/gates in place and passing.
- No pillar regression under the listed regression detection.
- Doctor reports clean or only explicitly acknowledged warnings.

### Work items

<a id="i035"></a>
### I035 — Replace full-scan query with tiered indexed retrieval

- **Pillars improved (P+):** P1, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - retrieval pipeline plugin replaces full-scan approach
  - SQLCipher/FTS + optional embeddings
- **Regression detection:**
  - Perf: query latency improves at N records vs full scan baseline
  - Accuracy: golden queries return expected evidence set deterministically
- **Implementation notes:**
  - Tier 0: time window narrowing using indexed timestamps.
  - Tier 1: FTS over extracted/ingested text summaries.
  - Tier 2: embeddings (optional) for semantic recall; only in IDLE or explicit.
  - Tier 3: deterministic rerank (optional) with explicit model identity (I74).
- **Acceptance criteria:**
  - Queries scale without full scans and remain deterministic.

<a id="i036"></a>
### I036 — Deterministic retrieval ordering (stable sort keys)

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** None
- **Enforcement location:**
  - retrieval sorts by stable keys: time, record_type, evidence_id
- **Regression detection:**
  - Test: same dataset yields identical ranked output across runs
- **Implementation notes:**
  - Define explicit tie-breakers at every stage.
  - Ensure DB queries include `ORDER BY` with full tie-breaker set.
- **Acceptance criteria:**
  - Retrieval ordering is stable and reproducible.

<a id="i037"></a>
### I037 — Candidate-first extraction (retrieve then extract)

- **Pillars improved (P+):** P1, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - extraction planner: select candidates then extract
- **Regression detection:**
  - Perf: extraction work bounded to top-K candidates
  - Accuracy: extraction uses explicit time/span constraints
- **Implementation notes:**
  - Planner selects candidates by query intent and time window.
  - Extraction only runs on candidates; results stored as derived artifacts (I38).
- **Acceptance criteria:**
  - Extraction cost is bounded and targeted; no random scans.

<a id="i038"></a>
### I038 — Derived artifact records for OCR/VLM outputs

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - schema: `derived.text.*` records
  - store APIs enforce immutability (I30)
- **Regression detection:**
  - Test: derived text record includes parent reference and span_ref
  - Test: model identity fields present and hashed
- **Implementation notes:**
  - Derived record fields: parent_evidence_id, span_ref, method (ocr/vlm),
  - model_id+digest, parameters, normalized_text (I75), content_hash.
- **Acceptance criteria:**
  - All extraction outputs are provenance-tracked derived artifacts.

<a id="i039"></a>
### I039 — Ledger query executions (inputs/outputs)

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - query execution writes ledger entry: inputs + retrieval plan + outputs
- **Regression detection:**
  - Golden: query ledger entry reproducible for fixed corpus
- **Implementation notes:**
  - Log: query text, time constraints, retrieval tiers used, index versions (I118),
  - candidate IDs, final cited evidence IDs.
- **Acceptance criteria:**
  - Every answer can be tied to a ledgered query execution record.

<a id="i040"></a>
### I040 — Ledger extraction operations (inputs/outputs)

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - extraction writes ledger entry linking inputs/outputs
- **Regression detection:**
  - Test: derived artifacts have corresponding ledger derivation entries
- **Implementation notes:**
  - Ledger payload includes parent hash, span_ref, method, model identity,
  - output hash and derived record id.
- **Acceptance criteria:**
  - Derivations are verifiable and reconstructable.

<a id="i041"></a>
### I041 — Citations point to immutable evidence IDs + spans

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** None
- **Enforcement location:**
  - citation schema uses evidence_id + span_ref + hashes
- **Regression detection:**
  - Schema test: citations cannot be created without required fields
- **Implementation notes:**
  - Citations include: evidence_id, evidence_hash, span_kind/time offsets,
  - span_start/end, ledger_head_ref, anchor_ref.
- **Acceptance criteria:**
  - Citations are independently verifiable pointers, not best-effort strings.

<a id="i042"></a>
### I042 — Citation resolver validates hashes/anchors/spans

- **Pillars improved (P+):** P4, P3, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - citation resolver service + CLI validates evidence and provenance
- **Regression detection:**
  - Test: resolver detects tampering and missing spans
- **Implementation notes:**
  - Resolver steps: load evidence, verify content_hash, verify ledger chain,
  - verify anchor, validate span exists in evidence.
- **Acceptance criteria:**
  - Every citation displayed in UI can be validated locally on demand.

<a id="i043"></a>
### I043 — Fail closed if citations do not resolve

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - answer pipeline refuses to return `state=ok` if citations unresolved
- **Regression detection:**
  - Golden tests: unresolved citations produce `state=no_evidence` or `state=partial`
- **Implementation notes:**
  - Define answer states: ok | partial | no_evidence | conflict.
  - If resolver fails, downgrade state and emit diagnostic trace.
- **Acceptance criteria:**
  - System never asserts unsupported answers; failure modes are explicit.

<a id="i065"></a>
### I065 — Define canonical evidence model (EvidenceObject)

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** None
- **Enforcement location:**
  - contracts: evidence schema and versioning
  - EventBuilder enforces EvidenceObject fields
- **Regression detection:**
  - Schema tests cover all evidence types and require minimal fields
- **Implementation notes:**
  - Define EvidenceObject contract and per-type extensions.
  - All primary capture, audio, window, input, and derived artifacts conform.
- **Acceptance criteria:**
  - Evidence model is consistent and contract-checked.

<a id="i066"></a>
### I066 — Hash everything that matters (media/metadata/derived)

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - hashing: media plaintext SHA-256; metadata canonical-json hash
- **Regression detection:**
  - Verify: recomputed hashes match stored hashes for sample corpus
- **Implementation notes:**
  - Compute hashes at write time and store in metadata and ledger.
  - Hash canonical JSON payloads deterministically (I126).
- **Acceptance criteria:**
  - Every evidence/derived object is hash-addressable and verifiable.

<a id="i067"></a>
### I067 — Ledger every state transition

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - ledger coverage expanded across all plugins and transitions
- **Regression detection:**
  - Gate: required event types appear for each run (start, evidence writes, stop/crash)
- **Implementation notes:**
  - Define a required transition list per evidence type.
  - Enforce in CI using run simulations and golden traces.
- **Acceptance criteria:**
  - Ledger provides complete provenance coverage for the system's actions.

<a id="i068"></a>
### I068 — Anchor on schedule (N entries or M minutes)

- **Pillars improved (P+):** P4, P3
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - anchor plugin anchors ledger head on schedule
- **Regression detection:**
  - Test: anchors created at configured cadence; verification passes
- **Implementation notes:**
  - Anchor cadence: every N entries or M minutes; persist anchor records.
  - Anchor includes timestamp, ledger head hash, and signature/HMAC (I61).
- **Acceptance criteria:**
  - Ledger heads are periodically sealed for tamper evidence.

<a id="i069"></a>
### I069 — Immutable per-run manifest (config+locks+versions)

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - run manifest evidence record written early and finalized at end
- **Regression detection:**
  - Test: manifest includes config/plugin/contracts hashes + versions
- **Implementation notes:**
  - Manifest initial write at start; finalize at stop with counters and last ledger head.
  - Include environment info (I127) and policy_hash (I100).
- **Acceptance criteria:**
  - A single manifest summarizes and identifies the full run context.

<a id="i070"></a>
### I070 — Citation objects carry verifiable pointers

- **Pillars improved (P+):** P4, P2, P3
- **Pillars risked (P-):** None
- **Enforcement location:**
  - citation schema: include evidence hash + ledger/anchor refs
- **Regression detection:**
  - Resolver rejects citations missing required verification fields
- **Implementation notes:**
  - Citations carry enough data to verify without trusting the answer text.
  - Include schema versions for forward compatibility.
- **Acceptance criteria:**
  - Citations are self-contained verification units.

<a id="i071"></a>
### I071 — Citation resolver CLI/API

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - CLI/API endpoints: `verify citation`, `resolve citation`
- **Regression detection:**
  - Golden: resolver output stable and correct for known citations
- **Implementation notes:**
  - Expose resolver via UX facade for UI and CLI parity.
  - Return structured verification report (pass/fail + why).
- **Acceptance criteria:**
  - Users can verify citations with one command.

<a id="i072"></a>
### I072 — Metadata immutable by default; derived never overwrites

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - store mutability policies enforced per record_type (I30)
- **Regression detection:**
  - Gate-IMMUT catches any overwrite on evidence/derived records
- **Implementation notes:**
  - Implement store-layer guardrails (not just query-layer).
  - Allow overwrite only for explicitly declared cache/index record types.
- **Acceptance criteria:**
  - Immutability is enforced uniformly across the codebase.

<a id="i073"></a>
### I073 — Persist derivation graphs (parent→child links)

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - derivation graph store and schema
  - ledger entries reference derivation edges
- **Regression detection:**
  - Test: derived artifacts create derivation edge to parent
- **Implementation notes:**
  - Store edges: parent_id, child_id, relation_type, span_ref, method.
  - Maintain edges as append-only records; index for fast traversal.
- **Acceptance criteria:**
  - Any derived output can be traced back to its precise evidence parents.

<a id="i074"></a>
### I074 — Record model identity for ML outputs

- **Pillars improved (P+):** P4, P2, P3
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - model identity schema and recording in derived artifacts
  - model manager records weight digests (Phase 6)
- **Regression detection:**
  - Test: derived artifacts contain model_name + model_digest + params
- **Implementation notes:**
  - Model identity includes: provider, model name, weights digest, runtime version,
  - inference parameters, and prompt/template digest when applicable.
- **Acceptance criteria:**
  - ML outputs are reproducible and attributable to exact model artifacts.

<a id="i075"></a>
### I075 — Deterministic text normalization before hashing

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** None
- **Enforcement location:**
  - text normalization function used before hashing and indexing
- **Regression detection:**
  - Test: normalization is deterministic and stable on sample inputs
- **Implementation notes:**
  - Normalize to NFC, normalize newlines to `\n`, trim trailing spaces,
  - define explicit rules and version them (`text_norm_version`).
- **Acceptance criteria:**
  - Text hashes and indexes are stable and reproducible.

<a id="i076"></a>
### I076 — Proof bundles export (evidence + ledger slice + anchors)

- **Pillars improved (P+):** P4, P3, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - proof bundle exporter in UX facade
- **Regression detection:**
  - Test: exported bundle verifies on a clean machine without network
- **Implementation notes:**
  - Bundle includes: selected evidence blobs, their metadata, derivation edges,
  - ledger slice covering them, relevant anchors, and verification reports.
- **Acceptance criteria:**
  - Bundles are self-contained, verifiable, and suitable for audit/sharing (sanitized).

<a id="i077"></a>
### I077 — Replay mode validates citations without model calls

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - replay tool validates retrieval/citations without model calls
- **Regression detection:**
  - Golden: replay reproduces expected citations and verification results
- **Implementation notes:**
  - Replay uses stored retrieval plan trace + index versions (I118).
  - No network and no model calls; fail with NO_EVIDENCE if required data missing.
- **Acceptance criteria:**
  - Citations can be validated deterministically offline.

<a id="i118"></a>
### I118 — Index versioning for retrieval reproducibility

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - indexes record version/digest in manifest and query ledger entries
- **Regression detection:**
  - Test: query includes index version refs; rebuild increments version
- **Implementation notes:**
  - Define index version scheme (monotonic int + content digest).
  - Store in manifest and attach to query executions for reproducibility.
- **Acceptance criteria:**
  - Answers can identify which index snapshot they used.

<a id="i127"></a>
### I127 — Record python/OS/package versions into run manifest

- **Pillars improved (P+):** P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - run manifest captures environment versions
- **Regression detection:**
  - Test: manifest contains python version, OS build, package versions list
- **Implementation notes:**
  - Collect: Python version, OS name/build, GPU info (if available),
  - and installed package versions with hashes when possible.
- **Acceptance criteria:**
  - Runs are attributable to an environment fingerprint for debugging and audits.


## Phase 5: Scheduler/governor

Activity-authoritative gating, budgets, preemption, telemetry integration.

**Entry criteria:** Phase 4 exit criteria met; relevant gates passing.

**Exit criteria (minimum):**

- All items in this phase have tests/gates in place and passing.
- No pillar regression under the listed regression detection.
- Doctor reports clean or only explicitly acknowledged warnings.

### Work items

<a id="i044"></a>
### I044 — Real scheduler plugin gates heavy work on user activity

- **Pillars improved (P+):** P1, P3
- **Pillars risked (P-):** P2
- **Enforcement location:**
  - new scheduler plugin (builtin): job admission based on activity
  - governor API used by all heavy workers
- **Regression detection:**
  - Test: ACTIVE mode prevents OCR/VLM/embeddings/indexing jobs from running
  - Test: IDLE mode allows bounded enrichment and records budgets in journal
- **Implementation notes:**
  - Define job types: ingest (allowed always) vs enrich (idle/explicit only).
  - Scheduler polls activity signal and enforces Pattern D.
  - Provide explicit user command to run enrichment now.
- **Acceptance criteria:**
  - No heavy processing occurs while user active; enrichment happens predictably when allowed.

<a id="i045"></a>
### I045 — Input tracker exposes activity signals (not only journal)

- **Pillars improved (P+):** P1, P2
- **Pillars risked (P-):** P3
- **Enforcement location:**
  - input_windows exposes aggregated activity signal channel to governor
- **Regression detection:**
  - Test: simulated input produces immediate ACTIVE signal
  - Test: inactivity decays to IDLE after configured timeout
- **Implementation notes:**
  - Define activity signal: last_input_ts_utc + rolling intensity metrics.
  - Publish to kernel context or a small shared store.
- **Acceptance criteria:**
  - Scheduler has an authoritative, low-latency activity signal.

<a id="i046"></a>
### I046 — Capture emits telemetry (queues, drops, lag, CPU)

- **Pillars improved (P+):** P1, P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - capture pipeline emits telemetry events and exposes metrics endpoint
- **Regression detection:**
  - Test: telemetry includes queue depths, drops, lag, CPU
  - Websocket (I83) streams telemetry with stable schema
- **Implementation notes:**
  - Emit periodic `telemetry.capture` records (derived/monitoring).
  - Keep telemetry lightweight and rate-limited in ACTIVE mode.
- **Acceptance criteria:**
  - Performance issues are observable without instrumenting code manually.

<a id="i047"></a>
### I047 — Governor outputs feed backpressure and job admission

- **Pillars improved (P+):** P1
- **Pillars risked (P-):** P2
- **Enforcement location:**
  - governor decisions affect capture rate/quality and enrichment admission
- **Regression detection:**
  - Integration test: governor changes lead to fps/quality changes within bounded time
- **Implementation notes:**
  - Expose governor outputs: allowed fps range, max CPU%, allow_enrich boolean.
  - Capture controller (I2/I24) consumes these outputs.
- **Acceptance criteria:**
  - System responds quickly and deterministically to activity and pressure changes.

<a id="i048"></a>
### I048 — Immediate ramp down on user input (cancel/deprioritize heavy jobs)

- **Pillars improved (P+):** P1, P3
- **Pillars risked (P-):** P2
- **Enforcement location:**
  - scheduler cancels/deprioritizes heavy jobs on new input events
- **Regression detection:**
  - Test: user input interrupts ongoing enrichment within timeout budget
- **Implementation notes:**
  - All heavy jobs must be cancellable and check cancellation token at chunk boundaries.
  - On ACTIVE transition, scheduler pauses queues and releases GPU leases.
- **Acceptance criteria:**
  - User interaction immediately restores invisibility by halting heavy work.

<a id="i116"></a>
### I116 — Model execution budgets per idle window

- **Pillars improved (P+):** P1, P3
- **Pillars risked (P-):** P2
- **Enforcement location:**
  - scheduler budgets for model execution (CPU/GPU time, tokens, batch sizes)
- **Regression detection:**
  - Test: budgets enforced; jobs stop/continue across idle windows without violating budget
- **Implementation notes:**
  - Define per-job and per-window budgets: max seconds, max items, max VRAM.
  - Record budget usage in telemetry/journal for audit and tuning.
- **Acceptance criteria:**
  - ML workloads are bounded and cannot starve the system.

<a id="i117"></a>
### I117 — Preemption/chunking for long jobs

- **Pillars improved (P+):** P1, P2
- **Pillars risked (P-):** None
- **Enforcement location:**
  - all long jobs implemented as chunked work units with checkpoints
- **Regression detection:**
  - Test: job can be paused/resumed without redoing completed work
- **Implementation notes:**
  - Define checkpointing per job: last processed evidence_id/span.
  - Persist checkpoints in derived store; ledger transitions record progress.
- **Acceptance criteria:**
  - Heavy processing is preemptible and resumes deterministically.


## Phase 6: Security + egress hardening

Least privilege plugins, subprocess sandbox, key separation/rotation, egress ledgering.

**Entry criteria:** Phase 5 exit criteria met; relevant gates passing.

**Exit criteria (minimum):**

- All items in this phase have tests/gates in place and passing.
- No pillar regression under the listed regression detection.
- Doctor reports clean or only explicitly acknowledged warnings.

### Work items

<a id="i049"></a>
### I049 — Egress gateway must be subprocess-hosted; kernel network-denied

- **Pillars improved (P+):** P3, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - process model: kernel has network denied; egress plugin runs in subprocess
  - network guard applied at OS/process boundary where possible
- **Regression detection:**
  - Security test: kernel cannot reach network even if code tries
  - Test: egress plugin can reach allowlisted endpoints only
- **Implementation notes:**
  - Move all network use into subprocess-hosted plugins.
  - Block sockets in kernel process (policy + platform enforcement).
  - Egress gateway is the only component granted network capability.
- **Acceptance criteria:**
  - Network access is centralized, auditable, and policy-controlled.

<a id="i050"></a>
### I050 — Minimize inproc_allowlist; prefer subprocess hosting

- **Pillars improved (P+):** P3, P1
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - plugin registry: inproc_allowlist minimized; default subprocess
- **Regression detection:**
  - Gate: fail if new inproc plugin added without security justification entry
- **Implementation notes:**
  - Move non-latency-critical plugins out-of-proc.
  - Allow inproc only for capture primitives that require minimal overhead.
- **Acceptance criteria:**
  - Kernel attack surface reduced while keeping capture performance.

<a id="i051"></a>
### I051 — Capability bridging for subprocess plugins (real capability plumbing)

- **Pillars improved (P+):** P2, P3, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - subprocess host runner provides real capability access (not None)
- **Regression detection:**
  - Test: subprocess plugin receives only declared capabilities and can operate
- **Implementation notes:**
  - Define capability RPC endpoints for safe operations (storage, journal, ledger).
  - Host enforces allowlist of capability methods per plugin manifest.
- **Acceptance criteria:**
  - Subprocess plugins are first-class and do not require inproc hosting to function.

<a id="i052"></a>
### I052 — Enforce least privilege per plugin manifest

- **Pillars improved (P+):** P3, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - plugin manifest declares required capabilities; loader enforces deny-by-default
- **Regression detection:**
  - Test: plugin without declared capability cannot access it
- **Implementation notes:**
  - Add manifest field `capabilities_required`.
  - Host constructs a capability proxy exposing only allowed methods.
- **Acceptance criteria:**
  - Least privilege is enforced mechanically.

<a id="i053"></a>
### I053 — Enforce filesystem permission policy declared by plugins

- **Pillars improved (P+):** P3
- **Pillars risked (P-):** P1, P2
- **Enforcement location:**
  - filesystem sandboxing for subprocess plugins
  - manifest-declared read/readwrite paths enforced
- **Regression detection:**
  - Test: plugin cannot read outside allowed roots (integration)
- **Implementation notes:**
  - Prefer OS mechanisms (job object + restricted token) on Windows.
  - Fallback: enforce via brokered file APIs; deny direct filesystem access where feasible.
- **Acceptance criteria:**
  - Plugins cannot exfiltrate or tamper with files beyond their declared scope.

<a id="i054"></a>
### I054 — Strengthen Windows job object restrictions (limits)

- **Pillars improved (P+):** P3
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - Windows job object: CPU/memory limits, kill-on-close, child restrictions
- **Regression detection:**
  - Test: runaway plugin is terminated and reported
- **Implementation notes:**
  - Add limits to job object; configure per plugin class (capture vs enrichment).
  - Record terminations as security/audit events.
- **Acceptance criteria:**
  - Untrusted/hung plugins are contained without harming system stability.

<a id="i055"></a>
### I055 — Sanitize subprocess env; pin caches; disable proxies

- **Pillars improved (P+):** P3, P1
- **Pillars risked (P-):** P2
- **Enforcement location:**
  - subprocess environment sanitizer in host
- **Regression detection:**
  - Test: proxy env vars removed; cache dirs pinned
- **Implementation notes:**
  - Remove proxy env vars by default; set deterministic cache directories.
  - Set offline flags for ML libs unless explicitly allowed for model download jobs.
- **Acceptance criteria:**
  - Plugin behavior is deterministic and not affected by ambient environment.

<a id="i056"></a>
### I056 — Plugin RPC timeouts and watchdogs

- **Pillars improved (P+):** P1, P3
- **Pillars risked (P-):** None
- **Enforcement location:**
  - plugin RPC layer: timeouts + watchdog to restart hung plugins
- **Regression detection:**
  - Test: hung plugin call times out and system recovers without deadlock
- **Implementation notes:**
  - Add per-call timeout; on repeated timeouts restart plugin process.
  - Surface errors via alerts and journal.
- **Acceptance criteria:**
  - Plugin failures do not stall capture or UI.

<a id="i057"></a>
### I057 — Max message size limits in plugin RPC protocol

- **Pillars improved (P+):** P3, P1
- **Pillars risked (P-):** None
- **Enforcement location:**
  - plugin RPC protocol enforces max message sizes and streaming
- **Regression detection:**
  - Test: oversized message rejected; chunked streaming used for large blobs
- **Implementation notes:**
  - Set size limits for JSON messages.
  - Use streaming APIs for media blobs; never send large blobs in JSON RPC.
- **Acceptance criteria:**
  - IPC is resilient and cannot be abused for memory exhaustion.

<a id="i058"></a>
### I058 — Harden hashing against symlinks / filesystem nondeterminism

- **Pillars improved (P+):** P3, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - hashing policy: symlink handling defined and enforced
- **Regression detection:**
  - Test: symlinks in plugin root are rejected or hashed deterministically
- **Implementation notes:**
  - Decide and document: disallow symlinks in plugin roots (recommended).
  - Enforce during plugin lock hashing and plugin load.
- **Acceptance criteria:**
  - Hashing cannot be bypassed via filesystem tricks.

<a id="i059"></a>
### I059 — Secure vault file permissions (Windows ACLs)

- **Pillars improved (P+):** P3
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - vault and data dirs created with restrictive ACLs on Windows
- **Regression detection:**
  - Test: created files are not world-readable (platform-dependent assertions)
- **Implementation notes:**
  - On Windows, set ACL to current user only for vault/keys.
  - Doctor checks and warns if permissions are too broad.
- **Acceptance criteria:**
  - Secrets and encrypted stores are protected by OS permissions.

<a id="i060"></a>
### I060 — Separate keys by purpose (metadata/media/tokenization/anchor)

- **Pillars improved (P+):** P3, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - key manager defines separate keys per purpose + key ids
- **Regression detection:**
  - Test: rotating one key does not break others; derived artifacts remain readable as policy dictates
- **Implementation notes:**
  - Define key namespaces: metadata, media, tokenizer, anchors.
  - Store key ids in headers and metadata; support multiple active keys for rotation.
- **Acceptance criteria:**
  - Key separation limits blast radius and supports safe rotation.

<a id="i061"></a>
### I061 — Anchor signing (HMAC/signature) with separate key domain

- **Pillars improved (P+):** P3, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - anchor plugin uses HMAC/signature over ledger head
- **Regression detection:**
  - Test: anchor verify fails if anchor modified or wrong key used
- **Implementation notes:**
  - Select signing mechanism: HMAC (symmetric) or signature (asymmetric).
  - Store signing key in separate key domain (DPAPI-protected).
- **Acceptance criteria:**
  - Anchors provide tamper evidence independent of ledger storage.

<a id="i062"></a>
### I062 — Add verify commands (ledger/anchors/evidence)

- **Pillars improved (P+):** P4, P3
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - verify CLI/API: `verify ledger`, `verify anchors`, `verify evidence`
- **Regression detection:**
  - Golden verification suite passes; tamper cases fail
- **Implementation notes:**
  - Ledger verify: recompute chain; anchor verify: verify signatures; evidence verify: hash checks.
  - Expose via UX facade for UI integration.
- **Acceptance criteria:**
  - Users can validate integrity with deterministic tooling.

<a id="i063"></a>
### I063 — Audit security events in ledger (key rotations, lock updates, config)

- **Pillars improved (P+):** P4, P3
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - ledger event types for security-relevant operations
- **Regression detection:**
  - Test: key rotation and lock updates emit ledger entries
- **Implementation notes:**
  - Record: key rotations, plugin lock updates, config changes, dangerous ops approvals.
  - Include actor identity (local user) and timestamps.
- **Acceptance criteria:**
  - Security posture changes are auditable and tamper-evident.

<a id="i064"></a>
### I064 — Dependency pinning + hash checking (supply chain)

- **Pillars improved (P+):** P3, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - runtime dependency verification and build-time pinning
- **Regression detection:**
  - CI verifies dependency hashes; runtime doctor reports mismatches
- **Implementation notes:**
  - Combine with Phase 0 lockfile (I88).
  - At runtime, report installed package versions and compare to manifest where feasible.
- **Acceptance criteria:**
  - Supply chain drift is detected and controlled.

<a id="i119"></a>
### I119 — Persist entity-tokenizer key id/version; version tokenization

- **Pillars improved (P+):** P2, P4, P3
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - tokenizer plugin stores key id/version used for each tokenization
- **Regression detection:**
  - Test: tokenization output is stable under same key id; rotation yields new version
- **Implementation notes:**
  - Persist tokenizer key id and version in each tokenized record.
  - Support resolving historical tokens by keeping old key versions as needed.
- **Acceptance criteria:**
  - Tokenization is reproducible and rotation-aware.

<a id="i120"></a>
### I120 — Ledger sanitized egress packets (hash + schema version)

- **Pillars improved (P+):** P4, P3
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - egress gateway writes ledger entry for each sanitized outbound packet
- **Regression detection:**
  - Test: egress attempt emits `egress.packet` ledger entry with hash + schema version
- **Implementation notes:**
  - Ledger `egress.packet` includes: sanitized payload hash, destination policy id,
  - schema version, approval id (if UI approved), and result (sent/blocked).
- **Acceptance criteria:**
  - Outbound actions are fully auditable without storing raw sensitive payloads.


## Phase 7: FastAPI UX facade + Web Console

Canonical UI, UX facade parity for CLI, approval workflows.

**Entry criteria:** Phase 6 exit criteria met; relevant gates passing.

**Exit criteria (minimum):**

- All items in this phase have tests/gates in place and passing.
- No pillar regression under the listed regression detection.
- Doctor reports clean or only explicitly acknowledged warnings.

### Work items

<a id="i078"></a>
### I078 — FastAPI UX facade as canonical interface

- **Pillars improved (P+):** P1, P2, P4, P3
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - new FastAPI app provides canonical UX facade endpoints
  - kernel exposes only internal APIs; UI/CLI call facade
- **Regression detection:**
  - API contract tests: endpoints stable and validated against schemas
  - Security: binds to localhost by default; requires auth token (I82)
- **Implementation notes:**
  - Define endpoints: doctor, config get/set, plugins list/approve,
  - run start/stop, query, verify, export proof bundles, model downloads.
  - Responses are structured and include answer state + citations.
- **Acceptance criteria:**
  - All user interactions route through a single, testable facade.

<a id="i079"></a>
### I079 — CLI parity: CLI calls shared UX facade functions

- **Pillars improved (P+):** P2, P4, P1
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - CLI uses shared UX facade functions (no direct kernel calls)
- **Regression detection:**
  - Test: CLI commands produce identical results as API endpoints
- **Implementation notes:**
  - Extract facade logic into a shared module used by both API and CLI.
  - Ensure CLI output is derived from structured responses.
- **Acceptance criteria:**
  - UI/CLI parity is enforced and drift is prevented.

<a id="i080"></a>
### I080 — Web Console UI (status/timeline/query/proof/plugins/keys)

- **Pillars improved (P+):** P1, P2, P4
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - Web Console served by FastAPI (or static assets) as sole maintained UI
- **Regression detection:**
  - UI smoke tests: load pages and call API endpoints (headless)
  - API snapshot tests for UI-critical views
- **Implementation notes:**
  - Minimal but complete views: status, timeline, query with citations,
  - proof/verify dashboard, plugins, keys, settings, jobs/scheduler.
  - All displays resolve citations via resolver (I71/I42).
- **Acceptance criteria:**
  - Web UI covers all critical workflows without requiring CLI.

<a id="i081"></a>
### I081 — Alerts panel driven by journal events

- **Pillars improved (P+):** P1, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - alerts derived from journal/telemetry streams
- **Regression detection:**
  - Test: disk pressure and capture drops appear as alerts
- **Implementation notes:**
  - Define alert types and severity thresholds in config.
  - Store alerts as derived records; show current and historical alerts.
- **Acceptance criteria:**
  - Operational problems are visible immediately with actionable context.

<a id="i082"></a>
### I082 — Local-only auth boundary (bind localhost + token)

- **Pillars improved (P+):** P3
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - API auth middleware: token-based auth; localhost binding by default
- **Regression detection:**
  - Security test: state-changing endpoints require auth token
- **Implementation notes:**
  - Generate local token on first run; store in protected vault.
  - Support explicit remote binding only when configured, with stronger auth.
- **Acceptance criteria:**
  - Local API is not accidentally exposed or writable without authorization.

<a id="i083"></a>
### I083 — Websocket for live telemetry

- **Pillars improved (P+):** P1, P2
- **Pillars risked (P-):** P3
- **Enforcement location:**
  - websocket endpoint streams telemetry and job status
- **Regression detection:**
  - Test: websocket schema stable and rate-limited
- **Implementation notes:**
  - Stream: capture telemetry (I46), scheduler state (I44), alerts (I81).
  - Rate-limit and require auth token; avoid leaking sensitive raw data.
- **Acceptance criteria:**
  - UI can display live status without polling overhead.

<a id="i121"></a>
### I121 — Egress approval workflow in UI

- **Pillars improved (P+):** P3, P4, P2
- **Pillars risked (P-):** P1
- **Enforcement location:**
  - UI + facade implement explicit approval flow for any outbound egress
- **Regression detection:**
  - Test: egress blocked without approval; approved egress logs approval id + packet hash (I120)
- **Implementation notes:**
  - UI shows leak-check summary (sanitizer report) and destination policy.
  - Approval produces a short-lived token bound to payload hash and destination.
  - Egress gateway requires approval token to send.
- **Acceptance criteria:**
  - Outbound actions are user-controlled, auditable, and sanitized by default.


## Phase 8: Optional expansion plugins

Clipboard, file activity, hot-reload; only after core verification is solid.

**Entry criteria:** Phase 7 exit criteria met; relevant gates passing.

**Exit criteria (minimum):**

- All items in this phase have tests/gates in place and passing.
- No pillar regression under the listed regression detection.
- Doctor reports clean or only explicitly acknowledged warnings.

### Work items

<a id="i114"></a>
### I114 — Clipboard capture plugin (local-only, append-only)

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P3, P1
- **Enforcement location:**
  - new clipboard capture plugin (subprocess-hosted by default)
- **Regression detection:**
  - Test: disabled by default; when enabled, records are append-only and ledgered
  - Security: redaction policy for sensitive clipboard types (optional) is explicit
- **Implementation notes:**
  - Capture clipboard changes with timestamps and type metadata.
  - Store clipboard content as evidence (Pattern A) locally encrypted.
  - Integrate with scheduler: no heavy parsing while ACTIVE.
- **Acceptance criteria:**
  - Clipboard history is captured locally with provenance and controlled overhead.

<a id="i115"></a>
### I115 — File activity capture plugin (USN journal / watcher)

- **Pillars improved (P+):** P2, P4
- **Pillars risked (P-):** P3, P1
- **Enforcement location:**
  - new file activity plugin (Windows USN journal or watcher)
- **Regression detection:**
  - Test: disabled by default; when enabled, events are time-ordered and searchable
- **Implementation notes:**
  - Prefer USN journal for low-overhead file change timelines.
  - Store as append-only evidence: file path (normalized), operation, timestamps.
  - Avoid capturing file contents unless explicitly enabled (separate plugin).
- **Acceptance criteria:**
  - File activity timeline can be correlated with other evidence by time.

<a id="i122"></a>
### I122 — Plugin hot-reload with hash verification and safe swap

- **Pillars improved (P+):** P1, P2, P3, P4
- **Pillars risked (P-):** P3, P1
- **Enforcement location:**
  - plugin manager supports hot-reload for non-core plugins with hash verification
- **Regression detection:**
  - Test: hot-reload updates plugin only if lockfile updated and verified
  - Test: in-flight jobs are drained/cancelled safely on reload
- **Implementation notes:**
  - Watch plugin directories for changes (or on explicit reload command).
  - Verify plugin hash against lockfile; refuse unsigned/unknown changes.
  - Swap plugin instance with state handoff protocol or cold restart.
- **Acceptance criteria:**
  - Plugins can be updated without downtime while preserving security and determinism.

