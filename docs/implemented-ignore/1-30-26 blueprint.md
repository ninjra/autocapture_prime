# 1. System Context & Constraints

Project_Scope: Local-first “memory replacement” system that captures raw screen (and audio via plugin) on Windows, stores media indefinitely (encrypted at rest), and provides natural-language Q&A with evidence/citations + a “What happened today” flow, under strict localhost-only exposure and plugin-first extensibility.
Primary_Source_File: 
Implementation_Target:
MUST: Implement 100% of items in the attached source material as recommended, optimized for the Four Pillars, and create `AGENTS.md`. (Sources: [SRC-001])
Four_Pillars:
P1_Performant: Minimize end-to-end user-visible completion time; prefer simple, fast, low-friction flows. (Sources: [SRC-001])
P2_Accurate: Do not exceed evidence; deterministic when possible; never fabricate; surface when uncitable/indeterminate. (Sources: [SRC-010, SRC-044, SRC-152])
P3_Secure: Localhost-only; deny-by-default privileges; encrypted at rest; sanitize only on explicit export; resist plugin blast radius. (Sources: [SRC-003, SRC-009, SRC-080, SRC-081, SRC-084, SRC-085])
P4_Citable: Evidence-backed UI + answers; citations resolve to spans/media; provenance and lineage are visible and auditable. (Sources: [SRC-010, SRC-044, SRC-133, SRC-134])

Architectural_Hard_Rules:

* Environment:

  * Single user, single machine: Windows 11 x64; 64 GB RAM; RTX 4090. (Sources: [SRC-002])
  * Monitor footprint: 1 × 8K monitor. (Sources: [SRC-141])
* Network/Exposure:

  * UI/API MUST never be exposed beyond `127.0.0.1`. (Sources: [SRC-003])
  * Enforce loopback-only via bind enforcement + offline guard + firewall rule; fail closed if not loopback. (Sources: [SRC-080])
* Retention & Privacy:

  * Raw-first local capture: no masking/filtering/deletion locally; media stored indefinitely. (Sources: [SRC-004])
  * No-deletion mode MUST remove/disable delete endpoints + retention pruning; replace with archive/migrate. (Sources: [SRC-020])
  * Cloud is optional and only via explicit egress/export with sanitization; local decrypted viewing remains possible. (Sources: [SRC-009])
  * Export-only sanitization MUST never mutate local raw store. (Sources: [SRC-084])
* Capture Semantics:

  * Change-driven capture: any visible change must result in a new stored media artifact (hash differs ⇒ saved; hash identical ⇒ skip). (Sources: [SRC-005])
  * Capture triggered on any HID input; additionally, while user active, check screenshot/hash at least every 0.5 seconds between HID. (Sources: [SRC-145])
  * Capture enabled during HID activity; must remain reliable under distraction/fatigue/mis-clicks. (Sources: [SRC-006])
  * Fullscreen/DRM-protected surfaces: best effort capture with explicit “unavailable” markers. (Sources: [SRC-144])
* Processing & Resource Governance:

  * While user is active: only kernel + capture pipeline may run; all other processing must pause. (Sources: [SRC-007])
  * When idle: GPU may saturate; CPU and RAM must never exceed 50% usage (hard constraint). (Sources: [SRC-008])
  * Enforce CPU/RAM caps with alerts + auto-throttle; implement Job Objects for enforcement (workers + plugin subprocesses). (Sources: [SRC-079, SRC-091])
  * GPU preemption on activity: release GPU allocations immediately on user input. (Sources: [SRC-099])
* Interaction & Truthfulness:

  * Primary interaction: natural-language Q&A with citations and a “What happened today” flow. (Sources: [SRC-010])
  * “Citations required” is default; never fabricate; deterministic when possible; clearly state when cannot cite/determine. (Sources: [SRC-044, SRC-152])
* Plugins:

  * Plugin-first architecture: plugins are first-class and can override core behavior. (Sources: [SRC-011])
  * Plugin installation MAY fetch from internet (pip/git) via explicit user action; still gated by policy and audit. (Sources: [SRC-148, SRC-083, SRC-085])
  * Untrusted plugins run out-of-process with IPC + JobObject caps. (Sources: [SRC-054, SRC-091])
* Encryption & Unlock:

  * Default-on at-rest encryption (DB+media), Windows Hello unlock + auto-lock. (Sources: [SRC-081])
  * Remove unlock token from URL; use secure in-memory session and short TTL. (Sources: [SRC-082])
* Audio:

  * Audio capture is required as a separate capture plugin. (Sources: [SRC-142])

Environment_Standards:
Localhost_Only_Standard:
- Runtime MUST refuse non-loopback bind_host and record an explicit audit/log event for refused binds. (Sources: [SRC-003, SRC-080, SRC-083])
No_Deletion_Standard:
- Any feature that would delete/unlink local raw media MUST be absent or replaced by archive/migrate. (Sources: [SRC-004, SRC-020])
Provenance_Standard:
- Every derived artifact MUST carry lineage fields (`job_id`, input frames, input hashes, engine+version). (Sources: [SRC-133, SRC-035])
Foreground_Gating_Standard:
- Background workers MUST be pausable to 0 while HID active; UI must reflect paused reason. (Sources: [SRC-007, SRC-041, SRC-074])
Resource_Budget_Standard:
- CPU/RAM caps MUST be enforced (not advisory) using Job Objects, with emitted throttle events and UI visibility. (Sources: [SRC-008, SRC-091, SRC-079])
Export_Standard:
- Sanitization happens only in export pipeline; local raw store is immutable w.r.t sanitization. (Sources: [SRC-009, SRC-084])
Auditability_Standard:
- Privileged actions (unlock/export/plugin/config) MUST be append-only auditable. (Sources: [SRC-083])

Source_Index:

* SRC-001:
  Type: Requirement
  Priority: MUST
  Quote: "implement 100% of these items ... also agents.md needs to be created"
  Notes: Applies to the attached source doc items + `AGENTS.md`.

* SRC-002:
  Type: Constraint
  Priority: MUST
  Quote: "Single user, single machine (Windows 11 x64; 64 GB RAM; RTX 4090)."
  Notes: Runtime assumptions for performance budgets and platform integrations.

* SRC-003:
  Type: Constraint
  Priority: MUST
  Quote: "Strictly localhost: UI/API never exposed beyond `127.0.0.1`."
  Notes: Enforce at runtime, not just config.

* SRC-004:
  Type: Constraint
  Priority: MUST
  Quote: "Capture policy is “raw-first”: no masking/filtering/deletion locally; media stored indefinitely."
  Notes: Implies no local redaction/deletion; only export sanitization.

* SRC-005:
  Type: Constraint
  Priority: MUST
  Quote: "any visible change ... must result in a new stored media artifact (hash differs ⇒ saved; hash identical ⇒ skip)."
  Notes: Strict change-driven capture and exact dedupe.

* SRC-006:
  Type: Constraint
  Priority: MUST
  Quote: "Capture is enabled during HID/user activity; capture must remain reliable under distraction/fatigue/mis-clicks."
  Notes: Drives robust UX and “never wonder if it worked”.

* SRC-007:
  Type: Constraint
  Priority: MUST
  Quote: "While the user is active, only kernel + capture pipeline may run; all other processing must pause."
  Notes: Foreground gating is non-negotiable.

* SRC-008:
  Type: Constraint
  Priority: MUST
  Quote: "When idle, GPU may saturate; CPU and RAM must never exceed 50% usage (hard constraint)."
  Notes: Enforce via Job Objects + dynamic budgeter.

* SRC-009:
  Type: Constraint
  Priority: MUST
  Quote: "Cloud is optional and only via explicit egress/export with sanitization"
  Notes: No implicit network upload; export-only.

* SRC-010:
  Type: Requirement
  Priority: MUST
  Quote: "Primary interaction is natural-language Q&A with citations and a “What happened today” flow."
  Notes: UI/UX must center this.

* SRC-011:
  Type: Constraint
  Priority: MUST
  Quote: "Plugin-first architecture remains: plugins are first-class and can override core behavior."
  Notes: Core must be overrideable; conflicts must be manageable.

* SRC-012:
  Type: Data
  Priority: [MISSING_VALUE]
  Quote: "Capture config already exposes knobs for `diff_epsilon`, `duplicate_threshold`, FPS bounds"
  Notes: Reuse existing config knobs; extend with new ones only as needed.

* SRC-013:
  Type: Data
  Priority: [MISSING_VALUE]
  Quote: "Capture orchestrator already has ROI enqueue backpressure"
  Notes: Build disk/queue guardrails on existing backpressure primitives.

* SRC-014:
  Type: Data
  Priority: [MISSING_VALUE]
  Quote: "Metrics already exist ... `captures_taken_total` ... `process_cpu_percent`, `process_rss_mb`"
  Notes: Extend existing metrics; do not fork redundant metrics.

* SRC-015:
  Type: Data
  Priority: [MISSING_VALUE]
  Quote: "Plugin system already supports discovery ... enable/disable/lock, safe mode, and a policy gate concept."
  Notes: Hardening builds atop existing plugin manager + PolicyGate.

* SRC-016:
  Type: Data
  Priority: [MISSING_VALUE]
  Quote: "destructive endpoints ... (`/api/delete_range`, `/api/delete_all`) which conflict with your ... requirement."
  Notes: Must be removed/disabled (see SRC-020).

* SRC-017:
  Type: Data
  Priority: [MISSING_VALUE]
  Quote: "MediaStore supports encrypted media files (e.g., `.acenc`)"
  Notes: Use as baseline for default encryption.

* SRC-018:
  Type: Data
  Priority: [MISSING_VALUE]
  Quote: "Processing lineage already threads through `frame_hash` ... `ArtifactRecord.derived_from`"
  Notes: Extend lineage to JobRun + dual hashes.

* SRC-019:
  Type: Requirement
  Priority: SHOULD
  Quote: "I-1 Add an append-only Capture Journal + reconciler (staging→committed)"
  Notes: Crash-safe capture persistence and provable capture events.

* SRC-020:
  Type: Requirement
  Priority: SHOULD
  Quote: "I-2 Implement No-Deletion Mode: remove/disable delete endpoints + retention pruning"
  Notes: Must align with raw-first indefinite retention.

* SRC-021:
  Type: Requirement
  Priority: SHOULD
  Quote: "I-3 Add preset “Memory Replacement (Raw)”"
  Notes: Align capture settings with strict change-driven policy.

* SRC-022:
  Type: Requirement
  Priority: SHOULD
  Quote: "I-4 Create segment-based media store (append-only) with per-frame hashes + periodic keyframes"
  Notes: Needed for indefinite retention scaling.

* SRC-023:
  Type: Requirement
  Priority: SHOULD
  Quote: "I-5 Two-tier disk watermarks: soft backpressure + hard “CAPTURE HALTED: DISK LOW” banner"
  Notes: Make disk-failure obvious; no silent capture loss.

* SRC-024:
  Type: Requirement
  Priority: SHOULD
  Quote: "I-6 Add encrypted local backup + restore workflow (external drive)"
  Notes: Required for long-term retention and migration.

* SRC-025:
  Type: Requirement
  Priority: SHOULD
  Quote: "I-7 Persist immutable config snapshot + plugin versions per session_id"
  Notes: Reproducibility and audit for any frame/artifact.

* SRC-026:
  Type: Requirement
  Priority: SHOULD
  Quote: "I-8 Run startup integrity sweep: DB↔media existence + hash check; surface issues"
  Notes: Convert corruption into visible “broken evidence”.

* SRC-027:
  Type: Requirement
  Priority: SHOULD
  Quote: "I-9 Crash-loop safe mode: if restarts >N, enter capture-only + diagnostics prompt"
  Notes: Preserve capture while preventing repeated thrash.

* SRC-028:
  Type: Requirement
  Priority: SHOULD
  Quote: "I-10 Split kernel into Windows Service (capture+DB) and separate user-space UI/processing group"
  Notes: Improve stability; capture survives UI failures/restarts.

* SRC-029:
  Type: Requirement
  Priority: SHOULD
  Quote: "II-1 Define canonical Frame v2 schema and treat it as the single source of truth"
  Notes: Reduce model drift; simplify UI and lineage.

* SRC-030:
  Type: Requirement
  Priority: SHOULD
  Quote: "II-2 Add `capture_trigger` + `change_reason` + diff stats to metadata"
  Notes: Auditable “why captured”.

* SRC-031:
  Type: Requirement
  Priority: SHOULD
  Quote: "II-3 Store two hashes: `raw_pixels_hash` ... + `encoded_bytes_hash`"
  Notes: Proof of pixel uniqueness + encoded storage verification.

* SRC-032:
  Type: Requirement
  Priority: SHOULD
  Quote: "II-4 Always surface core metadata at top of UI item detail"
  Notes: Reduce cognitive load; instant verification.

* SRC-033:
  Type: Requirement
  Priority: SHOULD
  Quote: "II-5 Compute `trust_level` (green/yellow/red) ... for each day/session and each answer"
  Notes: Conservative trust warnings tied to evidence completeness.

* SRC-034:
  Type: Requirement
  Priority: SHOULD
  Quote: "II-6 Store provenance ledger head (`entry_hash`) in DB and show/export it"
  Notes: Tamper-evident pointer.

* SRC-035:
  Type: Requirement
  Priority: SHOULD
  Quote: "II-7 Standardize artifact metadata: `job_id`, `engine`, `engine_version`, `attempts`, `last_error`"
  Notes: Prove processing ran; debug failures.

* SRC-036:
  Type: Requirement
  Priority: SHOULD
  Quote: "II-8 Add HID-session rollups: `active_seconds`, `captures_taken`, `drops_by_reason`"
  Notes: Measure capture tied to activity.

* SRC-037:
  Type: Requirement
  Priority: SHOULD
  Quote: "II-9 Implement local-only entity hash map for export sanitization (salted, rotatable)"
  Notes: Export sanitization reversible locally.

* SRC-038:
  Type: Requirement
  Priority: SHOULD
  Quote: "II-10 Add stronger DB constraints (FK + NOT NULL where required)"
  Notes: Prevent invalid states that break citations.

* SRC-039:
  Type: Requirement
  Priority: SHOULD
  Quote: "III-1 Make all workers idempotent via `dedupe_key=(type, engine_version, input_hash)`"
  Notes: Safe replay; avoid duplicates.

* SRC-040:
  Type: Requirement
  Priority: SHOULD
  Quote: "III-2 Introduce a first-class JobRun model (job_id everywhere) + UI DAG"
  Notes: Proof of processing chain.

* SRC-041:
  Type: Requirement
  Priority: SHOULD
  Quote: "III-3 Enforce “active user ⇒ processing paused”: non-capture workers scale to 0"
  Notes: Foreground gating requirement.

* SRC-042:
  Type: Requirement
  Priority: SHOULD
  Quote: "III-4 Add deterministic replay engine (time range/frame_hash) that records diffs"
  Notes: Auditing and debugging without losing history.

* SRC-043:
  Type: Requirement
  Priority: SHOULD
  Quote: "III-5 Add processing watchdog + heartbeat escalation + auto-retry policy"
  Notes: Prevent silent stalls.

* SRC-044:
  Type: Requirement
  Priority: SHOULD
  Quote: "III-6 Make “citations required” the default answer policy"
  Notes: Block uncited hallucinations.

* SRC-045:
  Type: Requirement
  Priority: SHOULD
  Quote: "III-7 Store summaries as artifacts with input list + prompt/model hash"
  Notes: Reproducible, citable summaries.

* SRC-046:
  Type: Requirement
  Priority: SHOULD
  Quote: "III-8 Add per-job debug bundle export (inputs/hashes/versions/logs)"
  Notes: Actionable debugging.

* SRC-047:
  Type: Requirement
  Priority: SHOULD
  Quote: "III-9 Nightly (idle-only) DB↔index consistency sweeps with repair"
  Notes: Prevent drift that breaks retrieval/citations.

* SRC-048:
  Type: Requirement
  Priority: SHOULD
  Quote: "III-10 Add dynamic budgeter: maximize GPU while enforcing CPU<50%, RAM<50%"
  Notes: Hard QoS constraints.

* SRC-049:
  Type: Requirement
  Priority: SHOULD
  Quote: "IV-1 Redesign plugin IA: Installed / Catalog / Updates / Permissions / Health"
  Notes: Reduce operator error; lower cognitive load.

* SRC-050:
  Type: Requirement
  Priority: SHOULD
  Quote: "IV-2 Atomic install/update with staging + hash verification + rollback"
  Notes: Avoid half-installed states; support recovery.

* SRC-051:
  Type: Requirement
  Priority: SHOULD
  Quote: "IV-3 Compatibility gating ... in manifest"
  Notes: Block incompatible plugins.

* SRC-052:
  Type: Requirement
  Priority: SHOULD
  Quote: "IV-4 Two-phase enable: sandbox load → health check → enable"
  Notes: Safer enable; avoids crash loops.

* SRC-053:
  Type: Requirement
  Priority: SHOULD
  Quote: "IV-5 Permission UX ... require explicit approval"
  Notes: Least privilege, visible denials.

* SRC-054:
  Type: Requirement
  Priority: SHOULD
  Quote: "IV-6 Default “untrusted plugins run out-of-process” with IPC + JobObject caps"
  Notes: Contain failures and enforce budgets.

* SRC-055:
  Type: Requirement
  Priority: SHOULD
  Quote: "IV-7 Plugin health dashboard: last error, latency, memory, denials, restart count"
  Notes: Visibility and faster debugging.

* SRC-056:
  Type: Requirement
  Priority: SHOULD
  Quote: "IV-8 Safe mode recovery wizard (tray + UI)"
  Notes: Recover from bad plugin/updates quickly.

* SRC-057:
  Type: Requirement
  Priority: SHOULD
  Quote: "IV-9 Optional plugin signing + trust levels"
  Notes: Supply-chain integrity option.

* SRC-058:
  Type: Requirement
  Priority: SHOULD
  Quote: "IV-10 Unified plugin logs/traces (per-plugin view)"
  Notes: Debugability.

* SRC-059:
  Type: Requirement
  Priority: SHOULD
  Quote: "explicit priority + conflict UI; block enable unless resolved. (Rec IV-11)"
  Notes: Plugin override collisions must be deterministic and visible.

* SRC-060:
  Type: Requirement
  Priority: SHOULD
  Quote: "V-1 Make Home = Today + Omnibox (Q&A-first)"
  Notes: Q&A-first UX.

* SRC-061:
  Type: Requirement
  Priority: SHOULD
  Quote: "V-2 Session-grouped timeline (HID sessions + app focus) with gap markers"
  Notes: “What happened” reasoning under cognitive load.

* SRC-062:
  Type: Requirement
  Priority: SHOULD
  Quote: "V-3 Item detail view: raw media + metadata/provenance + processing status"
  Notes: Direct verification view.

* SRC-063:
  Type: Requirement
  Priority: SHOULD
  Quote: "V-4 “Explain answer” panel with retrieval trace + top spans"
  Notes: Visible citeability and trace.

* SRC-064:
  Type: Requirement
  Priority: SHOULD
  Quote: "V-5 Cognitive accessibility modes: low-choice UI + big targets + keyboard-first"
  Notes: Reduce mis-click risk.

* SRC-065:
  Type: Requirement
  Priority: SHOULD
  Quote: "V-6 Capture status panel everywhere (top bar + tray parity)"
  Notes: “Is it working?” always visible.

* SRC-066:
  Type: Requirement
  Priority: SHOULD
  Quote: "V-7 “Fast recall templates” (time/app/person)"
  Notes: Reduce cognitive effort.

* SRC-067:
  Type: Requirement
  Priority: SHOULD
  Quote: "V-8 “Proof chips” per answer ... with job_id + hashes"
  Notes: Proof-first answers.

* SRC-068:
  Type: Requirement
  Priority: SHOULD
  Quote: "V-9 Export flow (sanitized only) with preview + warnings + audit entry"
  Notes: Safe egress UX.

* SRC-069:
  Type: Requirement
  Priority: SHOULD
  Quote: "V-10 Tray companion ... remove delete actions"
  Notes: Tray must not offer deletion.

* SRC-070:
  Type: Requirement
  Priority: SHOULD
  Quote: "VI-1 Define “Frictionless Capture” SLOs and show them in UI"
  Notes: User-visible capture reliability metrics.

* SRC-071:
  Type: Requirement
  Priority: SHOULD
  Quote: "VI-2 Add metrics: `screen_change_detect_ms`, `persist_commit_ms`, queue depth p95"
  Notes: Latency and backlog observability.

* SRC-072:
  Type: Requirement
  Priority: SHOULD
  Quote: "VI-3 Diagnostics bundle generator (no raw media by default)"
  Notes: Actionable debug bundle.

* SRC-073:
  Type: Requirement
  Priority: SHOULD
  Quote: "VI-4 Correlation IDs everywhere: `frame_id`, `job_id`, `plugin_id` in logs"
  Notes: Traceability.

* SRC-074:
  Type: Requirement
  Priority: SHOULD
  Quote: "VI-5 Explicit pipeline state machine in UI"
  Notes: Prevent silent assumptions.

* SRC-075:
  Type: Requirement
  Priority: SHOULD
  Quote: "VI-6 Silent failure detector: HID active but no captures ⇒ alert event + tray notify"
  Notes: Detect worst-case silent pause/gap.

* SRC-076:
  Type: Requirement
  Priority: SHOULD
  Quote: "VI-7 Error budget tracking for drop rate and pipeline lag"
  Notes: Conservative trust signal input.

* SRC-077:
  Type: Requirement
  Priority: SHOULD
  Quote: "VI-8 Runbook integrated into UI (localhost-only, restore, safe mode)"
  Notes: Recovery UX.

* SRC-078:
  Type: Requirement
  Priority: SHOULD
  Quote: "VI-9 Idle-only self-heal tasks: orphan cleanup, reindex, vector sidecar checks"
  Notes: Self-maintenance without foreground impact.

* SRC-079:
  Type: Requirement
  Priority: SHOULD
  Quote: "VI-10 Enforce CPU/RAM caps with alerts + auto-throttle"
  Notes: Visible and automatic enforcement.

* SRC-080:
  Type: Requirement
  Priority: SHOULD
  Quote: "VII-1 Enforce loopback-only: bind host + offline guard + firewall rule"
  Notes: Hard security boundary.

* SRC-081:
  Type: Requirement
  Priority: SHOULD
  Quote: "VII-2 Default-on at-rest encryption (DB+media), Windows Hello unlock + auto-lock"
  Notes: Protect raw media at rest.

* SRC-082:
  Type: Requirement
  Priority: SHOULD
  Quote: "VII-3 Remove unlock token from URL; use secure in-memory session and short TTL"
  Notes: Prevent token leakage via URL.

* SRC-083:
  Type: Requirement
  Priority: SHOULD
  Quote: "VII-4 Append-only audit log for privileged actions (unlock/export/plugin/config)"
  Notes: Tamper-evident actions.

* SRC-084:
  Type: Requirement
  Priority: SHOULD
  Quote: "VII-5 Export-only sanitization ... never mutate local raw"
  Notes: Raw store remains untouched.

* SRC-085:
  Type: Requirement
  Priority: SHOULD
  Quote: "VII-6 Tighten PolicyGate defaults + per-plugin allowlists managed in UI"
  Notes: Least privilege.

* SRC-086:
  Type: Requirement
  Priority: SHOULD
  Quote: "VII-7 Add CSP + CSRF hardening even on localhost"
  Notes: Browser security.

* SRC-087:
  Type: Requirement
  Priority: SHOULD
  Quote: "VII-8 Secrets scanning + log redaction tests in CI"
  Notes: Prevent leakage.

* SRC-088:
  Type: Requirement
  Priority: SHOULD
  Quote: "VII-9 Enforce vendor binary SHA verification (ffmpeg/qdrant) and fail closed"
  Notes: Supply chain guard.

* SRC-089:
  Type: Requirement
  Priority: SHOULD
  Quote: "VII-10 Export review UI: show hashed entity dictionary locally (after unlock)"
  Notes: Human-in-the-loop export.

* SRC-090:
  Type: Requirement
  Priority: SHOULD
  Quote: "VIII-1 Default GPU encoding (`nvenc_webp`/`nvenc_avif`), lossless; CPU fallback ladder"
  Notes: Throughput while respecting CPU cap.

* SRC-091:
  Type: Requirement
  Priority: SHOULD
  Quote: "VIII-2 Enforce CPU/RAM caps with Windows Job Objects"
  Notes: Reliable enforcement.

* SRC-092:
  Type: Requirement
  Priority: SHOULD
  Quote: "VIII-3 Change-driven capture: Desktop Duplication dirty-rect based; no polling"
  Notes: Efficient strict change capture.

* SRC-093:
  Type: Requirement
  Priority: SHOULD
  Quote: "VIII-4 BLAKE3 raw frame hashing (pre-encode), parallelized"
  Notes: Fast hashing.

* SRC-094:
  Type: Requirement
  Priority: SHOULD
  Quote: "VIII-5 Short DB transactions + batched commits + fsync scheduling"
  Notes: Reduce DB contention.

* SRC-095:
  Type: Requirement
  Priority: SHOULD
  Quote: "VIII-6 Idle-only GPU OCR/embedding (TensorRT/ONNX) with memory guard"
  Notes: Maximize GPU in idle.

* SRC-096:
  Type: Requirement
  Priority: SHOULD
  Quote: "VIII-7 Optimize retrieval: lexical-first fallback, vector sidecar localhost"
  Notes: Responsive Q&A under paused processing.

* SRC-097:
  Type: Requirement
  Priority: SHOULD
  Quote: "VIII-8 Shard media paths by hash prefix (or segment store)"
  Notes: Filesystem scale.

* SRC-098:
  Type: Requirement
  Priority: SHOULD
  Quote: "VIII-9 Define latency budgets and track p95"
  Notes: Regression prevention.

* SRC-099:
  Type: Requirement
  Priority: SHOULD
  Quote: "VIII-10 GPU preemption on activity"
  Notes: Avoid foreground stutter.

* SRC-100:
  Type: Requirement
  Priority: SHOULD
  Quote: "IX-1 Golden dataset for capture→OCR→embedding→answer with citations"
  Notes: End-to-end regressions.

* SRC-101:
  Type: Requirement
  Priority: SHOULD
  Quote: "IX-2 Chaos tests: crash during persist, disk full, DB locked, encoder fail"
  Notes: Validate recovery paths.

* SRC-102:
  Type: Requirement
  Priority: SHOULD
  Quote: "IX-3 Migration tests with ledger continuity and citation validity"
  Notes: Upgrades must not break evidence.

* SRC-103:
  Type: Requirement
  Priority: SHOULD
  Quote: "IX-4 E2E “Today Q&A” test: asks question, checks citations resolve"
  Notes: Citeability stays real.

* SRC-104:
  Type: Requirement
  Priority: SHOULD
  Quote: "IX-5 Fuzz plugin manifests + install sources (zip/dir/pkg)"
  Notes: Harden plugin manager parsing.

* SRC-105:
  Type: Requirement
  Priority: SHOULD
  Quote: "IX-6 Resource budget tests: CPU/RAM never exceed 50%"
  Notes: Continuous enforcement verification.

* SRC-106:
  Type: Requirement
  Priority: SHOULD
  Quote: "IX-7 Windows integration tests for DirectX capture + RawInputListener"
  Notes: Platform-specific validation.

* SRC-107:
  Type: Requirement
  Priority: SHOULD
  Quote: "IX-8 Localhost-only security tests (bind + offline guard + CSP)"
  Notes: Prevent exposure regressions.

* SRC-108:
  Type: Requirement
  Priority: SHOULD
  Quote: "IX-9 Provenance chain tamper-detection tests"
  Notes: Proof system must prove.

* SRC-109:
  Type: Requirement
  Priority: SHOULD
  Quote: "IX-10 Accessibility test suite"
  Notes: Cognitive accessibility and usability.

* SRC-110:
  Type: Requirement
  Priority: SHOULD
  Quote: "Phase 0: No-deletion + strict raw capture preset + capture health UI + foreground gating"
  Notes: Implementation order guidance.

* SRC-111:
  Type: Requirement
  Priority: SHOULD
  Quote: "Phase 1: JobRun/lineage model + proof chips + citations-required answers"
  Notes: Implementation order guidance.

* SRC-112:
  Type: Requirement
  Priority: SHOULD
  Quote: "Phase 2: Indefinite retention scaling ... segment store + backup/restore + archive/migrate"
  Notes: Implementation order guidance.

* SRC-113:
  Type: Requirement
  Priority: SHOULD
  Quote: "Phase 3: Plugin manager hardening"
  Notes: Implementation order guidance.

* SRC-114:
  Type: Requirement
  Priority: SHOULD
  Quote: "“What happened today” digest (idle GPU) + evidence-backed summaries"
  Notes: Daily digest requirement.

* SRC-115:
  Type: Requirement
  Priority: SHOULD
  Quote: "Sanitized export packages with local reversible entity map"
  Notes: Export package feature.

* SRC-116:
  Type: Behavior
  Priority: SHOULD
  Quote: "Installed: enabled/disabled, version, trust level, last health, permissions summary"
  Notes: Plugin UI IA details.

* SRC-117:
  Type: Behavior
  Priority: SHOULD
  Quote: "Catalog: built-in + local directory + installed packages + “import bundle”"
  Notes: Plugin sources UI.

* SRC-118:
  Type: Behavior
  Priority: SHOULD
  Quote: "Updates: available updates, pinned versions, rollback points"
  Notes: Update UX details.

* SRC-119:
  Type: Behavior
  Priority: SHOULD
  Quote: "Permissions: matrix by plugin vs permission (`network`, `filesystem`, `shell`, `openai`)"
  Notes: Permissions UX details.

* SRC-120:
  Type: Behavior
  Priority: SHOULD
  Quote: "Health: self-tests, recent errors, resource usage"
  Notes: Plugin health UX details.

* SRC-121:
  Type: Behavior
  Priority: SHOULD
  Quote: "Install → validate manifest → compute hashes ... stage → activate"
  Notes: Install flow.

* SRC-122:
  Type: Behavior
  Priority: SHOULD
  Quote: "Enable → permission prompt → sandbox load → health check → activate"
  Notes: Enable flow.

* SRC-123:
  Type: Behavior
  Priority: SHOULD
  Quote: "Update → stage new → run self-test → atomic switch → keep rollback snapshot"
  Notes: Update flow.

* SRC-124:
  Type: Behavior
  Priority: SHOULD
  Quote: "Rollback → select previous snapshot → activate → record audit entry"
  Notes: Rollback flow.

* SRC-125:
  Type: Behavior
  Priority: SHOULD
  Quote: "Doctor (UI wrapper around existing `plugins doctor`)"
  Notes: Plugin doctor integration.

* SRC-126:
  Type: Requirement
  Priority: COULD
  Quote: "Per-plugin performance budgets and auto-throttle"
  Notes: Marked “Stretch goals”.

* SRC-127:
  Type: Requirement
  Priority: COULD
  Quote: "Extension override conflict resolver with explicit priority graph"
  Notes: Marked “Stretch goals”; complements SRC-059.

* SRC-128:
  Type: Requirement
  Priority: COULD
  Quote: "Signed update channels and “quarantine new plugin until observed stable for N hours”"
  Notes: Marked “Stretch goals”.

* SRC-129:
  Type: Requirement
  Priority: SHOULD
  Quote: "Add/standardize these user-facing metrics"
  Notes: Capture freshness/completeness/latency/resource safety metrics.

* SRC-130:
  Type: Data
  Priority: SHOULD
  Quote: "`Frame` ... fields: `frame_id` ... `raw_pixels_hash` ... `encoded_bytes_hash`"
  Notes: Minimal Frame v2 schema proposal.

* SRC-131:
  Type: Data
  Priority: SHOULD
  Quote: "`Artifact` ... fields: `artifact_type` ... `engine_version` ... `job_id` ... `derived_from`"
  Notes: Minimal Artifact schema proposal.

* SRC-132:
  Type: Data
  Priority: SHOULD
  Quote: "`CitableSpan` ... `span_id` ... `text`, `bbox_norm`, `span_hash`"
  Notes: Minimal citable span schema.

* SRC-133:
  Type: Constraint
  Priority: MUST
  Quote: "Lineage rule (non-negotiable) ... Every derived object must include: `job_id` ... `input hash(es)`"
  Notes: Hard requirement for provenance and proof.

* SRC-134:
  Type: Behavior
  Priority: SHOULD
  Quote: "For any answer: show citations → spans → frame → raw media"
  Notes: UI evidence drill-down requirement.

* SRC-135:
  Type: Behavior
  Priority: SHOULD
  Quote: "show job chain with timestamps and engine versions"
  Notes: Proof visibility requirement.

* SRC-136:
  Type: Behavior
  Priority: SHOULD
  Quote: "show “missing evidence” explicitly if media or spans are absent (conservative)"
  Notes: Conservative UX.

* SRC-137:
  Type: Data
  Priority: SHOULD
  Quote: "Home / “Today” view (Q&A-first)"
  Notes: Wireframe guidance.

* SRC-138:
  Type: Data
  Priority: SHOULD
  Quote: "Capture Status ... Per-monitor ... Queue ... Disk ... Recent alerts"
  Notes: Status panel guidance.

* SRC-139:
  Type: Data
  Priority: SHOULD
  Quote: "Plugin manager main screen"
  Notes: Plugin UI guidance.

* SRC-140:
  Type: Data
  Priority: SHOULD
  Quote: "Item detail view showing metadata + provenance + processing status"
  Notes: Item detail guidance.

* SRC-141:
  Type: Data
  Priority: MUST
  Quote: "How many monitors ... 1 8k"
  Notes: Hardware footprint affects capture configuration.

* SRC-142:
  Type: Requirement
  Priority: MUST
  Quote: "Do you want audio capture ... yes, as a separate capture plugin"
  Notes: Audio capture implemented via plugin interface.

* SRC-143:
  Type: Constraint
  Priority: MUST
  Quote: "no, i want everything captured"
  Notes: No capture pauses by app category; privacy via encryption and export controls.

* SRC-144:
  Type: Requirement
  Priority: MUST
  Quote: "yes best effort with explicit."
  Notes: Fullscreen/DRM capture must record explicit unavailability markers.

* SRC-145:
  Type: Constraint
  Priority: MUST
  Quote: "trigger ss on any HID input ... atleast every .5 seconds to check the hash"
  Notes: Capture trigger policy.

* SRC-146:
  Type: Decision
  Priority: SHOULD
  Quote: "you have to get this shit functioning before we worry about running out of space."
  Notes: Prioritize correctness/stability over early storage optimization UX.

* SRC-147:
  Type: Decision
  Priority: SHOULD
  Quote: "ollama, but open to others if they are more optimal for the 4 pillars"
  Notes: Default local LLM runtime choice.

* SRC-148:
  Type: Decision
  Priority: MUST
  Quote: "Should plugin installation ... fetch from the internet ... ? yes."
  Notes: Plugin manager must support online sources (explicit action + policy).

* SRC-149:
  Type: Constraint
  Priority: MUST
  Quote: "no, capture is guaranteed"
  Notes: Remove/avoid “panic pause capture” UX; only allow pausing processing.

* SRC-150:
  Type: Decision
  Priority: SHOULD
  Quote: "a standalone image file ... open to it changing if it is better"
  Notes: Default storage should remain standalone-per-frame unless overridden.

* SRC-151:
  Type: Requirement
  Priority: SHOULD
  Quote: "immutable freeze checkpoints ... transferred to a new machine"
  Notes: Daily freeze + migration viability.

* SRC-152:
  Type: Constraint
  Priority: MUST
  Quote: "never ever make shit up ... clearly state when you cannot cite"
  Notes: Answer policy and UI messaging.

Coverage_Map:

* SRC-001: 2/DOC-001, 2/DOC-002, 1/Implementation_Target
* SRC-002: 2/MOD-001, 2/MOD-003, 2/MOD-020
* SRC-003: 2/MOD-017, 3/ADR-001
* SRC-004: 3/ADR-002, 2/MOD-005, 2/MOD-011
* SRC-005: 3/ADR-003, 2/MOD-001
* SRC-006: 2/MOD-002, 2/MOD-014
* SRC-007: 2/MOD-003, 3/ADR-007
* SRC-008: 2/MOD-003, 3/ADR-007
* SRC-009: 2/MOD-011, 3/ADR-011
* SRC-010: 2/MOD-009, 2/MOD-014
* SRC-011: 2/MOD-012, 3/ADR-009
* SRC-012: 2/MOD-001
* SRC-013: 2/MOD-001
* SRC-014: 2/MOD-016
* SRC-015: 2/MOD-012
* SRC-016: 2/MOD-019, 3/ADR-002
* SRC-017: 2/MOD-005, 3/ADR-012
* SRC-018: 2/MOD-008, 3/ADR-006
* SRC-019: 2/MOD-004, 3/ADR-005
* SRC-020: 2/MOD-019, 3/ADR-002
* SRC-021: 2/MOD-001, 3/ADR-003
* SRC-022: 2/MOD-005, 3/ADR-008
* SRC-023: 2/MOD-001, 2/MOD-014
* SRC-024: 2/MOD-018, 3/ADR-012
* SRC-025: 2/MOD-006, 2/MOD-012
* SRC-026: 2/MOD-019
* SRC-027: 2/MOD-020, 2/MOD-014
* SRC-028: 2/MOD-020, 3/ADR-015
* SRC-029: 2/MOD-006, 3/ADR-006
* SRC-030: 2/MOD-001, 2/MOD-006
* SRC-031: 2/MOD-005, 3/ADR-004
* SRC-032: 2/MOD-014
* SRC-033: 2/MOD-016, 2/MOD-009
* SRC-034: 2/MOD-007
* SRC-035: 2/MOD-008
* SRC-036: 2/MOD-002, 2/MOD-016
* SRC-037: 2/MOD-011, 3/ADR-011
* SRC-038: 2/MOD-006
* SRC-039: 2/MOD-008, 3/ADR-006
* SRC-040: 2/MOD-008, 2/MOD-014
* SRC-041: 2/MOD-003
* SRC-042: 2/MOD-008
* SRC-043: 2/MOD-008, 2/MOD-016
* SRC-044: 2/MOD-009, 3/ADR-010
* SRC-045: 2/MOD-008, 2/MOD-009
* SRC-046: 2/MOD-016
* SRC-047: 2/MOD-010, 2/MOD-019
* SRC-048: 2/MOD-003
* SRC-049: 2/MOD-012, 2/MOD-014
* SRC-050: 2/MOD-012
* SRC-051: 2/MOD-012
* SRC-052: 2/MOD-012
* SRC-053: 2/MOD-012
* SRC-054: 2/MOD-013, 3/ADR-009
* SRC-055: 2/MOD-012, 2/MOD-014
* SRC-056: 2/MOD-015, 2/MOD-014
* SRC-057: 2/MOD-012
* SRC-058: 2/MOD-012
* SRC-059: 2/MOD-012
* SRC-060: 2/MOD-014
* SRC-061: 2/MOD-014
* SRC-062: 2/MOD-014
* SRC-063: 2/MOD-014, 2/MOD-009
* SRC-064: 2/MOD-014, 2/MOD-021
* SRC-065: 2/MOD-014, 2/MOD-015
* SRC-066: 2/MOD-014
* SRC-067: 2/MOD-014, 2/MOD-009
* SRC-068: 2/MOD-011, 2/MOD-014
* SRC-069: 2/MOD-015, 3/ADR-002
* SRC-070: 2/MOD-016
* SRC-071: 2/MOD-016
* SRC-072: 2/MOD-016
* SRC-073: 2/MOD-016, 2/MOD-008
* SRC-074: 2/MOD-014
* SRC-075: 2/MOD-016, 2/MOD-015
* SRC-076: 2/MOD-016
* SRC-077: 2/MOD-014
* SRC-078: 2/MOD-019
* SRC-079: 2/MOD-003, 2/MOD-016
* SRC-080: 2/MOD-017
* SRC-081: 2/MOD-017, 3/ADR-012
* SRC-082: 2/MOD-017, 2/MOD-014
* SRC-083: 2/MOD-007, 2/MOD-012, 2/MOD-011
* SRC-084: 2/MOD-011
* SRC-085: 2/MOD-012, 2/MOD-013
* SRC-086: 2/MOD-017
* SRC-087: 2/MOD-021
* SRC-088: 2/MOD-020, 2/MOD-017
* SRC-089: 2/MOD-011, 2/MOD-014
* SRC-090: 2/MOD-001, 2/MOD-005
* SRC-091: 2/MOD-003, 2/MOD-013
* SRC-092: 2/MOD-001
* SRC-093: 2/MOD-001, 2/MOD-005
* SRC-094: 2/MOD-006, 2/MOD-001
* SRC-095: 2/MOD-008, 2/MOD-003
* SRC-096: 2/MOD-010, 2/MOD-009
* SRC-097: 2/MOD-005
* SRC-098: 2/MOD-016, 2/MOD-021
* SRC-099: 2/MOD-003
* SRC-100: 2/MOD-021
* SRC-101: 2/MOD-021
* SRC-102: 2/MOD-021
* SRC-103: 2/MOD-021
* SRC-104: 2/MOD-021
* SRC-105: 2/MOD-021
* SRC-106: 2/MOD-021
* SRC-107: 2/MOD-021
* SRC-108: 2/MOD-021
* SRC-109: 2/MOD-021
* SRC-110: 2/DOC-002
* SRC-111: 2/DOC-002
* SRC-112: 2/DOC-002
* SRC-113: 2/DOC-002
* SRC-114: 2/MOD-008, 2/MOD-014
* SRC-115: 2/MOD-011
* SRC-116: 2/MOD-014
* SRC-117: 2/MOD-014
* SRC-118: 2/MOD-014
* SRC-119: 2/MOD-014
* SRC-120: 2/MOD-014
* SRC-121: 2/MOD-012
* SRC-122: 2/MOD-012
* SRC-123: 2/MOD-012
* SRC-124: 2/MOD-012
* SRC-125: 2/MOD-012
* SRC-126: 2/MOD-013
* SRC-127: 2/MOD-012
* SRC-128: 2/MOD-012
* SRC-129: 2/MOD-016
* SRC-130: 2/MOD-006
* SRC-131: 2/MOD-006
* SRC-132: 2/MOD-006
* SRC-133: 2/MOD-006, 2/MOD-008
* SRC-134: 2/MOD-014
* SRC-135: 2/MOD-014
* SRC-136: 2/MOD-014, 2/MOD-009
* SRC-137: 2/MOD-014
* SRC-138: 2/MOD-014
* SRC-139: 2/MOD-014
* SRC-140: 2/MOD-014
* SRC-141: 2/MOD-001
* SRC-142: 2/MOD-012, 2/MOD-001
* SRC-143: 3/ADR-003
* SRC-144: 2/MOD-001
* SRC-145: 2/MOD-001, 2/MOD-002
* SRC-146: 2/DOC-002
* SRC-147: 2/MOD-009
* SRC-148: 2/MOD-012
* SRC-149: 2/MOD-015, 3/ADR-003
* SRC-150: 3/ADR-008, 2/MOD-005
* SRC-151: 2/MOD-007, 2/MOD-018
* SRC-152: 2/MOD-009, 3/ADR-010

Validation_Checklist:

* Four top-level sections exist and are ordered: 1) Context, 2) Modules, 3) ADRs, 4) Samples.
* No “TODO/TBD/later/future work” language appears anywhere.
* Every [MISSING_VALUE] is only used where the source material does not provide the value.
* Every module entry includes: Object_ID, Object_Name, Object_Type, Priority, Primary_Purpose, Sources, Interface_Definition.
* Every ADR includes Sources.
* Coverage_Map includes every SRC-### exactly once.
* Every logic-heavy module listed in Section 2 has at least one 3-row sample table in Section 4.

# 2. Functional Modules & Logic

* Object_ID: MOD-001
  Object_Name: CaptureKernelService
  Object_Type: Other
  Priority: MUST
  Primary_Purpose: Capture raw screen images change-driven with strict dedupe-by-hash; store full-res encrypted media; honor HID-trigger and ≤0.5s active polling/check; emit journal + metrics.
  Sources: [SRC-002, SRC-004, SRC-005, SRC-006, SRC-012, SRC-013, SRC-021, SRC-030, SRC-090, SRC-092, SRC-093, SRC-141, SRC-144, SRC-145]
  Interface_Definition:

  ```text
  Types:
    CaptureTrigger := "screen_change" | "hid_input" | "manual" | "replay" | "startup_integrity" | "unknown"
    CaptureResult := {
      frame_id: string,
      captured_at_utc: string,                 # ISO-8601 UTC
      session_id: string,
      monitor_id: string,
      monitor_bounds: [int,int,int,int],
      app_name: string | null,
      window_title: string | null,
      capture_trigger: CaptureTrigger,
      change_reason: string,                   # e.g., "dirty_rect", "hid_forced", "fullscreen_unavailable"
      diff_stats: { changed_pixels: int, changed_ratio: float } | null,
      raw_pixels_hash: string,                 # e.g., "b3:<...>" per SRC-093
      encoded_bytes_hash: string,              # e.g., "sha256:<...>"
      codec: string,                           # e.g., "webp_lossless" or "avif_lossless"
      bytes: int,
      encryption: { enabled: bool, key_id: string },
      raw_media_path: string | null,           # null if unavailable marker
      unavailable: { reason: string, detail: string | null } | null
    }

  Public API:
    start_capture() -> void
    stop_capture() -> void
    get_capture_status() -> {
      state: "RUNNING" | "STOPPED" | "ERROR",
      mode_preset: string,                     # e.g., "memory_replacement_raw"
      last_capture_age_seconds_global: float,
      per_monitor_last_capture_age_seconds: map[monitor_id]float,
      queue_depths: { roi_queue_depth: int, pending_frames: int, max_pending: int },
      counters: map[string]int,                # includes captures_taken_total, captures_dropped_total, captures_skipped_*
      disk: { staging_free_mb: int, data_free_mb: int, hard_halt: bool, reason: string | null },
      resources: { process_cpu_percent: float, process_rss_mb: float, gpu_utilization: float | null },
      alerts: [{ alert_id: string, severity: "INFO"|"WARN"|"ERROR", message: string, created_at_utc: string }]
    }

    force_capture_now(trigger: CaptureTrigger, monitor_id?: string) -> CaptureResult | null
      - MUST dedupe by comparing raw_pixels_hash to last committed frame for (monitor_id, session_id) in strict mode.

  Config (must exist; reuse existing knobs where already present):
    mode_preset: "memory_replacement_raw" (default)
    diff_epsilon: 0 (per SRC-021)
    duplicate_threshold: "exact_only" (per SRC-021)
    always_store_fullres: true (per SRC-021)
    block_fullscreen: false (per SRC-021)
    active_hash_check_interval_ms: 500 (per SRC-145)
    encoder_preference: ["nvenc_webp_lossless","nvenc_avif_lossless","cpu_webp_lossless","cpu_png"] (per SRC-090)
    max_pending: existing config key (per SRC-012)
    disk_guards:
      staging_min_free_mb: existing config key (per SRC-012)
      data_min_free_mb: existing config key (per SRC-012)
      watermark_soft_mb: [MISSING_VALUE]        # new config, source does not specify value
      watermark_hard_mb: [MISSING_VALUE]        # new config, source does not specify value
  ```

* Object_ID: MOD-002
  Object_Name: HIDActivityMonitor
  Object_Type: Other
  Priority: MUST
  Primary_Purpose: Track HID activity, compute sessions/rollups, drive active/idle gating, and support “silent failure detector” signals.
  Sources: [SRC-006, SRC-036, SRC-075, SRC-145]
  Interface_Definition:

  ```text
  Types:
    HidEvent := { ts_utc: string, device: "mouse"|"keyboard"|"other", kind: string }
    HidSession := {
      session_id: string,
      started_at_utc: string,
      ended_at_utc: string | null,
      active_seconds: int,
      captures_taken: int,
      drops_by_reason: map[string]int
    }

  Public API:
    start() -> void
    stop() -> void
    get_activity_state() -> { state: "ACTIVE"|"IDLE", last_hid_at_utc: string, idle_for_seconds: float }

    get_current_session_id() -> string
    list_sessions(range_start_utc: string, range_end_utc: string) -> HidSession[]

  Events:
    on_hid_event(event: HidEvent) -> void
    on_state_change(new_state: "ACTIVE"|"IDLE") -> void

  Config:
    idle_threshold_seconds: [MISSING_VALUE]     # must use existing repo default if present; else add config
    session_gap_seconds: [MISSING_VALUE]        # gap threshold to split sessions; must use existing if present
  ```

* Object_ID: MOD-003
  Object_Name: ForegroundGovernor
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Enforce “user active ⇒ only capture runs” and “idle ⇒ GPU may saturate but CPU/RAM ≤50%”; apply Job Object caps; GPU preemption on activity; emit throttle events.
  Sources: [SRC-007, SRC-008, SRC-041, SRC-048, SRC-079, SRC-091, SRC-099]
  Interface_Definition:

  ```text
  Types:
    WorkerClass := "capture" | "processing" | "plugin_subprocess" | "ui" | "database" | "index" | "export"
    BudgetState := {
      user_state: "ACTIVE"|"IDLE",
      cpu_cap_percent: float,                  # 50% hard cap in IDLE; ACTIVE inherits or stricter
      ram_cap_percent: float,                  # 50% hard cap in IDLE; ACTIVE inherits or stricter
      gpu_allowed: bool,                       # true in IDLE; false or "minimal" in ACTIVE for processing
      enforcement: "job_object" | "soft" | "unknown"
    }
    ThrottleEvent := { ts_utc: string, kind: "CPU"|"RAM"|"GPU_PREEMPT", detail: string }

  Public API:
    attach_process_group(group_id: string, processes: int[]) -> void
    set_worker_class(group_id: string, worker_class: WorkerClass) -> void
    on_user_state_change(state: "ACTIVE"|"IDLE") -> void
    get_budget_state() -> BudgetState
    list_throttle_events(range_utc...) -> ThrottleEvent[]

  Rules:
    - If HIDActivityMonitor.state == ACTIVE:
        - processing worker concurrency MUST scale to 0
        - GPU allocations for processing MUST be released within [MISSING_VALUE] seconds (source gives no number)
    - If HIDActivityMonitor.state == IDLE:
        - allow GPU saturation for processing jobs
        - enforce cpu_cap_percent=50 and ram_cap_percent=50 for total app worker+plugin subprocess usage

  Metrics:
    throttle_events_total (new)
    budget_state (gauge)
  ```

* Object_ID: MOD-004
  Object_Name: CaptureJournalAndReconciler
  Object_Type: Data Store
  Priority: MUST
  Primary_Purpose: Append-only capture journal + reconciler ensuring crash-safe persistence from staging to committed with no silent loss.
  Sources: [SRC-019, SRC-026]
  Interface_Definition:

  ```text
  JournalEntry := {
    journal_seq: int,
    ts_utc: string,
    kind: "CAPTURE_STARTED"|"MEDIA_STAGED"|"DB_ROW_WRITTEN"|"COMMITTED"|"FAILED"|"UNAVAILABLE",
    frame_id: string,
    raw_pixels_hash: string | null,
    encoded_bytes_hash: string | null,
    staging_path: string | null,
    committed_path: string | null,
    error: string | null
  }

  Public API:
    append(entry: JournalEntry) -> void
    replay_and_reconcile(on_startup: bool) -> {
      replayed: int,
      orphaned_staging_found: int,
      repaired: int,
      marked_failed: int
    }

  Reconcile Rules:
    - Any MEDIA_STAGED without COMMITTED after crash MUST be reconciled:
        - if staging exists and DB row missing -> write DB row then commit
        - if DB row exists but committed missing -> retry commit or mark as broken evidence
    - Journal MUST be append-only (no in-place edits); reconciliation outcomes appended as new entries.
  ```

* Object_ID: MOD-005
  Object_Name: MediaStoreV2
  Object_Type: Data Store
  Priority: MUST
  Primary_Purpose: Store encrypted raw media in staging→committed form; support both standalone-per-frame files (default) and optional segment store for scaling; verify hashes; provide random access.
  Sources: [SRC-004, SRC-017, SRC-022, SRC-031, SRC-090, SRC-097, SRC-150]
  Interface_Definition:

  ```text
  StorageMode := "standalone_files" | "segment_store"
  StoreMediaRequest := {
    frame_id: string,
    encoded_bytes: bytes,
    raw_pixels_hash: string,
    encoded_bytes_hash: string,
    codec: string,
    encryption_key_id: string
  }
  StoreMediaResult := {
    committed_path: string,
    bytes: int,
    codec: string,
    encoded_bytes_hash: string
  }

  Public API:
    store_media(req: StoreMediaRequest) -> StoreMediaResult
    read_media(frame_id: string, variant?: "raw"|"preview") -> bytes
    verify_media(frame_id: string) -> { ok: bool, mismatches: string[] }

  Storage Rules:
    - Default mode MUST be standalone per-frame media files (per SRC-150).
    - Segment store MUST be implemented and selectable by config (per SRC-022).
    - Paths MUST be sharded (hash-prefix) if using standalone mode (per SRC-097).
    - Both modes MUST preserve exact reconstruction of encoded bytes for citeable preview, and MUST store raw_pixels_hash separately.

  Encoder Ladder:
    - Prefer GPU encoders `nvenc_webp`/`nvenc_avif` lossless; fall back to CPU encoders with explicit warning when fallback occurs. (per SRC-090)
  ```

* Object_ID: MOD-006
  Object_Name: CanonicalMetadataSchemaAndDBConstraints
  Object_Type: Data Model
  Priority: MUST
  Primary_Purpose: Provide Frame v2 as single source of truth; store dual hashes; standardize artifact/job metadata; enforce FK/NOT NULL constraints; persist config snapshots and plugin versions per session.
  Sources: [SRC-025, SRC-029, SRC-030, SRC-031, SRC-035, SRC-038, SRC-130, SRC-131, SRC-132, SRC-133]
  Interface_Definition:

  ```text
  Canonical Entities (logical schema; implement in existing DB technology):
    FrameV2:
      frame_id: string (PK)
      captured_at_utc: string (NOT NULL)
      monotonic_ts: float (NOT NULL)
      session_id: string (NOT NULL)
      capture_trigger: string (NOT NULL)
      change_reason: string (NOT NULL)
      diff_changed_pixels: int | null
      diff_changed_ratio: float | null
      monitor_id: string (NOT NULL)
      monitor_bounds: [int,int,int,int] (NOT NULL)
      app_name: string | null
      window_title: string | null
      raw_media_path: string | null
      raw_pixels_hash: string | null (NOT NULL if raw_media_path != null)
      encoded_bytes_hash: string | null (NOT NULL if raw_media_path != null)
      codec: string | null
      bytes: int | null
      encryption_enabled: bool (NOT NULL)
      encryption_key_id: string | null
      unavailable_reason: string | null
      schema_version: int (NOT NULL, default=2)

    Artifact:
      artifact_id: string (PK)
      frame_id: string (FK -> FrameV2.frame_id, NOT NULL)
      artifact_type: string (NOT NULL)                # e.g., "ocr_spans", "embeddings", "summary"
      engine: string (NOT NULL)
      engine_version: string (NOT NULL)
      job_id: string (FK -> JobRun.job_id, NOT NULL)
      input_hash: string (NOT NULL)                   # at least raw_pixels_hash or frame_hash equivalent
      dedupe_key: string (UNIQUE, NOT NULL)           # (type, engine_version, input_hash)
      status: "pending"|"running"|"done"|"failed" (NOT NULL)
      attempts: int (NOT NULL)
      last_error: string | null
      timings_ms: json | null
      derived_from: json (NOT NULL)                   # must include hashes (per SRC-133)

    CitableSpan:
      span_id: string (PK)
      artifact_id: string (FK -> Artifact.artifact_id, NOT NULL)
      frame_id: string (FK -> FrameV2.frame_id, NOT NULL)
      text: string (NOT NULL)
      bbox_norm: [float,float,float,float] (NOT NULL)
      span_hash: string (NOT NULL)
      created_at_utc: string (NOT NULL)

    JobRun:
      job_id: string (PK)
      job_type: string (NOT NULL)                     # "ocr"|"embed"|"summary"|"reindex"|"export"...
      created_at_utc: string (NOT NULL)
      started_at_utc: string | null
      ended_at_utc: string | null
      status: "pending"|"running"|"done"|"failed"|"stalled" (NOT NULL)
      engine: string | null
      engine_version: string | null
      inputs: json (NOT NULL)                         # list of frame_id(s) + hashes
      outputs: json (NOT NULL)                        # artifact ids
      last_error: string | null

    ConfigSnapshot:
      session_id: string (PK)
      captured_at_utc: string (NOT NULL)
      config_json: json (NOT NULL)
      config_hash: string (NOT NULL)

    SessionPluginVersions:
      session_id: string (NOT NULL)
      plugin_id: string (NOT NULL)
      plugin_version: string (NOT NULL)
      plugin_code_sha256: string (NOT NULL)
      PRIMARY KEY (session_id, plugin_id)
  ```

* Object_ID: MOD-007
  Object_Name: ProvenanceLedgerAndDailyFreeze
  Object_Type: Data Store
  Priority: MUST
  Primary_Purpose: Maintain append-only provenance ledger with chain hashes; persist/show/export ledger head; create per-day immutable freeze checkpoints; provide verifier; log privileged actions.
  Sources: [SRC-034, SRC-083, SRC-151]
  Interface_Definition:

  ```text
  LedgerEntry := {
    entry_id: string,
    ts_utc: string,
    kind: "FRAME_COMMITTED"|"ARTIFACT_DONE"|"PLUGIN_CHANGE"|"CONFIG_SNAPSHOT"|"EXPORT_CREATED"|"UNLOCK"|"LOCK"|"DAILY_FREEZE",
    subject_id: string,                       # frame_id, artifact_id, plugin_id, export_id, etc.
    payload_hash: string,                      # hash of canonical payload
    prev_entry_hash: string | null,
    entry_hash: string                         # hash(prev_entry_hash + payload_hash + ts + kind)
  }

  AuditEvent := {
    audit_id: string,
    ts_utc: string,
    actor: "user"|"system",
    action: "unlock"|"lock"|"export"|"plugin_install"|"plugin_enable"|"plugin_disable"|"plugin_update"|"rollback"|"config_change",
    detail: json
  }

  Public API:
    append_ledger(entry: LedgerEntry) -> void
    get_ledger_head() -> { entry_hash: string, entry_id: string }
    verify_ledger_chain(range?: ...) -> { ok: bool, first_bad_entry_id: string | null }

    run_daily_freeze(day_utc: string) -> { freeze_entry_id: string, ledger_head_hash: string }
      - MUST be deterministic and idempotent for the same day_utc.

    record_audit(event: AuditEvent) -> void
  ```

* Object_ID: MOD-008
  Object_Name: JobSystemWorkersReplayAndWatchdog
  Object_Type: Background Worker
  Priority: MUST
  Primary_Purpose: Idempotent processing (OCR/embeddings/summaries/digest), JobRun DAG, deterministic replay engine, watchdog+heartbeats+retries, debug bundle export, idle-only scheduling, consistency sweeps.
  Sources: [SRC-007, SRC-039, SRC-040, SRC-042, SRC-043, SRC-045, SRC-046, SRC-047, SRC-048, SRC-095, SRC-114, SRC-133]
  Interface_Definition:

  ```text
  Public API:
    enqueue_job(job_type: string, inputs: json, priority?: int) -> job_id
    get_job(job_id: string) -> JobRun
    list_jobs(filter: json) -> JobRun[]

    replay(job_type: string, range_utc: {start,end} | frame_ids: string[]) -> { replay_job_id: string, diff_report_id: string }
      - MUST record diffs between prior artifacts and replay artifacts (per SRC-042).

    watchdog_tick() -> void
      - If job stalled beyond [MISSING_VALUE] seconds, mark stalled, retry per policy.

    export_job_debug_bundle(job_id: string) -> { bundle_id: string, path: string }
      - Bundle MUST include: inputs, hashes, versions, logs (per SRC-046) and exclude raw media by default (per SRC-072).

  Worker Rules:
    - All workers MUST be idempotent using dedupe_key=(type, engine_version, input_hash).
    - All non-capture workers MUST pause to 0 concurrency during ACTIVE user state.
    - Idle-only sweeps:
        - DB↔index consistency sweep with repair (per SRC-047)
        - orphan cleanup (per SRC-078)
  ```

* Object_ID: MOD-009
  Object_Name: AnswerEngineWithCitationsAndRetrievalTrace
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Serve Q&A with citations required; conservative “I don’t know yet” when uncitable; show retrieval trace; generate “What happened today” digest with evidence-backed summaries as artifacts.
  Sources: [SRC-010, SRC-044, SRC-063, SRC-096, SRC-114, SRC-152, SRC-134, SRC-136, SRC-147]
  Interface_Definition:

  ```text
  AnswerRequest := {
    query: string,
    time_range_utc?: { start: string, end: string },
    filters?: { app_name?: string, monitor_id?: string },
    policy: { citations_required: true, conservative: true }
  }

  Citation := { span_id: string, frame_id: string, artifact_id: string, text_preview: string, bbox_norm: [float,float,float,float] }

  AnswerResponse := {
    answer_id: string,
    answer_text: string,
    citations: Citation[],                      # MUST be non-empty if citations_required
    proof: {
      captured: { ok: bool, frame_ids: string[] },
      ocr: { ok: bool, artifact_ids: string[], job_ids: string[] },
      embed: { ok: bool, artifact_ids: string[], job_ids: string[] },
      summary: { ok: bool, artifact_ids: string[], job_ids: string[] }
    },
    retrieval_trace: {
      job_id: string,
      strategy: "lexical_first"|"vector"|"hybrid",
      inputs: json,
      top_spans: Citation[]
    },
    trust_level: "GREEN"|"YELLOW"|"RED",
    missing_evidence: { frames_missing: string[], spans_missing: string[] }
  }

  Public API:
    answer(req: AnswerRequest) -> AnswerResponse
      - MUST fail/soft-fail if citations_required=true and no citations found (per SRC-044, SRC-152).
      - MUST surface missing evidence explicitly (per SRC-136).

    daily_digest(day_local?: string) -> AnswerResponse
      - MUST be backed by Summary artifacts with input list + model hash (per SRC-045, SRC-114).
  ```

* Object_ID: MOD-010
  Object_Name: RetrievalIndexLexicalAndVectorSidecar
  Object_Type: Data Store
  Priority: MUST
  Primary_Purpose: Provide responsive retrieval under foreground gating via lexical-first fallback, with optional vector sidecar running localhost; include consistency sweeps and minimal payload retrieval.
  Sources: [SRC-096, SRC-047, SRC-003]
  Interface_Definition:

  ```text
  Public API:
    index_ocr_spans(frame_id: string, spans: CitableSpan[]) -> void
    index_embeddings(frame_id: string, vectors: bytes, meta: json) -> void
    lexical_search(query: string, filters?: json, limit?: int) -> Citation[]
    vector_search(query_vector: bytes, filters?: json, limit?: int) -> Citation[]
    hybrid_search(query: string, filters?: json, limit?: int) -> Citation[]

    consistency_sweep(range?: ...) -> { repaired: int, missing: int }
      - MUST run idle-only (per SRC-047).
  ```

* Object_ID: MOD-011
  Object_Name: ExportSanitizationPipeline
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Create sanitized export bundles only on explicit user action; entity hashing map (salted, rotatable); preview+warnings; audit entry; never mutate local raw.
  Sources: [SRC-009, SRC-037, SRC-068, SRC-084, SRC-089, SRC-115]
  Interface_Definition:

  ```text
  EntityMap := {
    salt_id: string,
    created_at_utc: string,
    mapping: map[string] { hashed: string, type: string }   # stored locally only, encrypted
  }

  ExportRequest := {
    range_utc: { start: string, end: string },
    include: { frames: bool, ocr: bool, summaries: bool, embeddings: bool },
    sanitize: { enabled: true, mode: "entity_hashing", salt_rotation: "manual"|"scheduled" },
    preview_only: bool
  }

  ExportResult := {
    export_id: string,
    created_at_utc: string,
    bundle_path: string,
    manifest: json,
    ledger_head_hash: string,
    entity_hash_dictionary_included: bool,        # MUST be false in exported bundle
    warnings: string[]
  }

  Public API:
    export_preview(req: ExportRequest) -> { warnings: string[], redaction_summary: json }
    export_create(req: ExportRequest) -> ExportResult
      - MUST write an audit event (per SRC-083).
      - MUST include ledger head pointer (per SRC-034).
      - MUST NOT include raw media by default; sanitized artifacts only (per SRC-084).

    reveal_entity_hashes_locally(after_unlock: bool) -> EntityMap
      - UI feature (per SRC-089).
  ```

* Object_ID: MOD-012
  Object_Name: PluginManagerCore
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Plugin discovery/install/update/rollback with atomic staging, compatibility gating, two-phase enable, permission UX, health dashboard, logs/traces, conflict resolution, doctor flow, optional signing.
  Sources: [SRC-011, SRC-015, SRC-049, SRC-050, SRC-051, SRC-052, SRC-053, SRC-055, SRC-057, SRC-058, SRC-059, SRC-121, SRC-122, SRC-123, SRC-124, SRC-125, SRC-148]
  Interface_Definition:

  ```text
  PluginId := string
  PluginManifest := {
    plugin_id: PluginId,
    version: string,
    entrypoint: string,
    compatibility: {
      app_version_range: string,
      schema_version_range: string,
      os: string,
      python: string | null,
      gpu_required: bool | null
    },
    permissions_requested: string[],              # e.g., "network", "filesystem", "shell", "openai"
    provides: string[],                           # extension points
    overrides: string[],                          # overridden extension points
    priority: int                                 # used for conflict resolution
  }

  InstalledPlugin := {
    plugin_id: PluginId,
    version: string,
    enabled: bool,
    trust_level: "untrusted"|"trusted"|"signed",
    manifest_sha256: string,
    code_sha256: string,
    permissions_granted: string[],
    last_health: { status: "HEALTHY"|"UNHEALTHY", checked_at_utc: string, last_error: string | null }
  }

  Public API:
    discover_sources() -> { builtin: InstalledPlugin[], directory: InstalledPlugin[], entrypoints: InstalledPlugin[] }
    install(source: "folder"|"zip"|"wheel"|"pip"|"git", locator: string) -> { staged: bool, plugin_id: PluginId, version: string }
      - MUST: validate manifest; compute hashes; show diff vs current; stage; activate (per SRC-121).
      - MUST: support internet sources pip/git as explicit user action (per SRC-148).

    enable(plugin_id: PluginId) -> { ok: bool, reason: string | null }
      - MUST: permission prompt -> sandbox load -> health check -> enable (per SRC-122).

    disable(plugin_id: PluginId) -> void
    update(plugin_id: PluginId, target_version?: string) -> { ok: bool, rollback_point_id: string }
    rollback(plugin_id: PluginId, rollback_point_id: string) -> { ok: bool }
    list_rollback_points(plugin_id: PluginId) -> { rollback_point_id: string, version: string, created_at_utc: string }[]

    resolve_conflicts() -> { conflicts: [{ extension: string, plugins: PluginId[] }], resolution_required: bool }
      - MUST: block enable if unresolved conflicts (per SRC-059).

    doctor() -> { report: json }                   # UI wrapper around existing command (per SRC-125)

    get_plugin_logs(plugin_id: PluginId, tail: int) -> string[]
  ```

* Object_ID: MOD-013
  Object_Name: PluginSandboxAndPolicyGate
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Enforce PolicyGate deny-by-default permissions, run untrusted plugins out-of-process with IPC, and apply JobObject resource caps; record denials and health.
  Sources: [SRC-053, SRC-054, SRC-085, SRC-091, SRC-014, SRC-126]
  Interface_Definition:

  ```text
  PolicyPermission := "network"|"filesystem"|"shell"|"openai"|"unknown"

  PolicyDecision := { allowed: bool, reason: string, permission: PolicyPermission, plugin_id: string }

  SandboxConfig := {
    mode: "in_process"|"out_of_process",
    job_object_caps: { cpu_percent: float, ram_percent: float },    # must enforce per SRC-091
    ipc: { transport: "stdio"|"named_pipe"|"[MISSING_VALUE]" }
  }

  Public API:
    evaluate(plugin_id: string, permission: PolicyPermission, context: json) -> PolicyDecision
    run_plugin(plugin_id: string, sandbox: SandboxConfig) -> { handle_id: string }
    stop_plugin(handle_id: string) -> void
    get_denials(plugin_id: string, range_utc...) -> PolicyDecision[]
  ```

* Object_ID: MOD-014
  Object_Name: WebUIV2
  Object_Type: Other
  Priority: MUST
  Primary_Purpose: Q&A-first Home (Today + Omnibox), session-grouped timeline with gaps, item detail view with metadata/provenance/status, explain-answer panel with retrieval trace, accessibility modes, capture status panel everywhere, plugin manager IA, export review, runbook, safe mode wizard.
  Sources: [SRC-060, SRC-061, SRC-062, SRC-063, SRC-064, SRC-065, SRC-066, SRC-067, SRC-068, SRC-074, SRC-077, SRC-082, SRC-116, SRC-117, SRC-118, SRC-119, SRC-120, SRC-134, SRC-135, SRC-137, SRC-138, SRC-139, SRC-140]
  Interface_Definition:

  ```text
  UI Pages/Tabs (must exist):
    - HomeToday:
        - Omnibox Q&A input
        - Suggested queries: ["What happened today", "Last 15m", "Last 1h", ...]
        - Answer view: citations + proof chips + explain panel
        - Capture/Processing status banner visible at top
    - Timeline:
        - Grouped by HID sessions + app focus
        - Gap markers with reasons (disk checks, fullscreen unavailable, backpressure, etc.)
    - FrameDetail:
        - Raw media preview
        - Core metadata at top: timestamps, hashes, monitor/app/window, trigger, trust
        - Processing section: OCR/Embed/Summary status with job_id + engine versions
    - Plugins:
        - Installed / Catalog / Updates / Permissions / Health
        - Conflict resolution UI (priority graph)
        - Doctor view (embedded)
    - Export:
        - Sanitized-only export preview + warnings
        - Entity hash dictionary view (local-only after unlock)
    - Help/Runbook:
        - Localhost-only, restore, safe mode steps
    - SafeModeWizard:
        - Enter/exit safe mode; re-enable plugins one-by-one

  Session/Unlock UX:
    - MUST not include unlock token in URL params (per SRC-082).
    - MUST use short TTL in-memory session for protected endpoints (unlock required).
  ```

* Object_ID: MOD-015
  Object_Name: TrayCompanionV2
  Object_Type: Other
  Priority: MUST
  Primary_Purpose: Always-visible capture status, alerts, safe mode entry, processing pause toggles; MUST NOT offer capture pause or deletion actions.
  Sources: [SRC-065, SRC-069, SRC-075, SRC-149, SRC-027, SRC-056]
  Interface_Definition:

  ```text
  Tray Menu (required):
    - Status (read-only):
        - Capture: RUNNING (no pause control)
        - Processing: RUNNING/PAUSED (toggle allowed)
        - Last capture age
        - Disk: OK / CAPTURE HALTED: DISK LOW
    - Actions:
        - Pause Processing / Resume Processing
        - Enter Safe Mode / Exit Safe Mode
        - Open UI
        - Export Diagnostics Bundle
    - MUST NOT include:
        - Pause Capture
        - Delete range / Delete all / any deletion action
  ```

* Object_ID: MOD-016
  Object_Name: ObservabilityMetricsSLOsDiagnostics
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Extend metrics (latency, queue p95), correlation IDs, SLO dashboard, error budgets, pipeline state machine, silent failure alerts, diagnostics bundles (no raw media by default).
  Sources: [SRC-014, SRC-070, SRC-071, SRC-072, SRC-073, SRC-074, SRC-075, SRC-076, SRC-129]
  Interface_Definition:

  ```text
  Required Metrics (existing + new):
    Existing (must reuse if present): captures_taken_total, captures_dropped_total, captures_skipped_*, process_cpu_percent, process_rss_mb, gpu_* gauges
    New:
      - screen_change_detect_ms (histogram)
      - persist_commit_ms (histogram)
      - roi_queue_depth (gauge, already exists per SRC-013)
      - pending_frames (gauge)
      - throttle_events_total (counter)
      - last_capture_age_seconds (gauge, per monitor + global)
      - capture_gap_seconds (aggregate)
      - queue_depth_p95 (computed for UI)
      - error_budget_drop_rate (computed)
      - error_budget_pipeline_lag (computed)

  Correlation IDs:
    - Every log line for capture/processing/plugin MUST include: frame_id and/or job_id and/or plugin_id (per SRC-073).

  Diagnostics Bundle:
    generate_diagnostics_bundle(include_raw_media: bool=false) -> { bundle_id: string, path: string }
      - MUST include config snapshot, plugin list, logs, DB integrity results
      - MUST exclude raw media by default (per SRC-072)
  ```

* Object_ID: MOD-017
  Object_Name: LocalSecurityAndSessionProtection
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Loopback-only enforcement + firewall rule, CSP/CSRF, session unlock (not URL token), secrets scanning hooks, vendor binary SHA verification, encryption unlock/auto-lock.
  Sources: [SRC-003, SRC-080, SRC-081, SRC-082, SRC-086, SRC-087, SRC-088]
  Interface_Definition:

  ```text
  Network Guard:
    enforce_loopback_only(bind_host: string, bind_port: int) -> void
      - MUST fail closed if bind_host != "127.0.0.1" (per SRC-080)

  Web Security:
    set_csp_headers() -> void
    enable_csrf_protection() -> void

  Session Lock/Unlock:
    unlock(method: "windows_hello") -> { session_id: string, expires_at_utc: string }
    lock() -> void
    is_unlocked() -> bool
    - MUST NOT place tokens in URLs (per SRC-082)

  Vendor SHA Verification:
    verify_vendor_binaries(manifest: { path: string, sha256: string }[]) -> { ok: bool, failed: string[] }
      - MUST fail closed if mismatch (per SRC-088)
  ```

* Object_ID: MOD-018
  Object_Name: BackupRestoreAndMigration
  Object_Type: Other
  Priority: MUST
  Primary_Purpose: Encrypted local backup + restore workflow (external drive) and migration to new machine while preserving hashes/citations/ledger continuity.
  Sources: [SRC-024, SRC-151, SRC-112]
  Interface_Definition:

  ```text
  BackupRequest := { destination_path: string, include_media: bool=true, include_db: bool=true, include_ledger: bool=true }
  BackupResult := { backup_id: string, created_at_utc: string, manifest: json, path: string }

  RestoreRequest := { backup_path: string, destination_root: string }
  RestoreResult := { ok: bool, repaired: int, missing: int, ledger_ok: bool }

  Public API:
    backup_create(req: BackupRequest) -> BackupResult
    restore(req: RestoreRequest) -> RestoreResult
    verify_backup(backup_path: string) -> { ok: bool, issues: string[] }
  ```

* Object_ID: MOD-019
  Object_Name: NoDeletionModeAndIntegritySweeps
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Enforce no deletion (remove endpoints, disable retention pruning), run startup integrity sweep, mark broken evidence, and ensure answers referencing missing evidence are “stale”.
  Sources: [SRC-020, SRC-026, SRC-016, SRC-136]
  Interface_Definition:

  ```text
  Public API:
    assert_no_delete_routes_present() -> { ok: bool, found_routes: string[] }     # must be used in tests
    startup_integrity_sweep() -> { frames_checked: int, missing_media: int, hash_mismatches: int }
    mark_stale_answers_for_missing_evidence(frame_ids: string[]) -> int

  Behavior:
    - Delete endpoints MUST be absent: /api/delete_range, /api/delete_all (per SRC-016, SRC-020).
    - Retention worker MUST never unlink files in no-deletion mode.
  ```

* Object_ID: MOD-020
  Object_Name: WindowsServiceSupervisorAndSafeMode
  Object_Type: Other
  Priority: MUST
  Primary_Purpose: Split kernel into Windows Service (capture+DB) and user-space UI/processing; crash-loop detection safe mode; service resumes capture after reboot; safe mode capture-only + diagnostics prompt.
  Sources: [SRC-028, SRC-027, SRC-056, SRC-080]
  Interface_Definition:

  ```text
  Components:
    - KernelService (Windows Service):
        - Runs CaptureKernelService + DB write path + CaptureJournal
    - UserAgent (User-space):
        - Runs WebUI, processing workers, plugin UI, tray
    - Supervisor:
        - Monitors restarts; if restarts > N within window -> enter safe mode

  Safe Mode:
    - Only capture pipeline runs (capture+DB+journal)
    - Third-party plugins disabled
    - UI shows reason and provides diagnostics export
    - N, window_seconds are config values: [MISSING_VALUE] (source does not provide)

  Firewall:
    - Install firewall rule restricting bind to loopback (per SRC-080).
  ```

* Object_ID: MOD-021
  Object_Name: TestHarnessAndQA
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Golden dataset, chaos tests, migration tests, e2e Q&A tests, fuzz plugin manifests, resource budget tests, Windows integration tests, localhost-only security tests, provenance tamper tests, accessibility tests.
  Sources: [SRC-100, SRC-101, SRC-102, SRC-103, SRC-104, SRC-105, SRC-106, SRC-107, SRC-108, SRC-109, SRC-087]
  Interface_Definition:

  ```text
  Test Suites (must exist in CI):
    - golden_e2e_memory_replacement:
        - capture->ocr->embedding->answer with citations
    - chaos_capture_persist:
        - crash during persist, disk full, DB locked, encoder fail
    - migrations_ledger_citations:
        - upgrade across versions; ledger continuity; citations resolvable
    - e2e_today_qa:
        - ask "What happened today" and verify citations resolve to media/spans
    - fuzz_plugin_manifests:
        - malformed manifests never crash; errors surfaced
    - resource_budget_enforcement:
        - CPU/RAM caps respected; alerts fire on attempted breach
    - windows_capture_integration:
        - DirectX capture + RawInputListener on Win11 runner
    - localhost_security_regressions:
        - bind loopback only; offline guard; CSP/CSRF headers present
    - provenance_tamper_detection:
        - modify ledger; verifier detects break
    - accessibility_suite:
        - keyboard nav, focus order, contrast
  ```

* Object_ID: DOC-001
  Object_Name: AGENTS.md
  Object_Type: Other
  Priority: MUST
  Primary_Purpose: Provide deterministic implementation guardrails and workflow for Codex CLI and other agents, aligned to constraints (no deletion, localhost-only, citations required, foreground gating, resource caps).
  Sources: [SRC-001, SRC-003, SRC-004, SRC-007, SRC-008, SRC-044, SRC-085, SRC-149, SRC-152]
  Interface_Definition:

  ```text
  File: AGENTS.md
  Required Contents (verbatim template to create):
    # Agents Operating Manual

    ## Mission
    - Implement ALL requirements in BLUEPRINT.md with no omissions.
    - Optimize for: Performance, Accuracy, Security, Citeability.

    ## Non-Negotiables
    - Localhost-only: never bind beyond 127.0.0.1; fail closed.
    - No local deletion: no delete endpoints; no retention pruning; archive/migrate only.
    - Raw-first local store: no masking/filtering locally; sanitization only on explicit export.
    - Foreground gating: when user is ACTIVE, only capture+kernel runs; pause all other processing.
    - Idle budgets: CPU <= 50% and RAM <= 50% (enforced), GPU may saturate.
    - Answers: citations required by default; never fabricate; clearly say when uncitable/indeterminate.
    - Tray: MUST NOT provide capture pause or deletion actions (processing pause OK).

    ## Implementation Protocol
    - For each SRC requirement: reference where it is implemented (module/ADR/test).
    - Add/extend tests for every behavior change; prefer deterministic tests.
    - Any new privileged behavior must be audited (append-only audit log).
    - Treat plugin code and external inputs as untrusted; enforce PolicyGate and sandbox.

    ## Definition of Done
    - All test suites in MOD-021 pass.
    - Coverage_Map is satisfied: every SRC implemented and verifiable.
    - Manual smoke: capture running; Q&A returns citations; export is sanitized; no delete routes exist.
  ```

* Object_ID: DOC-002
  Object_Name: SPEC.md
  Object_Type: Other
  Priority: MUST
  Primary_Purpose: Implementation spec that “goes hand in hand” with the attached md; provides phased implementation order and acceptance criteria checklist for Codex CLI.
  Sources: [SRC-001, SRC-110, SRC-111, SRC-112, SRC-113, SRC-146]
  Interface_Definition:

  ```text
  File: SPEC.md
  Required Contents (verbatim template to create):
    # Implementation Spec (Phased)

    ## Principle
    Implement 100% of the recommendations and constraints. Phasing is ordering only, not scope reduction.

    ## Phase 0 (Stabilize & Make Status Obvious)
    - No-deletion mode (remove delete endpoints, disable retention pruning)
    - Memory Replacement (Raw) capture preset
    - Capture health/status UI + tray parity
    - Foreground gating: processing pauses when user active

    ## Phase 1 (Provable Processing)
    - JobRun model + DAG UI
    - Proof chips per answer (job_id + hashes)
    - Citations-required answers default

    ## Phase 2 (Retention & Migration)
    - Segment store option + sharded standalone files
    - Encrypted backup + restore workflow
    - Archive/migrate flows (no deletion)

    ## Phase 3 (Plugin Hardening)
    - Atomic install/update/rollback
    - Two-phase enable + sandboxing
    - Permission UX + PolicyGate tightening

    ## Completion Checklist
    - Localhost-only enforced (bind + firewall)
    - CPU/RAM caps enforced with Job Objects
    - Startup integrity sweep implemented
    - Daily freeze checkpoints implemented
    - Export is sanitized-only and does not mutate local raw
    - Golden + chaos + migration + e2e tests pass
  ```

# 3. Architecture Decision Records (ADRs)

* ADR_ID: ADR-001
  Title: Enforce loopback-only runtime binding
  Status: Accepted
  Context: UI/API must never be exposed beyond 127.0.0.1, and misconfig could bind to LAN.
  Decision: Enforce bind_host == 127.0.0.1 at runtime; fail closed otherwise; install firewall rule to block non-loopback access.
  Consequences:

  * Prevents accidental LAN exposure.
  * Requires installer/service to apply firewall rule.
    Sources: [SRC-003, SRC-080]

* ADR_ID: ADR-002
  Title: No-Deletion Mode as default behavior
  Status: Accepted
  Context: Raw-first indefinite retention prohibits local deletion and conflicts with existing delete endpoints and retention pruning.
  Decision: Remove/disable `/api/delete_range` and `/api/delete_all` endpoints and any pruning/unlink code paths; replace with archive/migrate workflows only.
  Consequences:

  * Users cannot delete locally; must rely on encryption and export sanitization.
  * Requires route tests and grep checks to prevent reintroduction.
    Sources: [SRC-004, SRC-016, SRC-020]

* ADR_ID: ADR-003
  Title: Memory Replacement (Raw) capture semantics
  Status: Accepted
  Context: Must capture any visible change and trigger capture on HID input; no app-based pauses; best-effort fullscreen capture with explicit unavailability.
  Decision:

  * Default preset: diff_epsilon=0, exact-only dedupe, always_store_fullres=true, block_fullscreen=false.
  * Trigger capture checks on HID input and ensure ≤500ms active check interval.
  * Record “unavailable” markers for DRM/fullscreen capture failures.
    Consequences:
  * Higher capture volume; requires disk guards and performance optimizations.
  * Dedupe relies on raw_pixels_hash.
    Sources: [SRC-021, SRC-005, SRC-143, SRC-144, SRC-145, SRC-149]

* ADR_ID: ADR-004
  Title: Dual-hash capture proof (raw pixels + encoded bytes)
  Status: Accepted
  Context: Need pixel-level uniqueness proof while storing encoded media efficiently.
  Decision: Store raw_pixels_hash (BLAKE3) pre-encode and encoded_bytes_hash (SHA256) post-encode for every stored frame; expose in UI and use for integrity checks.
  Consequences:

  * Adds hashing cost; must parallelize.
  * Enables robust corruption detection and dedupe correctness.
    Sources: [SRC-031, SRC-093]

* ADR_ID: ADR-005
  Title: Append-only Capture Journal with reconciler
  Status: Accepted
  Context: Must be crash-safe and provable that capture occurred even if DB write fails mid-flight.
  Decision: Implement an append-only journal that records staging, DB write, and commit; on startup reconcile orphaned staging and mark broken evidence explicitly.
  Consequences:

  * Requires new storage file and recovery logic.
  * Enables deterministic recovery and audit trail.
    Sources: [SRC-019, SRC-026]

* ADR_ID: ADR-006
  Title: Canonical Frame v2 + JobRun + idempotent artifacts
  Status: Accepted
  Context: Need single source of truth for captured frames and provable processing lineage.
  Decision:

  * Migrate to Frame v2 canonical schema.
  * Introduce JobRun model for all processing.
  * Enforce artifact idempotency via dedupe_key=(type, engine_version, input_hash).
    Consequences:
  * DB migrations required.
  * UI and workers must use Frame v2.
    Sources: [SRC-029, SRC-040, SRC-039, SRC-133]

* ADR_ID: ADR-007
  Title: Foreground gating and hard resource caps
  Status: Accepted
  Context: Non-negotiable: only capture pipeline runs while user active; in idle CPU/RAM must never exceed 50%, GPU can saturate.
  Decision:

  * Implement ForegroundGovernor that pauses non-capture workers when ACTIVE.
  * Enforce CPU/RAM caps using Windows Job Objects for worker and plugin subprocesses.
  * Preempt GPU allocations on HID input.
    Consequences:
  * Requires process grouping and cap enforcement.
  * Prevents background processing from harming foreground UX.
    Sources: [SRC-007, SRC-008, SRC-091, SRC-099, SRC-048]

* ADR_ID: ADR-008
  Title: Media storage supports both standalone files and segment store
  Status: Accepted
  Context: User prefers standalone per-frame files, but indefinite retention scaling requires segment store option.
  Decision:

  * Default storage mode: standalone-per-frame files (sharded by hash prefix).
  * Implement segment store as selectable backend for scaling.
    Consequences:
  * Two code paths; must share verification and retrieval interfaces.
  * Compatibility maintained for current pipeline while enabling future scaling.
    Sources: [SRC-150, SRC-022, SRC-097]

* ADR_ID: ADR-009
  Title: Plugin hardening with atomic ops, sandboxing, permissions UX, and conflict resolution
  Status: Accepted
  Context: Plugins can override core behavior; must reduce operator error and contain untrusted plugin risk.
  Decision:

  * Redesign plugin IA and flows.
  * Atomic install/update/rollback with staging and hash checks.
  * Two-phase enable.
  * Default untrusted plugins out-of-process; PolicyGate deny-by-default.
  * Conflict resolution required before enable (priority graph).
    Consequences:
  * More implementation complexity; improves stability and security.
    Sources: [SRC-011, SRC-049, SRC-050, SRC-052, SRC-054, SRC-053, SRC-085, SRC-059, SRC-127, SRC-148]

* ADR_ID: ADR-010
  Title: Conservative Q&A with citations required
  Status: Accepted
  Context: User demands “never make shit up”; citations required; UI must show proof and missing evidence.
  Decision:

  * Default answer policy requires citations; if unavailable, respond with conservative message and diagnostic suggestions.
  * Show proof chips and retrieval trace; show missing evidence explicitly.
    Consequences:
  * More “I don’t know yet” responses; preserves trust.
    Sources: [SRC-044, SRC-152, SRC-067, SRC-063, SRC-136]

* ADR_ID: ADR-011
  Title: Export-only sanitization via local entity hash map
  Status: Accepted
  Context: Cloud optional only through explicit export; sanitization must not mutate local raw; user wants local reversible mapping.
  Decision:

  * Export pipeline performs entity hashing using salted, rotatable local map.
  * Export review UI shows hashed entity dictionary locally after unlock; export bundle excludes dictionary.
  * All exports audited and include ledger head.
    Consequences:
  * Requires entity extraction + hashing components and review UX.
    Sources: [SRC-009, SRC-037, SRC-084, SRC-089, SRC-115, SRC-083, SRC-034]

* ADR_ID: ADR-012
  Title: Default-on encryption and migration-safe key management
  Status: Accepted
  Context: Raw media is sensitive; must be encrypted at rest and migratable to new machine without breaking access.
  Decision:

  * Encrypt DB+media at rest by default; unlock via Windows Hello with auto-lock.
  * Key escrow locally (DPAPI-protected) and backup/export of key material only via explicit workflow in Backup/Restore module.
    Consequences:
  * Requires careful key handling to support migration and restore.
    Sources: [SRC-081, SRC-024, SRC-151, SRC-017]

* ADR_ID: ADR-013
  Title: SLOs, error budgets, and diagnostics-first operations
  Status: Accepted
  Context: Must detect silent failures and make capture state obvious; diagnostics bundles needed without leaking raw media by default.
  Decision:

  * Add SLO dashboard and error budgets in UI.
  * Implement silent failure detector (HID active but no captures).
  * Provide diagnostics bundle export excluding raw media by default.
    Consequences:
  * Additional metrics and UI work; reduces time-to-detect and time-to-recover.
    Sources: [SRC-070, SRC-075, SRC-072, SRC-065, SRC-074]

* ADR_ID: ADR-014
  Title: Test strategy as release gate
  Status: Accepted
  Context: System must be trustworthy long-term; migrations must preserve citations/ledger continuity; platform-specific capture must be validated.
  Decision: CI must run golden, chaos, migration, e2e Q&A, fuzz, resource budget, Windows capture integration, localhost security, provenance tamper detection, and accessibility suites.
  Consequences:

  * Heavier CI; strong regression protection.
    Sources: [SRC-100, SRC-101, SRC-102, SRC-103, SRC-105, SRC-106, SRC-107, SRC-108, SRC-109]

* ADR_ID: ADR-015
  Title: Split kernel into Windows Service + user-space UI/processing
  Status: Accepted
  Context: Capture must remain stable and survive UI failures; reboot should resume capture.
  Decision: Implement capture+DB+journal as Windows Service; run UI/processing/tray as separate process group; add safe mode on crash loop.
  Consequences:

  * Installer and supervisor complexity; improves stability and reliability.
    Sources: [SRC-028, SRC-027]

# 4. Grounding Data (Few-Shot Samples)

* Sample_ID: SAMPLE-001
  Related_Modules: [MOD-001]
  Purpose: Demonstrate strict change-driven capture and exact dedupe-by-hash.
  Table:

  | ts_utc                   | trigger       | raw_pixels_hash | prev_raw_pixels_hash | action          |
  | ------------------------ | ------------- | --------------- | -------------------- | --------------- |
  | 2026-01-30T20:14:05.123Z | hid_input     | b3:AAA          | b3:AAA               | skip_duplicate  |
  | 2026-01-30T20:14:05.623Z | screen_change | b3:AAB          | b3:AAA               | store_new_frame |
  | 2026-01-30T20:14:06.123Z | screen_change | b3:AAC          | b3:AAB               | store_new_frame |

* Sample_ID: SAMPLE-002
  Related_Modules: [MOD-004]
  Purpose: Show crash-safe capture journaling and reconciliation.
  Table:

  | journal_seq | kind            | frame_id | staging_path            | committed_path               | reconcile_outcome       |
  | ----------: | --------------- | -------- | ----------------------- | ---------------------------- | ----------------------- |
  |         501 | MEDIA_STAGED    | f-123    | staging/ab/cd/f-123.tmp | null                         | pending_on_crash        |
  |         502 | RECONCILE_RETRY | f-123    | staging/ab/cd/f-123.tmp | media/ab/cd/f-123.webp.acenc | committed_after_restart |
  |         503 | COMMITTED       | f-123    | null                    | media/ab/cd/f-123.webp.acenc | ok                      |

* Sample_ID: SAMPLE-003
  Related_Modules: [MOD-008]
  Purpose: Demonstrate idempotent worker behavior via dedupe_key.
  Table:

  | job_id  | artifact_type | engine_version | input_hash | dedupe_key | result |        |                            |
  | ------- | ------------- | -------------- | ---------- | ---------- | ------ | ------ | -------------------------- |
  | job-001 | ocr_spans     | 2.7.0          | b3:AAB     | ocr_spans  | 2.7.0  | b3:AAB | created artifact a-001     |
  | job-002 | ocr_spans     | 2.7.0          | b3:AAB     | ocr_spans  | 2.7.0  | b3:AAB | no duplicate; reused a-001 |
  | job-003 | ocr_spans     | 2.7.1          | b3:AAB     | ocr_spans  | 2.7.1  | b3:AAB | created artifact a-002     |

* Sample_ID: SAMPLE-004
  Related_Modules: [MOD-003]
  Purpose: Show foreground gating transitions and GPU preemption.
  Table:

  | ts_utc               | hid_state | processing_workers | gpu_allowed | action_taken                   |
  | -------------------- | --------- | ------------------ | ----------- | ------------------------------ |
  | 2026-01-30T20:00:00Z | IDLE      | 4                  | true        | start_idle_jobs                |
  | 2026-01-30T20:00:05Z | ACTIVE    | 0                  | false       | pause_processing + gpu_preempt |
  | 2026-01-30T20:05:10Z | IDLE      | 4                  | true        | resume_processing              |

* Sample_ID: SAMPLE-005
  Related_Modules: [MOD-009, MOD-014]
  Purpose: Conservative answer behavior when citations are missing or evidence is broken.
  Table:

  | query                     | citations_found | missing_evidence | response_style                        |
  | ------------------------- | --------------- | ---------------- | ------------------------------------- |
  | "What happened today?"    | 12              | none             | answer + citations + proof chips      |
  | "What did I type at 3pm?" | 0               | none             | "I can’t cite evidence for this yet." |
  | "Open the invoice text"   | 3               | frames_missing=1 | answer + warn "evidence missing"      |

* Sample_ID: SAMPLE-006
  Related_Modules: [MOD-011]
  Purpose: Export-only sanitization and local-only entity map.
  Table:

  | entity_text                       | entity_type | hashed_value | included_in_export_bundle | visible_locally_after_unlock |
  | --------------------------------- | ----------- | ------------ | ------------------------- | ---------------------------- |
  | "Acme Corp"                       | org         | h:9f2a...    | true (hashed only)        | true                         |
  | "[john@x.com](mailto:john@x.com)" | email       | h:12bb...    | true (hashed only)        | true                         |
  | "4111 1111"                       | cc          | h:77cd...    | true (hashed only)        | true                         |

* Sample_ID: SAMPLE-007
  Related_Modules: [MOD-012]
  Purpose: Two-phase enable and conflict blocking.
  Table:

  | plugin_id    | requests_permissions | conflicts_detected | enable_result                      |
  | ------------ | -------------------- | ------------------ | ---------------------------------- |
  | ocr.paddle   | ["filesystem"]       | none               | allowed -> sandbox_load -> enabled |
  | pluginA.over | ["network"]          | conflicts=1        | blocked: resolve conflict first    |
  | risky.plugin | ["shell"]            | none               | denied by PolicyGate by default    |
