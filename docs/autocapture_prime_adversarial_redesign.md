# Adversarial Redesign Proposal — Autocapture Prime (repo snapshot)

Source snapshot: [repomix-output.md](sandbox:/mnt/data/repomix-output.md)

## Assumptions

- Analysis is restricted to the single provided snapshot file; no execution or external systems are assumed (no evidence otherwise).
- Windows 11 + WSL2 is the target environment; where repo evidence is Linux/POSIX-oriented, platform-safe equivalents are proposed.
- Local-only by default is the intended security posture unless explicitly enabled via config flags (e.g., allow_remote / privacy.cloud).
- The plugin system is the primary extension mechanism; any functionality not expressed as a plugin is treated as core kernel behavior.
- Determinism means: identical inputs + identical effective config + identical plugin+contract locks → identical ordering/hashes/outputs (within documented tolerances).
- Citeability means: every user-visible output can be traced to immutable evidence spans and cryptographically verifiable lineage artifacts.
- Performance recommendations prioritize reducing capture lag and query latency without weakening durability or audit guarantees.
- Where repo intent is unclear or conflicting, the report states “no evidence” and treats it as a risk/gap rather than inventing behavior.

## THREAD / CHAT_ID

- **THREAD:** PROJECT_AUTOCAPTURE_PRIME
- **CHAT_ID:** UNKNOWN

## Key claims

- **CITE:** Repo describes “Autocapture Prime” as a plugin-forward capture+query kernel, with `autocapture_nx` as canonical runtime. (README.md:1-8)
- **CITE:** Security contract is local-first: deny network by default, require citations for claims, and treat cloud as explicitly enabled. (contracts/security.md:1-31)
- **CITE:** Default plugin hosting is subprocess with job limits; in-proc allowlist is empty; network-capable plugins must be allowed explicitly. (config/default.json:963-1008; autocapture_nx/plugin_system/registry.py:548-601)
- **CITE:** Ledger is append-only with hash chaining and fsync, and stores policy snapshot hashes for auditability. (plugins/builtin/ledger_basic/plugin.py:60-112)
- **CITE:** Web console is authenticated and local-only by default (allow_remote=false), with FastAPI routes for run/query/verify/plugins/telemetry. (config/default.json:1501-1521; autocapture/web/auth.py:1-96; autocapture/web/api.py:1-70)
- **INFERENCE:** Repo is already architected for strong provenance, but several critical state files are not written atomically, creating crash/power-loss footguns. (autocapture_nx/kernel/loader.py:742-774; autocapture_nx/plugin_system/manager.py:241-257)

## Timeline

- **D0:** 2026-02-06 (America/Denver)

- **Phase 0:** 2026-02-06 → 2026-02-20
- **Phase 1:** 2026-02-21 → 2026-03-31
- **Phase 2:** 2026-04-01 → 2026-05-31
- **Phase 3:** 2026-06-01 → 2026-07-31

## Context derived from repo

### What this repository is

- A local-first, plugin-forward “capture → process → query” system (“Autocapture Prime”) with a canonical runtime package `autocapture_nx` and a legacy/UX package `autocapture`. (README.md:1-12)

### Primary workflows

- **Core run loop:** `autocapture run` starts capture + background processing. (contracts/user_surface.md:1-60)
- **Query:** `autocapture query "…"` returns answers with citations/evidence requirements. (contracts/user_surface.md:30-60; contracts/security.md:27-31)
- **Web/tray console:** `autocapture web` serves a local console for status, query, plugin management, verification, diagnostics. (contracts/user_surface.md:44-60; autocapture/web/api.py:1-70)
- **Integrity/verification:** `autocapture verify` and proof-bundle export/verify exist for citeability. (contracts/user_surface.md:44-60; autocapture_nx/kernel/proof_bundle.py:130-220)

### Major components

- **Kernel loader / lifecycle:** boot sequence loads config, enforces safe mode/crash-loop, validates contract lock, applies network deny, and initializes plugins. (autocapture_nx/kernel/loader.py:170-204; autocapture_nx/kernel/loader.py:420-462)
- **Plugin system:** registry enforces plugin locks and capability rules; runtime provides filesystem and network guards; subprocess hosting uses Windows Job Objects for limits. (autocapture_nx/plugin_system/registry.py:548-676; autocapture_nx/plugin_system/runtime.py:108-226; autocapture_nx/windows/win_sandbox.py:37-110)
- **State + provenance:** append-only journal + hash-chained ledger + DPAPI anchors; proof-bundle exporter packages verifiable subsets. (plugins/builtin/journal_basic/plugin.py:43-145; plugins/builtin/ledger_basic/plugin.py:60-156; plugins/builtin/anchor_basic/plugin.py:35-92; autocapture_nx/kernel/proof_bundle.py:130-220)
- **Query pipeline:** kernel query records a ledger event including blocked/ran extraction state; answer layer enforces citations. (autocapture_nx/kernel/query.py:644-706; plugins/builtin/answer_basic/plugin.py:1-110)
- **Web console:** FastAPI app + local-only auth; endpoints cover run/query/verify/plugins/telemetry/media/trace. (autocapture/web/auth.py:1-96; autocapture/web/api.py:1-70)

### Storage/state model

- **Data directory** contains media, metadata, indices, and run state; encryption is supported by storage plugins (encrypted layer wraps media/metadata). (plugins/builtin/storage_encrypted/plugin.py:1-120)
- **Provenance stores** are NDJSON files with fsync for journal and ledger; anchors stored separately and protected via DPAPI when possible. (plugins/builtin/journal_basic/plugin.py:43-145; plugins/builtin/ledger_basic/plugin.py:60-156; plugins/builtin/anchor_basic/plugin.py:35-92)

### Execution model

- **Default hosting:** plugins run as subprocesses with job limits; in-proc plugins are allowlisted (default allowlist empty). (config/default.json:963-1008)
- **Network posture:** global network deny is applied unless explicitly allowed; only allowlisted plugin IDs may perform network operations. (config/default.json:1000-1008; autocapture_nx/plugin_system/registry.py:556-601)

### Interfaces

- **CLI** (`autocapture` entrypoint) supports doctor/config/run/query/verify/web. (contracts/user_surface.md:1-60)
- **Web UI** provides panels for capture, query, timeline, plugins, verification, and telemetry. (autocapture/web/ui/index.html:1-120)

### External integrations (as evidenced in repo)

- **FastAPI** web console and **DPAPI** for local key protection. (autocapture/web/api.py:1-70; plugins/builtin/anchor_basic/plugin.py:35-92)
- **Qdrant** vector index is supported but restricted to localhost URLs; otherwise a SQLite-based index is used. (autocapture/indexing/factory.py:1-67)
- **WSL2 queue** exists for dispatching “gpu_heavy” jobs via a shared directory protocol. (autocapture/runtime/wsl2_queue.py:13-78; config/default.json:1417-1424)

### Boundary / ambiguity notes

- The repo contains both `autocapture_nx` and `autocapture` packages; some responsibilities (e.g., verification utilities) exist in the legacy package. This is a drift risk unless enforced by contract/policy gates. (README.md:4-12; plugins/builtin/ledger_basic/plugin.py:128-156)
- Dev tray launcher hardcodes host/port (127.0.0.1:8787), which can diverge from config and cause operator confusion. (ops/dev/launch_tray.ps1:290-318)

## Red-team failure scenarios

### A) Red-team as a User (Justin)

| id | scenario | detection | mitigation |
| --- | --- | --- | --- |
| U-01 | Runs `autocapture run` in the wrong config/data directory and unknowingly queries a different dataset | UI/CLI provenance header shows unexpected data_dir/run_id; integrity scan reports different counts; SLO shows “stale capture” | FND-01 instance lock + UX-02 prominent data_dir/run_id + META-03 provenance everywhere + `config show --paths` command |
| U-02 | Misinterprets answer as complete even though extraction was blocked (allow_decode_extract=false) | Query result includes blocked_extract + missing_spans_count; UI coverage bar <100% | EXEC-07 schedule extraction + UX-04 completeness UI + META-08 evaluation fields |
| U-03 | Accidentally enables egress or raw egress via a quick toggle under fatigue | Policy snapshot changes logged; UI banner shows “egress enabled”; ledger records policy change | UX-06 typed confirmation + SEC-04 approval_required by default + META-06 policy snapshot export |
| U-04 | Approves a plugin without understanding its filesystem scope; plugin exfiltrates or deletes local data | Plugin permission diff shows broad roots; fs_guard deny/allow counters; audit log shows file ops outside expected | EXT-06 permission UX + SEC-01 hardened filesystem guard + EXT-01 lifecycle states |
| U-05 | Thinks capture is paused, but capture continues (tray indicator unclear) | Ledger shows capture.start without matching stop; UI banner indicates active capture; disk usage increasing | SEC-08 explicit capture indicator + UX-02 pause/resume panel + ledgered start/stop |
| U-06 | Edits user.json manually and introduces a syntax error; next boot fails | Doctor/config validator error shown; UI safe-mode banner with reason code | FND-02 atomic writes + UX-09 presets/diff viewer + FND-10 safe-mode remediation UI |
| U-07 | Exports a proof bundle and later cannot verify what it contains or whether it was tampered with | Bundle verification report missing signature; hashes not covering all files | SEC-07 signed bundle + META-03 provenance header + FND-03 integrity scan |
| U-08 | Runs queries during heavy background processing; results are slow and feel ‘hung’ | Telemetry shows queue depth, query_latency spikes; UI shows active background jobs | EXEC-03 concurrency budgets + OPS-02 metrics + PERF-08 auto-throttle |
| U-09 | Uses the dev tray launcher that hardcodes port 8787; conflicts with another service or user-changed config | Tray launch fails or opens wrong instance; web bind mismatch | SEC-03 tray launcher respects config or refuses; UI displays actual bind address |
| U-10 | Assumes citations are ‘links’ but cannot locate underlying evidence quickly | User clicks citation but no evidence viewer; high ‘open evidence’ latency | UX-04 citation explorer + META-05 span addressing + Run/job detail view (UX-03) |
| U-11 | Low disk causes capture to partially write segments; later queries fail or are inconsistent | Disk free metric low; journal shows segment errors; integrity scan reports missing blobs | FND-06 disk-pressure pause + FND-03 integrity scan + OPS-02 metrics |
| U-12 | Upgrades plugins/contracts and then cannot explain behavior change | Run manifest shows new lock hashes; ledger contains lock_update/config_change events | META-01 config snapshots + META-02 plugin provenance + EXT-03 rollback + RD-05 regression gates |

### B) Red-team as a System Admin/Operator

| id | scenario | detection | mitigation |
| --- | --- | --- | --- |
| A-01 | Plugin update introduces incompatibility; kernel fails to boot or crashes | Registry refuses plugin via compatibility gate; audit log shows crash loop; doctor reports degraded capability | EXT-04 compatibility contracts + EXT-03 rollback + FND-10 safe-mode banner |
| A-02 | Contract lock drift (contracts/lock.json mismatch) blocks boot unexpectedly after merge | Loader verify_contract_lock failure; gate_contract_pins CI failure | RD-05 gates + tooling to update lock with review + META-04 schema versioning |
| A-03 | Corrupted ledger/journal due to disk or partial write; verification fails | Integrity scan detects broken hash chain; verify endpoint returns failure | FND-03 integrity scan + FND-02 atomic writes + OPS-03 diagnostics bundle |
| A-04 | State store schema drift across versions (metadata.db/state_tape.db); subtle runtime bugs | Doctor reports schema_version mismatch; migration status endpoint shows drift | FND-08 migrations + OPS-06 migration status + QA-05 migration tests |
| A-05 | WSL2 queue directory permissions break; gpu_heavy jobs silently never complete | Queue depth grows; conductor reports timeouts; wsl2 job files stuck in outbox | PERF-04 round-trip protocol + OPS-04 health details + EXEC-02 retries |
| A-06 | Performance regression after update; capture lag exceeds SLO and user loses trust | gate_perf fails; SLO dashboard budget burn; telemetry p95 capture lag increased | PERF-07 regression gates + OPS-08 budgets + RD-05 release policy |
| A-07 | Plugin sandbox bypass via Windows path edge cases or early socket creation | Security guard tests fail; deny counters missing; unexpected network/file activity in audit log | SEC-01 path hardening + SEC-02 early guard + QA-04 security regression suite |
| A-08 | Operator enables allow_remote or exposes web console on LAN accidentally | Auth logs show non-loopback requests; bind_host not loopback; doctor warns | SEC-03 enforce loopback + web/auth strict local-only defaults + gate_doctor check |
| A-09 | Key rotation leaves mixed-key data unreadable or partially rewrapped | Reads fail for some blobs; key_id mismatches; doctor reports missing keys | SEC-06 staged rewrap + tests + operator runbook (RD-06) |
| A-10 | Diagnostics bundles leak secrets or PII (logs/config) | Secret scanning gate flags; redaction tests fail; bundle contains raw tokens | SEC-09 secret hygiene + OPS-03 redacted bundles + SEC-05 redaction |
| A-11 | Plugin approvals/locks are manually edited; system behavior changes silently | Lock signature verification fails; ledger records unexpected lock_update event | EXT-11 signed lockfile + FND-03 integrity scan + RD-05 gates |
| A-12 | Operator needs rollback but has no quick procedure under incident pressure | High error rate; repeated restarts; unclear steps | EXT-03 rollback + OPS-05 operator commands + RD-06 runbook |

# Recommendations (bucketed)

## I. Foundation

| id | scores | effort | risk | recommendation |
| --- | --- | --- | --- | --- |
| FND-03 | 2/2/2/4=10 | M | Low | Add `autocapture integrity scan` to verify ledger chain, anchors, blob hashes, and metadata references |
| FND-01 | 1/3/2/3=9 | S | Low | Add an exclusive instance lock for (config_dir, data_dir) to prevent concurrent writers |
| FND-05 | 2/1/3/3=9 | M | Med | Introduce content-addressed ingest IDs for file-based inputs (sha256→input_id) and dedupe at ingest boundary |
| FND-08 | 1/2/3/3=9 | L | Med | Add explicit DB migration framework with version pinning + rollback plan for all sqlite/state stores |
| FND-02 | 1/2/2/3=8 | M | Low | Centralize atomic-write (temp+fsync+rename) for all JSON/NDJSON state writes (config, run_state, approvals, audit) |
| FND-04 | 1/1/2/4=8 | M | Low | Record run-recovery actions as first-class journal/ledger events (quarantine, seal, replay) with before/after hashes |
| FND-06 | 3/1/2/2=8 | M | Low | Make disk-pressure handling fail-safe: preflight free-space, throttle capture/processing, and surface “paused due to disk” state |
| FND-07 | 1/2/2/3=8 | L | Med | Add `autocapture backup create/restore` for config + locks + anchors (and optional data) with integrity checks |
| FND-09 | 1/1/3/3=8 | M | Low | Standardize timestamp handling: store UTC in records, include tz_offset, and use monotonic clocks for durations |
| FND-10 | 0/2/2/2=6 | S | Low | Make safe-mode and crash-loop reasons user-visible (CLI + web UI) with a deterministic “next safe action” checklist |

### FND-03

| Field | Value |
| --- | --- |
| Recommendation | Add `autocapture integrity scan` to verify ledger chain, anchors, blob hashes, and metadata references |
| Rationale | Makes corruption detectable early and gives operators a deterministic, auditable health report. |
| Pillar scores (P1/P2/P3/P4=Total) | 2/2/2/4=10 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Citeability, Accuracy, Performance, Security |
| risked | None |
| enforcement_location | autocapture_nx/cli.py, autocapture/pillars/citable.py, autocapture_nx/kernel/proof_bundle.py, plugins/builtin/storage_* |
| regression_detection | tests/test_integrity_scan.py; tools/gate_doctor.py (optional); ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Corrupt one byte in ledger.ndjson and one blob; scan reports both with exact IDs and exits non-zero. |

### FND-01

| Field | Value |
| --- | --- |
| Recommendation | Add an exclusive instance lock for (config_dir, data_dir) to prevent concurrent writers |
| Rationale | Prevents silent state corruption when two kernel instances share the same stores; also reduces “wrong dataset” confusion. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/3/2/3=9 |
| Effort | S |
| Risk | Low |
| Dependencies | None |
| improved | Security, Accuracy, Citeability |
| risked | Performance |
| enforcement_location | autocapture_nx/kernel/loader.py, autocapture_nx/kernel/paths.py |
| regression_detection | tests/test_instance_lock.py; tools/gate_doctor.py (add check); ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Start two kernels pointing at same data_dir; second exits with deterministic error and leaves stores unmodified. |

### FND-05

| Field | Value |
| --- | --- |
| Recommendation | Introduce content-addressed ingest IDs for file-based inputs (sha256→input_id) and dedupe at ingest boundary |
| Rationale | Reduces user errors (“wrong file selected twice”) and ensures deterministic identity across runs and exports. |
| Pillar scores (P1/P2/P3/P4=Total) | 2/1/3/3=9 |
| Effort | M |
| Risk | Med |
| Dependencies | None |
| improved | Accuracy, Citeability, Performance |
| risked | Security |
| enforcement_location | autocapture_nx/ingest/*, autocapture_nx/kernel/prefixed_id.py, plugins/builtin/storage_media_basic/plugin.py |
| regression_detection | tests/test_ingest_dedupe.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Ingest same file twice; metadata store returns same input_id and does not duplicate blobs. |

### FND-08

| Field | Value |
| --- | --- |
| Recommendation | Add explicit DB migration framework with version pinning + rollback plan for all sqlite/state stores |
| Rationale | Prevents silent schema drift and makes upgrades/rollbacks operable and auditable. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/2/3/3=9 |
| Effort | L |
| Risk | Med |
| Dependencies | None |
| improved | Accuracy, Citeability, Security |
| risked | Performance |
| enforcement_location | autocapture_nx/storage/*, autocapture/indexing/*, tools/gate_contract_pins.py (extend) |
| regression_detection | tests/test_db_migrations.py; tools/gate_doctor.py (schema version); ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Apply migration forward then rollback on fixture DB; queries still work and schema_version matches expected values. |

### FND-02

| Field | Value |
| --- | --- |
| Recommendation | Centralize atomic-write (temp+fsync+rename) for all JSON/NDJSON state writes (config, run_state, approvals, audit) |
| Rationale | Hardens crash/power-loss durability beyond ledger/journal; avoids partial JSON that bricks boot or UI. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/2/2/3=8 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Citeability, Security |
| risked | Performance |
| enforcement_location | autocapture_nx/kernel/loader.py, autocapture_nx/plugin_system/manager.py, autocapture/config/load.py, autocapture_nx/kernel/audit.py |
| regression_detection | tests/test_atomic_write.py; tools/gate_doctor.py (verify JSON parse); ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Kill process mid-write via test hook; after restart, file is either previous valid version or new valid version (never partial). |

### FND-04

| Field | Value |
| --- | --- |
| Recommendation | Record run-recovery actions as first-class journal/ledger events (quarantine, seal, replay) with before/after hashes |
| Rationale | Crash recovery is currently implicit; making it explicit improves auditability and prevents “mysterious” changes. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/2/4=8 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Citeability, Accuracy |
| risked | Performance |
| enforcement_location | autocapture_nx/kernel/loader.py, plugins/builtin/journal_basic/plugin.py, plugins/builtin/ledger_basic/plugin.py |
| regression_detection | tests/test_recovery_audit_entries.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Create a dangling segment file; boot triggers recovery; ledger contains `recovery.*` events referencing affected artifact hashes. |

### FND-06

| Field | Value |
| --- | --- |
| Recommendation | Make disk-pressure handling fail-safe: preflight free-space, throttle capture/processing, and surface “paused due to disk” state |
| Rationale | Prevents partial writes and corrupted segments when disk fills; reduces operator incidents under no-deletion defaults. |
| Pillar scores (P1/P2/P3/P4=Total) | 3/1/2/2=8 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Performance, Accuracy, Citeability |
| risked | Security |
| enforcement_location | autocapture_nx/capture/pipeline.py, autocapture_nx/storage/retention.py, autocapture/web/ui/index.html |
| regression_detection | tests/test_disk_pressure_pause.py; tools/gate_perf.py (baseline); ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Simulate low disk; capture enters paused state, no new segments are started, UI shows actionable banner, resumes when space returns. |

### FND-07

| Field | Value |
| --- | --- |
| Recommendation | Add `autocapture backup create/restore` for config + locks + anchors (and optional data) with integrity checks |
| Rationale | Provides deterministic recovery and rollback; reduces downtime after config corruption or mistaken edits. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/2/2/3=8 |
| Effort | L |
| Risk | Med |
| Dependencies | FND-03 |
| improved | Citeability, Security, Accuracy |
| risked | Performance |
| enforcement_location | autocapture_nx/cli.py, autocapture_nx/kernel/paths.py, plugins/builtin/ledger_basic/plugin.py, plugins/builtin/anchor_basic/plugin.py |
| regression_detection | tests/test_backup_restore.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Create backup, wipe config_dir, restore; doctor passes and ledger/anchors verify; optional data restore preserves blob hashes. |

### FND-09

| Field | Value |
| --- | --- |
| Recommendation | Standardize timestamp handling: store UTC in records, include tz_offset, and use monotonic clocks for durations |
| Rationale | Eliminates DST/locale-induced nondeterminism and improves replay correctness. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/3/3=8 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Citeability |
| risked | Performance, Security |
| enforcement_location | autocapture_nx/kernel/determinism.py, plugins/builtin/* (event timestamps), autocapture_nx/kernel/run_state.py |
| regression_detection | tests/test_time_normalization.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Create events across DST boundary; timestamps are UTC with offsets; replay produces same ordering and durations. |

### FND-10

| Field | Value |
| --- | --- |
| Recommendation | Make safe-mode and crash-loop reasons user-visible (CLI + web UI) with a deterministic “next safe action” checklist |
| Rationale | Reduces operator time-to-recovery; prevents unsafe manual edits under stress. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/2/2/2=6 |
| Effort | S |
| Risk | Low |
| Dependencies | None |
| improved | Security, Accuracy, Citeability |
| risked | None |
| enforcement_location | autocapture_nx/kernel/loader.py, docs/safe_mode.md, autocapture/web/ui/index.html |
| regression_detection | tests/test_safe_mode_ui_banner.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Force safe_mode via crash marker; UI shows reason code, disabled capabilities, and a copyable remediation checklist. |


## II. Metadata

| id | scores | effort | risk | recommendation |
| --- | --- | --- | --- | --- |
| META-07 | 2/1/3/4=10 | L | Med | Introduce a content-addressed artifact manifest for all derived artifacts (OCR text, embeddings, indexes) with lineage pointers |
| META-01 | 1/1/3/4=9 | M | Low | Persist a canonical effective-config snapshot per run (config.effective.json + sha256) and link it from run_manifest |
| META-06 | 0/3/2/4=9 | M | Low | Persist full policy snapshots (privacy + plugin permissions + egress settings) by hash, and include in ledger + proof bundle |
| META-02 | 0/2/2/4=8 | M | Low | Capture plugin provenance: store (plugin_id, version, manifest_sha256, artifact_sha256, permissions) for every loaded plugin in run_manifest |
| META-04 | 1/1/3/3=8 | M | Med | Version all record schemas explicitly (schema_version field) and enforce validation at write boundaries |
| META-05 | 0/1/3/4=8 | M | Low | Normalize citation addressing: require citations to reference (evidence_id, span_id, start/end offsets or time range) + stable locator |
| META-08 | 1/1/3/3=8 | M | Low | Add minimal evaluation-result records (quality, coverage, freshness) and surface them in query results and UI |
| META-09 | 0/1/3/4=8 | M | Low | Record determinism inputs explicitly: RNG seeds, locale/TZ, model versions, and any sampling parameters used |
| META-03 | 0/1/2/4=7 | S | Low | Add a standard `provenance` object to all user-visible outputs (CLI query, web query, exports) |
| META-10 | 1/1/2/3=7 | S | Low | Define a canonical diagnostics bundle schema (bundle_manifest.json) for doctor + support artifacts |

### META-07

| Field | Value |
| --- | --- |
| Recommendation | Introduce a content-addressed artifact manifest for all derived artifacts (OCR text, embeddings, indexes) with lineage pointers |
| Rationale | Makes derived outputs reproducible and prevents “mystery artifacts” from contaminating queries. |
| Pillar scores (P1/P2/P3/P4=Total) | 2/1/3/4=10 |
| Effort | L |
| Risk | Med |
| Dependencies | None |
| improved | Citeability, Accuracy, Performance |
| risked | Security |
| enforcement_location | autocapture_nx/kernel/derived_records.py, autocapture_nx/kernel/metadata_store.py, autocapture_nx/kernel/proof_bundle.py |
| regression_detection | tests/test_artifact_manifest_lineage.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Derived artifact has sha256 and `derived_from` pointing to evidence+config hashes; integrity scan verifies reachability. |

### META-01

| Field | Value |
| --- | --- |
| Recommendation | Persist a canonical effective-config snapshot per run (config.effective.json + sha256) and link it from run_manifest |
| Rationale | Hash-only config is not sufficient for post-hoc reproduction; snapshot enables deterministic reruns and proof bundles. (No evidence of a persisted effective-config snapshot beyond hashes in run_state/run_manifest: autocapture_nx/kernel/loader.py:742-774, 856-934.) |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/3/4=9 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Citeability |
| risked | Security, Performance |
| enforcement_location | autocapture_nx/kernel/loader.py, autocapture/config/load.py, autocapture_nx/kernel/canonical_json.py |
| regression_detection | tests/test_run_config_snapshot.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Boot kernel; run directory contains config.effective.json; sha256 matches run_manifest field and ledger `run.start` record. |

### META-06

| Field | Value |
| --- | --- |
| Recommendation | Persist full policy snapshots (privacy + plugin permissions + egress settings) by hash, and include in ledger + proof bundle |
| Rationale | Ledger currently stores policy_snapshot_hash; storing the snapshot content enables audit and compliance proof. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/3/2/4=9 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Security, Citeability, Accuracy |
| risked | None |
| enforcement_location | plugins/builtin/ledger_basic/plugin.py, autocapture_nx/kernel/policy_gate.py, autocapture_nx/kernel/proof_bundle.py |
| regression_detection | tests/test_policy_snapshot_exported.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Export proof bundle; includes policy_snapshot.json keyed by hash; verifying bundle checks hash matches ledger entries. |

### META-02

| Field | Value |
| --- | --- |
| Recommendation | Capture plugin provenance: store (plugin_id, version, manifest_sha256, artifact_sha256, permissions) for every loaded plugin in run_manifest |
| Rationale | Allows answering “what code ran” and prevents ambiguity when locks change later. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/2/2/4=8 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Citeability, Security, Accuracy |
| risked | None |
| enforcement_location | autocapture_nx/plugin_system/registry.py, autocapture_nx/kernel/loader.py, config/plugin_locks.json |
| regression_detection | tests/test_plugin_provenance_in_manifest.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Run kernel; run_manifest lists each enabled plugin with hashes and permissions; proof bundle includes same. |

### META-04

| Field | Value |
| --- | --- |
| Recommendation | Version all record schemas explicitly (schema_version field) and enforce validation at write boundaries |
| Rationale | Prevents silent schema drift and enables safe migrations and replay across versions. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/3/3=8 |
| Effort | M |
| Risk | Med |
| Dependencies | None |
| improved | Accuracy, Citeability, Security |
| risked | Performance |
| enforcement_location | contracts/*.schema.json, autocapture_nx/kernel/evidence.py, plugins/builtin/* |
| regression_detection | tests/test_schema_version_enforced.py; tools/gate_contract_pins.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Attempt to write a record missing schema_version; write is rejected; old fixtures still validate with their pinned version. |

### META-05

| Field | Value |
| --- | --- |
| Recommendation | Normalize citation addressing: require citations to reference (evidence_id, span_id, start/end offsets or time range) + stable locator |
| Rationale | Reduces misinterpretation and supports precise replay/verification of claims. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/1/3/4=8 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Citeability |
| risked | None |
| enforcement_location | contracts/answer.schema.json, plugins/builtin/citation_basic/*, autocapture_nx/kernel/query.py |
| regression_detection | tests/test_citation_span_contract.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Generate answer; every citation includes span coordinates; replay tool can extract same text and verify hash equality. |

### META-08

| Field | Value |
| --- | --- |
| Recommendation | Add minimal evaluation-result records (quality, coverage, freshness) and surface them in query results and UI |
| Rationale | Turns silent failure modes (missing extraction/index) into measurable, explainable signals. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/3/3=8 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Citeability |
| risked | Performance, Security |
| enforcement_location | contracts/evaluation.schema.json (new), autocapture_nx/kernel/query.py, autocapture/web/ui/index.html |
| regression_detection | tests/test_query_evaluation_fields.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Query returns evaluation fields like coverage_ratio and missing_spans_count; UI displays without blocking. |

### META-09

| Field | Value |
| --- | --- |
| Recommendation | Record determinism inputs explicitly: RNG seeds, locale/TZ, model versions, and any sampling parameters used |
| Rationale | Improves replay fidelity and reduces “modeled vs measured” ambiguity. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/1/3/4=8 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Citeability |
| risked | Performance, Security |
| enforcement_location | autocapture_nx/kernel/determinism.py, autocapture_nx/plugin_system/registry.py (RNGScope), contracts/run_manifest.schema.json (new) |
| regression_detection | tests/test_manifest_determinism_fields.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Run manifest includes tz/locale plus rng seeds; re-run in replay mode produces identical ordering and hashes. |

### META-03

| Field | Value |
| --- | --- |
| Recommendation | Add a standard `provenance` object to all user-visible outputs (CLI query, web query, exports) |
| Rationale | Makes “processing happened against THIS input + THIS config” provable in the primary UX, not just internal files. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/1/2/4=7 |
| Effort | S |
| Risk | Low |
| Dependencies | None |
| improved | Citeability, Accuracy |
| risked | Security, Performance |
| enforcement_location | autocapture_nx/kernel/query.py, autocapture/web/routes/query.py, autocapture_nx/cli.py, contracts/answer.schema.json |
| regression_detection | tests/test_query_provenance_header.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Query response includes provenance fields (run_id, query_id, ledger_head_hash, anchor_ref, config_hash, plugin_lock_hash). |

### META-10

| Field | Value |
| --- | --- |
| Recommendation | Define a canonical diagnostics bundle schema (bundle_manifest.json) for doctor + support artifacts |
| Rationale | Makes operator exports machine-parseable and comparable across versions. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/2/3=7 |
| Effort | S |
| Risk | Low |
| Dependencies | None |
| improved | Citeability, Accuracy, Performance |
| risked | Security |
| enforcement_location | autocapture_nx/cli.py, tools/gate_doctor.py, contracts/diagnostics_bundle.schema.json (new) |
| regression_detection | tests/test_diagnostics_bundle_schema.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Run `autocapture doctor --bundle`; output includes bundle_manifest.json validating against schema; redaction applied. |


## III. Execution

| id | scores | effort | risk | recommendation |
| --- | --- | --- | --- | --- |
| EXEC-04 | 2/1/3/4=10 | L | Med | Implement `autocapture replay` to re-run processing/indexing on an existing dataset without mutating original artifacts |
| EXEC-06 | 1/2/3/4=10 | L | High | Introduce staged multi-store writes for evidence: write blob→write metadata→append journal→append ledger, with rollback markers |
| EXEC-01 | 2/1/3/3=9 | L | Med | Formalize a persisted pipeline DAG (stages + deps) for capture→process→index→query, stored in state_tape |
| EXEC-05 | 1/1/4/3=9 | M | Med | Eliminate nondeterminism sources (time.now, unordered dict iteration, RNG) from critical pipelines; enforce stable sort everywhere |
| EXEC-02 | 2/1/2/3=8 | M | Med | Add an idempotent job runner with explicit retry policy (bounded retries + backoff) and attempt records in ledger |
| EXEC-03 | 3/1/2/2=8 | M | Med | Unify concurrency controls: per-stage semaphores + global CPU/RAM budgets + deterministic scheduling |
| EXEC-09 | 2/3/1/2=8 | M | Med | Tighten subprocess plugin runtime limits: enforce RPC timeouts, kill-on-timeout, and record termination in audit log |
| EXEC-07 | 1/1/2/3=7 | M | Low | Make on-query extraction an explicit scheduled job: show blocked reasons and offer “schedule extraction now” |
| EXEC-08 | 1/2/2/2=7 | M | Low | Add standardized health checks for each pipeline capability (capture, OCR, VLM, indexing, retrieval, answer) |
| EXEC-10 | 1/0/3/2=6 | S | Low | Deterministic retrieval tie-breaking: score→evidence_id→span_id ordering, documented as contract |

### EXEC-04

| Field | Value |
| --- | --- |
| Recommendation | Implement `autocapture replay` to re-run processing/indexing on an existing dataset without mutating original artifacts |
| Rationale | Supports safe upgrades and “reprocess with new model” workflows while preserving auditability. |
| Pillar scores (P1/P2/P3/P4=Total) | 2/1/3/4=10 |
| Effort | L |
| Risk | Med |
| Dependencies | META-07 |
| improved | Citeability, Accuracy, Performance |
| risked | Security |
| enforcement_location | autocapture_nx/kernel/replay.py, autocapture_nx/kernel/derived_records.py, autocapture_nx/kernel/proof_bundle.py |
| regression_detection | tests/test_replay_produces_new_artifacts.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Replay creates a new derived-artifact namespace; original evidence and artifacts remain unchanged; lineage links both. |

### EXEC-06

| Field | Value |
| --- | --- |
| Recommendation | Introduce staged multi-store writes for evidence: write blob→write metadata→append journal→append ledger, with rollback markers |
| Rationale | Prevents orphan blobs/records and makes partial commits detectable and repairable. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/2/3/4=10 |
| Effort | L |
| Risk | High |
| Dependencies | None |
| improved | Accuracy, Citeability, Security |
| risked | Performance |
| enforcement_location | plugins/builtin/storage_*, plugins/builtin/journal_basic/plugin.py, plugins/builtin/ledger_basic/plugin.py |
| regression_detection | tests/test_two_phase_commit_recovery.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Force failure between steps; recovery detects incomplete transaction and either completes or rolls back deterministically. |

### EXEC-01

| Field | Value |
| --- | --- |
| Recommendation | Formalize a persisted pipeline DAG (stages + deps) for capture→process→index→query, stored in state_tape |
| Rationale | Current pipeline ordering is spread across modules; a DAG makes replay and partial recovery deterministic. |
| Pillar scores (P1/P2/P3/P4=Total) | 2/1/3/3=9 |
| Effort | L |
| Risk | Med |
| Dependencies | None |
| improved | Accuracy, Citeability, Performance |
| risked | Security |
| enforcement_location | autocapture_nx/runtime/conductor.py, autocapture_nx/kernel/state_tape.py, autocapture_nx/kernel/query.py |
| regression_detection | tests/test_pipeline_dag_determinism.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Given same config and inputs, DAG serialization is byte-identical; executing DAG twice produces identical stage ordering and IDs. |

### EXEC-05

| Field | Value |
| --- | --- |
| Recommendation | Eliminate nondeterminism sources (time.now, unordered dict iteration, RNG) from critical pipelines; enforce stable sort everywhere |
| Rationale | Determinism is a primary requirement; this turns it into an enforced contract. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/4/3=9 |
| Effort | M |
| Risk | Med |
| Dependencies | None |
| improved | Accuracy, Citeability |
| risked | Performance, Security |
| enforcement_location | autocapture_nx/kernel/query.py, plugins/builtin/retrieval_basic/*, autocapture_nx/kernel/canonical_json.py |
| regression_detection | tests/test_deterministic_retrieval_order.py; tools/gate_perf.py (ensure not slower); ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Run identical query twice; evidence_id ordering and citation sets are identical; hashes match. |

### EXEC-02

| Field | Value |
| --- | --- |
| Recommendation | Add an idempotent job runner with explicit retry policy (bounded retries + backoff) and attempt records in ledger |
| Rationale | Prevents silent partial failures and makes transient errors diagnosable and auditable. |
| Pillar scores (P1/P2/P3/P4=Total) | 2/1/2/3=8 |
| Effort | M |
| Risk | Med |
| Dependencies | None |
| improved | Citeability, Performance, Accuracy |
| risked | Security |
| enforcement_location | autocapture_nx/runtime/conductor.py, plugins/builtin/ledger_basic/plugin.py |
| regression_detection | tests/test_job_retry_records.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Inject transient failure; job retries deterministically and records attempts; after success, final artifacts match expected hashes. |

### EXEC-03

| Field | Value |
| --- | --- |
| Recommendation | Unify concurrency controls: per-stage semaphores + global CPU/RAM budgets + deterministic scheduling |
| Rationale | Avoids plugin/processing contention and performance cliffs; reduces capture lag spikes. |
| Pillar scores (P1/P2/P3/P4=Total) | 3/1/2/2=8 |
| Effort | M |
| Risk | Med |
| Dependencies | None |
| improved | Performance, Accuracy |
| risked | Citeability, Security |
| enforcement_location | autocapture_nx/runtime/governor.py, autocapture_nx/runtime/scheduler.py, autocapture_nx/capture/pipeline.py |
| regression_detection | tests/test_concurrency_budget_enforced.py; tools/gate_perf.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Stress with concurrent extract+index; capture lag stays within SLO; scheduler never exceeds configured concurrency. |

### EXEC-09

| Field | Value |
| --- | --- |
| Recommendation | Tighten subprocess plugin runtime limits: enforce RPC timeouts, kill-on-timeout, and record termination in audit log |
| Rationale | Prevents hung plugins from blocking pipeline; improves containment. |
| Pillar scores (P1/P2/P3/P4=Total) | 2/3/1/2=8 |
| Effort | M |
| Risk | Med |
| Dependencies | None |
| improved | Security, Performance, Citeability |
| risked | Accuracy |
| enforcement_location | autocapture_nx/plugin_system/host_runner.py, autocapture_nx/kernel/audit.py, autocapture_nx/windows/win_sandbox.py |
| regression_detection | tests/test_plugin_timeout_killed.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Create plugin that sleeps forever; host kills after timeout; audit log contains termination record; kernel continues safely. |

### EXEC-07

| Field | Value |
| --- | --- |
| Recommendation | Make on-query extraction an explicit scheduled job: show blocked reasons and offer “schedule extraction now” |
| Rationale | Avoids user confusion when allow_decode_extract=false; makes completeness measurable and controllable. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/2/3=7 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Citeability, Performance |
| risked | Security |
| enforcement_location | autocapture_nx/kernel/query.py, autocapture_nx/processing/idle.py, autocapture/web/ui/index.html |
| regression_detection | tests/test_schedule_extract_from_query.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Query with missing extraction; UI/CLI indicates blocked and can schedule; after completion, query returns more evidence. |

### EXEC-08

| Field | Value |
| --- | --- |
| Recommendation | Add standardized health checks for each pipeline capability (capture, OCR, VLM, indexing, retrieval, answer) |
| Rationale | Turns silent degradation into detectable component status; improves safe-mode decisions. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/2/2/2=7 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Security, Accuracy, Citeability |
| risked | Performance |
| enforcement_location | autocapture_nx/kernel/doctor.py, autocapture/web/routes/health.py, plugins/builtin/* |
| regression_detection | tests/test_component_health_matrix.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Disable a plugin; health endpoint reports degraded capability with reason; doctor exits non-zero when critical capability missing. |

### EXEC-10

| Field | Value |
| --- | --- |
| Recommendation | Deterministic retrieval tie-breaking: score→evidence_id→span_id ordering, documented as contract |
| Rationale | Prevents flaky answers and inconsistent citations when scores tie. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/0/3/2=6 |
| Effort | S |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Citeability |
| risked | Performance, Security |
| enforcement_location | plugins/builtin/retrieval_basic/plugin.py, contracts/retrieval.schema.json (new) |
| regression_detection | tests/test_retrieval_tie_breaking.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Construct equal-score candidates; retrieval order matches documented tie-breaker deterministically. |


## IV. Extensions

| id | scores | effort | risk | recommendation |
| --- | --- | --- | --- | --- |
| EXT-03 | 1/3/2/3=9 | L | Med | Add update + rollback with lock history and manifest/permission diffs (CLI + UI) |
| EXT-04 | 0/2/3/3=8 | M | Med | Enforce compatibility contracts: plugin declares kernel_api_version + contract_lock_hash; registry refuses mismatches |
| EXT-05 | 1/2/2/3=8 | M | Low | Add `plugins plan/apply` dry-run: compute capability graph, conflicts, and required permissions before applying changes |
| EXT-11 | 0/4/1/3=8 | M | Med | Cryptographically sign plugin_locks.json and approvals with local key; verify before boot |
| EXT-01 | 0/2/2/3=7 | M | Low | Define explicit plugin lifecycle states (installed→locked→approved→enabled→healthy) and enforce transitions |
| EXT-06 | 0/4/1/2=7 | M | Low | Permission UX: require explicit per-plugin filesystem roots + network scopes; show permissions diff on approval |
| EXT-07 | 1/3/1/2=7 | M | Low | Sandbox policy UI: show hosting mode (subprocess/inproc), job limits, and reasons; restrict inproc to allowlist with explicit override |
| EXT-08 | 1/2/2/2=7 | M | Med | Add standardized plugin health checks and heartbeat; surface in UI and disable on repeated failures |
| EXT-02 | 1/2/1/2=6 | M | Med | Add local-only plugin install (`autocapture plugins install <path>`) with manifest validation and lock update preview |
| EXT-10 | 0/2/1/3=6 | L | Med | Add plugin SBOM metadata (dependencies + hashes) to plugin lock entries |
| EXT-12 | 0/1/2/2=5 | S | Low | Implement a plugin “capabilities matrix” page: what provides what, conflicts, and current selection rationale |
| EXT-09 | 0/1/1/2=4 | S | Low | Expose per-plugin logs and last error context (sanitized) in plugin manager |

### EXT-03

| Field | Value |
| --- | --- |
| Recommendation | Add update + rollback with lock history and manifest/permission diffs (CLI + UI) |
| Rationale | Makes plugin changes auditable and reversible; reduces downtime from bad plugin updates. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/3/2/3=9 |
| Effort | L |
| Risk | Med |
| Dependencies | EXT-01 |
| improved | Security, Accuracy, Citeability |
| risked | Performance |
| enforcement_location | autocapture_nx/plugin_system/manager.py, autocapture/web/ui/index.html, config/plugin_locks.json |
| regression_detection | tests/test_plugin_update_rollback.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Update plugin; UI shows diff; rollback restores previous hashes and version; system reboots plugins deterministically. |

### EXT-04

| Field | Value |
| --- | --- |
| Recommendation | Enforce compatibility contracts: plugin declares kernel_api_version + contract_lock_hash; registry refuses mismatches |
| Rationale | Prevents runtime crashes from schema drift and ensures plugins are built for the pinned contract set. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/2/3/3=8 |
| Effort | M |
| Risk | Med |
| Dependencies | None |
| improved | Accuracy, Security, Citeability |
| risked | Performance |
| enforcement_location | contracts/plugin_manifest.schema.json, autocapture_nx/plugin_system/registry.py, contracts/lock.json |
| regression_detection | tests/test_plugin_compatibility_gate.py; tools/gate_contract_pins.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Plugin with mismatched api_version fails to load with deterministic error including expected and actual versions. |

### EXT-05

| Field | Value |
| --- | --- |
| Recommendation | Add `plugins plan/apply` dry-run: compute capability graph, conflicts, and required permissions before applying changes |
| Rationale | Avoids half-applied plugin states and gives operator confidence before toggling. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/2/2/3=8 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Citeability, Security |
| risked | Performance |
| enforcement_location | autocapture_nx/plugin_system/manager.py, autocapture_nx/plugin_system/registry.py |
| regression_detection | tests/test_plugins_plan_output_deterministic.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Plan output is canonical JSON and stable across runs; apply follows plan exactly; ledger records plan hash. |

### EXT-11

| Field | Value |
| --- | --- |
| Recommendation | Cryptographically sign plugin_locks.json and approvals with local key; verify before boot |
| Rationale | Prevents undetected tampering of lock/approval state on disk. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/4/1/3=8 |
| Effort | M |
| Risk | Med |
| Dependencies | None |
| improved | Security, Citeability |
| risked | Performance, Accuracy |
| enforcement_location | autocapture_nx/kernel/keyring.py, autocapture_nx/plugin_system/registry.py, config/plugin_locks.json |
| regression_detection | tests/test_plugin_locks_signature_verified.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Modify lockfile by one byte; boot refuses with clear message; `plugins approve` regenerates valid signature. |

### EXT-01

| Field | Value |
| --- | --- |
| Recommendation | Define explicit plugin lifecycle states (installed→locked→approved→enabled→healthy) and enforce transitions |
| Rationale | Reduces admin footguns where a plugin is hash-approved but misconfigured or unhealthy; makes UX clearer. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/2/2/3=7 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Security, Accuracy, Citeability |
| risked | None |
| enforcement_location | autocapture_nx/plugin_system/manager.py, autocapture_nx/plugin_system/registry.py, autocapture/web/routes/plugins.py |
| regression_detection | tests/test_plugin_lifecycle_state_machine.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Attempt to enable an unapproved plugin; system rejects with actionable message; UI shows correct state. |

### EXT-06

| Field | Value |
| --- | --- |
| Recommendation | Permission UX: require explicit per-plugin filesystem roots + network scopes; show permissions diff on approval |
| Rationale | Reduces accidental over-privilege and improves user understanding of risk. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/4/1/2=7 |
| Effort | M |
| Risk | Low |
| Dependencies | EXT-01 |
| improved | Security, Citeability |
| risked | Performance, Accuracy |
| enforcement_location | autocapture/web/ui/index.html, autocapture/web/routes/plugins.py, autocapture_nx/plugin_system/runtime.py |
| regression_detection | tests/test_plugin_permission_prompt_required.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Approving a plugin shows permission summary and requires typed confirmation for high-risk scopes; refusal leaves plugin disabled. |

### EXT-07

| Field | Value |
| --- | --- |
| Recommendation | Sandbox policy UI: show hosting mode (subprocess/inproc), job limits, and reasons; restrict inproc to allowlist with explicit override |
| Rationale | Makes containment guarantees visible and prevents unsafe runtime changes under fatigue. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/3/1/2=7 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Security, Citeability, Performance |
| risked | Accuracy |
| enforcement_location | config/default.json, autocapture_nx/plugin_system/registry.py, autocapture/web/ui/index.html |
| regression_detection | tests/test_inproc_allowlist_enforced.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Try to enable inproc for non-allowlisted plugin; refused; UI explains; override requires admin flag and is ledger-recorded. |

### EXT-08

| Field | Value |
| --- | --- |
| Recommendation | Add standardized plugin health checks and heartbeat; surface in UI and disable on repeated failures |
| Rationale | Prevents silent pipeline failures from flaky plugins; enables automated containment. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/2/2/2=7 |
| Effort | M |
| Risk | Med |
| Dependencies | EXT-01 |
| improved | Performance, Security, Accuracy, Citeability |
| risked | None |
| enforcement_location | autocapture_nx/plugin_system/host_runner.py, autocapture_nx/kernel/audit.py, autocapture/web/routes/plugins.py |
| regression_detection | tests/test_plugin_crash_loop_quarantine.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Plugin crashes 3 times in 5 min; manager quarantines; UI shows quarantined with rollback option; ledger records. |

### EXT-02

| Field | Value |
| --- | --- |
| Recommendation | Add local-only plugin install (`autocapture plugins install <path>`) with manifest validation and lock update preview |
| Rationale | Current system supports discovery + locks but not explicit install flows; reduces manual file copying mistakes. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/2/1/2=6 |
| Effort | M |
| Risk | Med |
| Dependencies | None |
| improved | Performance, Security, Citeability |
| risked | Accuracy |
| enforcement_location | autocapture_nx/plugin_system/manager.py, contracts/plugin_manifest.schema.json, config/plugin_locks.json |
| regression_detection | tests/test_plugin_install_local_path.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Install plugin from zip/dir; manager validates schema and writes lock preview; no network required; plugin appears in UI. |

### EXT-10

| Field | Value |
| --- | --- |
| Recommendation | Add plugin SBOM metadata (dependencies + hashes) to plugin lock entries |
| Rationale | Improves auditability and supply-chain visibility without requiring network. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/2/1/3=6 |
| Effort | L |
| Risk | Med |
| Dependencies | None |
| improved | Citeability, Security |
| risked | Performance, Accuracy |
| enforcement_location | tools/hypervisor/scripts/update_plugin_locks.py, config/plugin_locks.json |
| regression_detection | tests/test_plugin_lock_contains_sbom.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Lock generation includes dependency list and hash; doctor verifies consistency; changes are diffable. |

### EXT-12

| Field | Value |
| --- | --- |
| Recommendation | Implement a plugin “capabilities matrix” page: what provides what, conflicts, and current selection rationale |
| Rationale | Reduces cognitive load and prevents wrong-plugin selection under fatigue. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/1/2/2=5 |
| Effort | S |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Citeability |
| risked | Performance, Security |
| enforcement_location | autocapture/web/ui/index.html, autocapture_nx/plugin_system/registry.py |
| regression_detection | tests/test_capabilities_matrix_endpoint.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Endpoint returns deterministic matrix; UI renders accessible table; selecting plugin shows which capabilities change. |

### EXT-09

| Field | Value |
| --- | --- |
| Recommendation | Expose per-plugin logs and last error context (sanitized) in plugin manager |
| Rationale | Shortens time-to-diagnose and reduces “operator guessing” changes. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/1/1/2=4 |
| Effort | S |
| Risk | Low |
| Dependencies | None |
| improved | Citeability, Performance |
| risked | Security, Accuracy |
| enforcement_location | autocapture_nx/plugin_system/host_runner.py, autocapture/web/ui/index.html |
| regression_detection | tests/test_plugin_logs_endpoint.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | UI can fetch last N log lines per plugin; logs redact secrets; endpoint requires auth token. |


## V. UI/UX

| id | scores | effort | risk | recommendation |
| --- | --- | --- | --- | --- |
| UX-04 | 1/1/3/3=8 | M | Low | Query UI: show extraction completeness (allowed/blocked/ran), time window coverage, and a citation explorer |
| UX-05 | 1/3/1/3=8 | L | Med | Extension Manager UI v2 (IA + flows): Installed / Available / Updates / Approvals / Health / Policies |
| UX-03 | 0/1/2/4=7 | M | Low | Create a Run/Job Detail view with full provenance: config snapshot, plugin hashes, ledger head, anchors, artifacts |
| UX-01 | 1/1/2/2=6 | M | Low | Add a first-class Activity Dashboard (Today/Recent) showing capture status, last ingest, errors, and SLO summary |
| UX-02 | 1/1/2/2=6 | M | Low | Add an Input Ingest / Capture panel: current data_dir, run_id, active sources, pause/resume, and disk banner |
| UX-06 | 0/4/0/2=6 | S | Low | Make dangerous toggles misclick-resistant (egress enable, allow_raw_egress, allow_images): require typed confirmation + undo window |
| UX-09 | 0/1/2/2=5 | M | Low | Add config presets and a diff viewer (effective vs user overrides) with search and safe defaults |
| UX-08 | 0/1/1/2=4 | S | Low | Standardize error UX: actionable messages, “copy diagnostics”, and “open doctor bundle” on failures |
| UX-07 | 0/1/1/1=3 | M | Low | Accessibility hardening: add ARIA labels, focus order, skip links, and keyboard shortcuts; run automated a11y checks |
| UX-10 | 0/0/1/2=3 | S | Low | Terminology cleanup: unify NX/MX naming in UI + docs; add a single “Core runtime: autocapture_nx” statement |

### UX-04

| Field | Value |
| --- | --- |
| Recommendation | Query UI: show extraction completeness (allowed/blocked/ran), time window coverage, and a citation explorer |
| Rationale | Prevents misunderstanding of results and exposes “modeled vs measured” boundaries. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/3/3=8 |
| Effort | M |
| Risk | Low |
| Dependencies | META-05, META-08 |
| improved | Accuracy, Citeability |
| risked | Performance, Security |
| enforcement_location | autocapture/web/ui/index.html, autocapture/web/routes/query.py, autocapture_nx/kernel/query.py |
| regression_detection | tests/test_query_ui_shows_blocked_extract.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Run a query with allow_decode_extract=false; UI shows blocked_extract with reason and offers schedule job. |

### UX-05

| Field | Value |
| --- | --- |
| Recommendation | Extension Manager UI v2 (IA + flows): Installed / Available / Updates / Approvals / Health / Policies |
| Rationale | Addresses the repo’s current plugin UX gap (no install/update/rollback, limited permission surfacing). |
| Pillar scores (P1/P2/P3/P4=Total) | 1/3/1/3=8 |
| Effort | L |
| Risk | Med |
| Dependencies | EXT-01, EXT-02, EXT-03, EXT-06 |
| improved | Security, Citeability, Performance |
| risked | Accuracy |
| enforcement_location | autocapture/web/ui/index.html, autocapture/web/routes/plugins.py, autocapture_nx/plugin_system/manager.py |
| regression_detection | tests/test_extension_manager_core_flows.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Install→approve→enable→rollback flow works end-to-end from UI with deterministic state and no page reload required. |

### UX-03

| Field | Value |
| --- | --- |
| Recommendation | Create a Run/Job Detail view with full provenance: config snapshot, plugin hashes, ledger head, anchors, artifacts |
| Rationale | Makes audits frictionless and supports Justin’s “prove what ran” requirement. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/1/2/4=7 |
| Effort | M |
| Risk | Low |
| Dependencies | META-01, META-02, META-03 |
| improved | Citeability, Accuracy |
| risked | Performance, Security |
| enforcement_location | autocapture/web/ui/index.html, autocapture/web/routes/metadata.py, autocapture/web/routes/trace.py |
| regression_detection | tests/test_run_detail_contains_provenance.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Open run detail; view shows provenance header and links to config.effective.json and proof bundle export; hashes match. |

### UX-01

| Field | Value |
| --- | --- |
| Recommendation | Add a first-class Activity Dashboard (Today/Recent) showing capture status, last ingest, errors, and SLO summary |
| Rationale | Reduces hunting across tabs; makes system state visible and lowers misconfiguration risk. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/2/2=6 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Citeability, Performance |
| risked | Security |
| enforcement_location | autocapture/web/ui/index.html, autocapture/web/routes/telemetry.py, autocapture/web/routes/health.py |
| regression_detection | tests/test_ui_dashboard_renders.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Dashboard loads with keyboard only; shows last capture time, queue depth, and safe-mode status; no console errors. |

### UX-02

| Field | Value |
| --- | --- |
| Recommendation | Add an Input Ingest / Capture panel: current data_dir, run_id, active sources, pause/resume, and disk banner |
| Rationale | Prevents “capturing the wrong thing” and provides immediate feedback for pause/resume actions. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/2/2=6 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Performance, Citeability |
| risked | Security |
| enforcement_location | autocapture/web/ui/index.html, autocapture/web/routes/run.py |
| regression_detection | tests/test_pause_resume_idempotent.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Pause then resume capture; no duplicated segments; UI shows state transitions and persists across refresh. |

### UX-06

| Field | Value |
| --- | --- |
| Recommendation | Make dangerous toggles misclick-resistant (egress enable, allow_raw_egress, allow_images): require typed confirmation + undo window |
| Rationale | Protects against fatigue errors and aligns with “local-only by default” posture. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/4/0/2=6 |
| Effort | S |
| Risk | Low |
| Dependencies | None |
| improved | Security, Citeability |
| risked | Performance, Accuracy |
| enforcement_location | autocapture/web/ui/index.html, autocapture/web/routes/settings.py, config/default.json |
| regression_detection | tests/test_dangerous_toggle_requires_confirm.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Attempt to enable allow_raw_egress; UI requires typed phrase; config updates atomically; undo within 30s restores prior state. |

### UX-09

| Field | Value |
| --- | --- |
| Recommendation | Add config presets and a diff viewer (effective vs user overrides) with search and safe defaults |
| Rationale | Reduces JSON editing friction and makes configuration changes auditable. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/1/2/2=5 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Citeability |
| risked | Performance, Security |
| enforcement_location | autocapture/web/ui/index.html, autocapture/config/load.py, contracts/config_schema.json |
| regression_detection | tests/test_config_diff_viewer.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Select preset; UI shows diff; applying creates canonical user.json; restart preserves diff; doctor passes. |

### UX-08

| Field | Value |
| --- | --- |
| Recommendation | Standardize error UX: actionable messages, “copy diagnostics”, and “open doctor bundle” on failures |
| Rationale | Improves recovery speed and reduces random config changes. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/1/1/2=4 |
| Effort | S |
| Risk | Low |
| Dependencies | None |
| improved | Citeability, Performance |
| risked | Security, Accuracy |
| enforcement_location | autocapture/web/ui/index.html, autocapture/web/routes/doctor.py |
| regression_detection | tests/test_error_to_diagnostics_flow.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Trigger a controlled error; UI shows error code, remediation steps, and one-click diagnostics bundle download. |

### UX-07

| Field | Value |
| --- | --- |
| Recommendation | Accessibility hardening: add ARIA labels, focus order, skip links, and keyboard shortcuts; run automated a11y checks |
| Rationale | Prevents accessibility regressions and reduces cognitive load under fatigue. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/1/1/1=3 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Citeability |
| risked | Performance, Security |
| enforcement_location | autocapture/web/ui/index.html, autocapture/web/ui/static/* |
| regression_detection | tests/test_accessibility_smoke.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Automated a11y test passes on core screens; manual keyboard nav reaches all controls in logical order. |

### UX-10

| Field | Value |
| --- | --- |
| Recommendation | Terminology cleanup: unify NX/MX naming in UI + docs; add a single “Core runtime: autocapture_nx” statement |
| Rationale | Prevents misunderstanding about what code path is active and what guarantees apply. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/0/1/2=3 |
| Effort | S |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Citeability |
| risked | None |
| enforcement_location | README.md, contracts/user_surface.md, autocapture/web/ui/index.html |
| regression_detection | tests/test_docs_consistency_smoke.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Docs and UI show a single canonical runtime; all command examples map to actual CLI; no dead links in repo docs. |


## VI. Ops

| id | scores | effort | risk | recommendation |
| --- | --- | --- | --- | --- |
| OPS-02 | 2/1/2/3=8 | M | Low | Instrument frictionless workflow metrics: TTFR, query latency, misconfig errors, plugin crashes, blocked ops; expose /metrics + UI |
| OPS-03 | 1/2/1/4=8 | M | Low | Provide a deterministic diagnostics bundle export (zip) with redaction: doctor report, config snapshot, locks, recent logs, telemetry |
| OPS-05 | 1/1/2/3=7 | M | Med | Add operator commands: `reindex`, `vacuum`, `quarantine`, `rollback-locks`, each producing ledgered actions |
| OPS-01 | 1/1/1/3=6 | M | Med | Adopt structured JSONL logging with correlation IDs (run_id, job_id, plugin_id) and log rotation |
| OPS-07 | 1/1/2/2=6 | M | Med | Add a self-test harness runnable from tray: capture 5s, extract 1 segment, query 1 prompt, verify ledger |
| OPS-08 | 1/1/2/2=6 | M | Low | Make SLO/error budget first-class: surface budgets in UI and fail gates when regression exceeds thresholds |
| OPS-04 | 1/1/1/2=5 | S | Low | Expand /health to include component matrix + last error codes, while keeping a stable summary for monitoring |
| OPS-06 | 0/1/2/2=5 | M | Low | Expose migration status (DB versions, last migration timestamp, checksum) in doctor + UI |

### OPS-02

| Field | Value |
| --- | --- |
| Recommendation | Instrument frictionless workflow metrics: TTFR, query latency, misconfig errors, plugin crashes, blocked ops; expose /metrics + UI |
| Rationale | Required measurement for “frictionless core workflow”; turns UX pain into tracked SLOs. |
| Pillar scores (P1/P2/P3/P4=Total) | 2/1/2/3=8 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Performance, Accuracy, Citeability |
| risked | Security |
| enforcement_location | autocapture/telemetry.py, autocapture/web/routes/metrics.py, autocapture_nx/ux/facade.py |
| regression_detection | tests/test_metrics_contains_ttfr.py; tools/gate_perf.py (budget); ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Run with fresh data dir; metrics show ttfr_seconds histogram; UI shows trend; values match measured timestamps. |

### OPS-03

| Field | Value |
| --- | --- |
| Recommendation | Provide a deterministic diagnostics bundle export (zip) with redaction: doctor report, config snapshot, locks, recent logs, telemetry |
| Rationale | Improves supportability without leaking PII; enables reproducible bug reports. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/2/1/4=8 |
| Effort | M |
| Risk | Low |
| Dependencies | META-10 |
| improved | Citeability, Security, Performance |
| risked | Accuracy |
| enforcement_location | autocapture/web/routes/doctor.py, autocapture_nx/kernel/doctor.py, autocapture/web/ui/index.html |
| regression_detection | tests/test_diagnostics_bundle_redacts.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Create bundle; contains manifest + hashes; redacts tokens and PII patterns; bundle verification passes. |

### OPS-05

| Field | Value |
| --- | --- |
| Recommendation | Add operator commands: `reindex`, `vacuum`, `quarantine`, `rollback-locks`, each producing ledgered actions |
| Rationale | Reduces ad-hoc manual interventions and keeps ops actions auditable. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/2/3=7 |
| Effort | M |
| Risk | Med |
| Dependencies | None |
| improved | Citeability, Accuracy, Performance |
| risked | Security |
| enforcement_location | autocapture_nx/cli.py, autocapture_nx/kernel/loader.py, plugins/builtin/ledger_basic/plugin.py |
| regression_detection | tests/test_operator_commands_ledgered.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Run `reindex`; system records action with before/after index hashes; query results unchanged except performance. |

### OPS-01

| Field | Value |
| --- | --- |
| Recommendation | Adopt structured JSONL logging with correlation IDs (run_id, job_id, plugin_id) and log rotation |
| Rationale | Makes troubleshooting deterministic and reduces log spam; supports diagnostics bundles. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/1/3=6 |
| Effort | M |
| Risk | Med |
| Dependencies | None |
| improved | Citeability, Performance, Accuracy |
| risked | Security |
| enforcement_location | autocapture_nx/kernel/logging.py, autocapture/web/api.py, autocapture_nx/plugin_system/host_runner.py |
| regression_detection | tests/test_logs_have_correlation_ids.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Run capture+query; logs include run_id and query_id; log files rotate at configured size without losing last N minutes. |

### OPS-07

| Field | Value |
| --- | --- |
| Recommendation | Add a self-test harness runnable from tray: capture 5s, extract 1 segment, query 1 prompt, verify ledger |
| Rationale | Provides a low-friction go/no-go check after updates. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/2/2=6 |
| Effort | M |
| Risk | Med |
| Dependencies | None |
| improved | Performance, Accuracy, Citeability |
| risked | Security |
| enforcement_location | autocapture/web/routes/doctor.py, autocapture_nx/kernel/query.py, autocapture/pillars/citable.py |
| regression_detection | tests/test_self_test_harness.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Run self-test; produces report with timings and pass/fail; does not require network; cleans up its own test artifacts. |

### OPS-08

| Field | Value |
| --- | --- |
| Recommendation | Make SLO/error budget first-class: surface budgets in UI and fail gates when regression exceeds thresholds |
| Rationale | Prevents gradual decay; ties UX pain to enforceable regression policy. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/2/2=6 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Performance, Accuracy, Citeability |
| risked | Security |
| enforcement_location | autocapture_nx/ux/facade.py, tools/gate_perf.py, autocapture/web/ui/index.html |
| regression_detection | tests/test_slo_budget_regression_gate.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Introduce artificial regression; gate fails; UI shows budget burn; release checklist blocks shipping. |

### OPS-04

| Field | Value |
| --- | --- |
| Recommendation | Expand /health to include component matrix + last error codes, while keeping a stable summary for monitoring |
| Rationale | Improves operational visibility without breaking consumers. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/1/2=5 |
| Effort | S |
| Risk | Low |
| Dependencies | None |
| improved | Performance, Citeability |
| risked | Security, Accuracy |
| enforcement_location | autocapture/web/routes/health.py, autocapture_nx/kernel/doctor.py |
| regression_detection | tests/test_health_has_stable_fields.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Health endpoint always includes status + version; optional details include component states; schema is versioned. |

### OPS-06

| Field | Value |
| --- | --- |
| Recommendation | Expose migration status (DB versions, last migration timestamp, checksum) in doctor + UI |
| Rationale | Prevents hidden drift and simplifies rollback decisions. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/1/2/2=5 |
| Effort | M |
| Risk | Low |
| Dependencies | FND-08 |
| improved | Accuracy, Citeability |
| risked | Performance, Security |
| enforcement_location | autocapture_nx/kernel/doctor.py, autocapture/web/ui/index.html |
| regression_detection | tests/test_doctor_reports_db_versions.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Doctor output includes each DB schema_version; changing DB triggers mismatch detection; remediation steps are provided. |


## VII. Security

| id | scores | effort | risk | recommendation |
| --- | --- | --- | --- | --- |
| SEC-05 | 0/4/2/3=9 | L | High | Add PII detection/redaction at export/egress boundaries using configured recognizers; record redaction map in metadata |
| SEC-04 | 0/4/1/3=8 | M | Med | Default to approval_required=true for any egress, and require explicit per-destination allowlists; ledger every egress event |
| SEC-06 | 1/4/1/2=8 | L | Med | Key rotation hardening: store key_id with every encrypted blob/record; support staged rewrap and verify mixed-key reads |
| SEC-07 | 0/3/1/4=8 | M | Low | Sign proof bundle manifest locally and verify on import/replay; include sha256 for all bundle files |
| SEC-10 | 0/4/1/3=8 | M | Low | Harden cloud/gateway pathways: require explicit privacy.cloud.enabled AND egress approval; block by default and test |
| SEC-01 | 0/4/1/2=7 | M | Med | Harden filesystem_guard path normalization: resolve symlinks, normalize case/UNC, and deny path traversal consistently on Windows |
| SEC-03 | 0/3/1/2=6 | S | Low | Make loopback binding enforceable: validate config + runtime bind address; tray launcher must respect config or refuse to start |
| SEC-08 | 0/3/0/3=6 | M | Low | Make capture consent explicit: persistent tray indicator + start/stop events ledgered; prevent silent background capture |
| SEC-09 | 0/4/0/2=6 | M | Low | Secrets hygiene: enforce sanitize_env for all subprocesses, redact tokens in logs, and add repo-wide secret scanning gate |
| SEC-02 | 0/4/0/1=5 | M | Med | Ensure network_guard is applied early in subprocess plugins (sitecustomize) and covers common HTTP libs |

### SEC-05

| Field | Value |
| --- | --- |
| Recommendation | Add PII detection/redaction at export/egress boundaries using configured recognizers; record redaction map in metadata |
| Rationale | Prevents accidental exposure of sensitive data; improves auditability of what left the system. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/4/2/3=9 |
| Effort | L |
| Risk | High |
| Dependencies | None |
| improved | Security, Citeability, Accuracy |
| risked | Performance |
| enforcement_location | autocapture/privacy/redaction.py, autocapture/egress/sanitize.py, config/default.json |
| regression_detection | tests/test_redaction_deterministic.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Export proof bundle with PII; redaction replaces with deterministic tokens; redaction map stored; verification confirms hashes. |

### SEC-04

| Field | Value |
| --- | --- |
| Recommendation | Default to approval_required=true for any egress, and require explicit per-destination allowlists; ledger every egress event |
| Rationale | Aligns with “local-only by default” and prevents accidental leakage through optional gateway features. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/4/1/3=8 |
| Effort | M |
| Risk | Med |
| Dependencies | None |
| improved | Security, Citeability |
| risked | Performance, Accuracy |
| enforcement_location | config/default.json, autocapture/egress/client.py, autocapture/web/routes/egress.py |
| regression_detection | tests/test_egress_requires_approval_by_default.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Attempt egress without approval; blocked; after approving destination, egress succeeds and ledger contains event with hashes. |

### SEC-06

| Field | Value |
| --- | --- |
| Recommendation | Key rotation hardening: store key_id with every encrypted blob/record; support staged rewrap and verify mixed-key reads |
| Rationale | Prevents data loss during rotation and improves forensic auditability. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/4/1/2=8 |
| Effort | L |
| Risk | Med |
| Dependencies | None |
| improved | Security, Citeability, Performance |
| risked | Accuracy |
| enforcement_location | autocapture/crypto/keyring.py, plugins/builtin/storage_encrypted/plugin.py, autocapture/web/routes/keys.py |
| regression_detection | tests/test_key_rotation_rewrap_plan.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Rotate key; old data readable; new writes use new key_id; optional rewrap migrates deterministically and is resumable. |

### SEC-07

| Field | Value |
| --- | --- |
| Recommendation | Sign proof bundle manifest locally and verify on import/replay; include sha256 for all bundle files |
| Rationale | Protects against tampering and strengthens citeability guarantees of exported artifacts. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/3/1/4=8 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Citeability, Security |
| risked | Performance, Accuracy |
| enforcement_location | autocapture_nx/kernel/proof_bundle.py, autocapture/crypto/dpapi.py |
| regression_detection | tests/test_proof_bundle_signature_verifies.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Modify any bundle file; verification fails with deterministic error; valid bundle verifies and outputs manifest hash. |

### SEC-10

| Field | Value |
| --- | --- |
| Recommendation | Harden cloud/gateway pathways: require explicit privacy.cloud.enabled AND egress approval; block by default and test |
| Rationale | Ensures optional networked features cannot be enabled accidentally through UI toggles or partial config. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/4/1/3=8 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Security, Citeability |
| risked | Performance, Accuracy |
| enforcement_location | autocapture/gateway/router.py, autocapture_nx/kernel/policy_gate.py, tests/test_gateway_policy_block_cloud_default.py |
| regression_detection | tests/test_cloud_enable_requires_two_step.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | With defaults, any cloud call returns 403; enabling requires two-step consent and produces ledgered policy-change events. |

### SEC-01

| Field | Value |
| --- | --- |
| Recommendation | Harden filesystem_guard path normalization: resolve symlinks, normalize case/UNC, and deny path traversal consistently on Windows |
| Rationale | Current guards use absolute() not resolve(); Windows path edge-cases can bypass intended root restrictions. (filesystem_guard uses Path.absolute() roots, not resolve(): autocapture_nx/plugin_system/runtime.py:169-204.) |
| Pillar scores (P1/P2/P3/P4=Total) | 0/4/1/2=7 |
| Effort | M |
| Risk | Med |
| Dependencies | None |
| improved | Security, Citeability |
| risked | Performance, Accuracy |
| enforcement_location | autocapture_nx/plugin_system/runtime.py, autocapture_nx/windows/win_paths.py |
| regression_detection | tests/test_filesystem_guard_windows_edge_cases.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Attempt to open files via symlink/UNC/.. traversal; guard blocks and increments deny counter; allowed paths still work. |

### SEC-03

| Field | Value |
| --- | --- |
| Recommendation | Make loopback binding enforceable: validate config + runtime bind address; tray launcher must respect config or refuse to start |
| Rationale | ops/dev/launch_tray.ps1 currently hardcodes 127.0.0.1:8787; config drift creates confusion and risk. (Dev tray launcher hardcodes 127.0.0.1:8787: ops/dev/launch_tray.ps1:290-318; web defaults: config/default.json:1501-1521.) |
| Pillar scores (P1/P2/P3/P4=Total) | 0/3/1/2=6 |
| Effort | S |
| Risk | Low |
| Dependencies | None |
| improved | Security, Accuracy, Citeability |
| risked | Performance |
| enforcement_location | config/default.json, autocapture/web/api.py, ops/dev/launch_tray.ps1 |
| regression_detection | tests/test_tray_launcher_respects_bind.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Set bind_port to non-default; tray launcher either uses it or errors; web server never binds non-loopback unless allow_remote=true. |

### SEC-08

| Field | Value |
| --- | --- |
| Recommendation | Make capture consent explicit: persistent tray indicator + start/stop events ledgered; prevent silent background capture |
| Rationale | Reduces privacy incidents and provides auditable evidence of when capture was active. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/3/0/3=6 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Security, Citeability |
| risked | Performance, Accuracy |
| enforcement_location | autocapture/tray/app.py, plugins/builtin/ledger_basic/plugin.py, autocapture/web/ui/index.html |
| regression_detection | tests/test_capture_start_stop_ledgered.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Start capture; tray shows indicator; ledger contains start event; stopping capture records stop event and disables capture plugins. |

### SEC-09

| Field | Value |
| --- | --- |
| Recommendation | Secrets hygiene: enforce sanitize_env for all subprocesses, redact tokens in logs, and add repo-wide secret scanning gate |
| Rationale | Prevents accidental leakage into logs or diagnostics bundles. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/4/0/2=6 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Security, Citeability |
| risked | Performance, Accuracy |
| enforcement_location | autocapture_nx/plugin_system/host_runner.py, autocapture_nx/kernel/logging.py, tools/gate_secrets.py (new) |
| regression_detection | tests/test_log_redaction.py; tools/gate_secrets.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Insert fake token into env; logs and diagnostics redact; gate fails if secrets patterns are committed. |

### SEC-02

| Field | Value |
| --- | --- |
| Recommendation | Ensure network_guard is applied early in subprocess plugins (sitecustomize) and covers common HTTP libs |
| Rationale | Prevents plugins from creating sockets before the guard is installed; reduces bypass risk. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/4/0/1=5 |
| Effort | M |
| Risk | Med |
| Dependencies | None |
| improved | Security |
| risked | Performance, Accuracy, Citeability |
| enforcement_location | autocapture_nx/plugin_system/host_runner.py, autocapture_nx/plugin_system/runtime.py |
| regression_detection | tests/test_network_guard_applies_before_imports.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Plugin imports requests and attempts outbound call at import-time; guard blocks deterministically and logs denial. |


## VIII. Performance

| id | scores | effort | risk | recommendation |
| --- | --- | --- | --- | --- |
| PERF-02 | 3/0/2/2=7 | M | Low | Incremental indexing: process only new/changed evidence by ID+hash; avoid full reindex on boot |
| PERF-03 | 3/0/2/2=7 | M | Low | Add caching for expensive derived steps (OCR/VLM/embeddings) keyed by (evidence_hash, extractor_version, config_hash) |
| PERF-04 | 3/1/2/1=7 | L | Med | Complete WSL2 job loop: implement worker response handling + backpressure; avoid polling/scanning directories |
| PERF-05 | 4/0/2/1=7 | L | High | Optional GPU acceleration (RTX 4090): OCR/embeddings via WSL2 worker; gated by config and local-only constraints |
| PERF-01 | 4/0/1/1=6 | M | Med | Batch and pipeline capture encoding/writes to reduce per-frame overhead; measure CPU and I/O per segment |
| PERF-06 | 3/0/1/2=6 | M | Low | Use streaming I/O for proof bundle export and large media reads to reduce peak memory |
| PERF-07 | 1/0/2/2=5 | M | Low | Add performance baselines and regression gates for key flows: boot, capture lag, query latency, proof export |
| PERF-08 | 1/0/1/2=4 | M | Low | Surface resource usage (CPU/RAM/disk) and auto-throttle policies in UI; make them deterministic and configurable |

### PERF-02

| Field | Value |
| --- | --- |
| Recommendation | Incremental indexing: process only new/changed evidence by ID+hash; avoid full reindex on boot |
| Rationale | Prevents startup cliffs and reduces background work; improves responsiveness. |
| Pillar scores (P1/P2/P3/P4=Total) | 3/0/2/2=7 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Performance, Accuracy, Citeability |
| risked | Security |
| enforcement_location | autocapture/indexing/factory.py, autocapture/indexing/lexical_index.py, autocapture/indexing/vector_index.py |
| regression_detection | tests/test_incremental_indexing.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Add 1 new segment; indexing processes only that segment; query results include it; index build time scales with delta. |

### PERF-03

| Field | Value |
| --- | --- |
| Recommendation | Add caching for expensive derived steps (OCR/VLM/embeddings) keyed by (evidence_hash, extractor_version, config_hash) |
| Rationale | Avoids recomputation on replay and reduces idle processing cost. |
| Pillar scores (P1/P2/P3/P4=Total) | 3/0/2/2=7 |
| Effort | M |
| Risk | Low |
| Dependencies | META-07 |
| improved | Performance, Accuracy, Citeability |
| risked | Security |
| enforcement_location | autocapture_nx/processing/*, plugins/builtin/ocr_*, plugins/builtin/embeddings_* |
| regression_detection | tests/test_extractor_cache_keys.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Run extractor twice with same config; second run hits cache and produces identical outputs without reprocessing. |

### PERF-04

| Field | Value |
| --- | --- |
| Recommendation | Complete WSL2 job loop: implement worker response handling + backpressure; avoid polling/scanning directories |
| Rationale | Current WSL2 queue dispatch exists; completing the loop makes GPU offload usable and reliable. |
| Pillar scores (P1/P2/P3/P4=Total) | 3/1/2/1=7 |
| Effort | L |
| Risk | Med |
| Dependencies | None |
| improved | Performance, Accuracy, Security |
| risked | Citeability |
| enforcement_location | autocapture/runtime/wsl2_queue.py, autocapture/runtime/routing.py, autocapture_nx/runtime/conductor.py |
| regression_detection | tests/test_wsl2_job_roundtrip.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Submit gpu_heavy job; WSL2 worker writes response; native side ingests deterministically and records job_id in ledger. |

### PERF-05

| Field | Value |
| --- | --- |
| Recommendation | Optional GPU acceleration (RTX 4090): OCR/embeddings via WSL2 worker; gated by config and local-only constraints |
| Rationale | Leverages target hardware for large workloads while keeping default local/offline behavior. |
| Pillar scores (P1/P2/P3/P4=Total) | 4/0/2/1=7 |
| Effort | L |
| Risk | High |
| Dependencies | PERF-04 |
| improved | Performance, Accuracy |
| risked | Security, Citeability |
| enforcement_location | autocapture/runtime/routing.py, autocapture/runtime/wsl2_queue.py, plugins/builtin/*_gpu |
| regression_detection | tests/test_gpu_offload_flagged.py; tools/gate_perf.py (optional GPU suite); ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | When gpu_heavy.target=wsl2, heavy jobs route to queue; results match CPU outputs within tolerance; no network calls. |

### PERF-01

| Field | Value |
| --- | --- |
| Recommendation | Batch and pipeline capture encoding/writes to reduce per-frame overhead; measure CPU and I/O per segment |
| Rationale | Improves throughput on Windows and reduces capture lag; provides measurable TTFR improvements. |
| Pillar scores (P1/P2/P3/P4=Total) | 4/0/1/1=6 |
| Effort | M |
| Risk | Med |
| Dependencies | None |
| improved | Performance |
| risked | Security, Accuracy, Citeability |
| enforcement_location | plugins/builtin/capture_windows/plugin.py, autocapture_nx/capture/pipeline.py |
| regression_detection | tests/test_capture_throughput_baseline.py; tools/gate_perf.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Capture 60s at fps_target; CPU stays under threshold and lag_p95 improves vs baseline; hashes unchanged. |

### PERF-06

| Field | Value |
| --- | --- |
| Recommendation | Use streaming I/O for proof bundle export and large media reads to reduce peak memory |
| Rationale | Prevents out-of-memory on large datasets; improves export speed. |
| Pillar scores (P1/P2/P3/P4=Total) | 3/0/1/2=6 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Performance, Citeability |
| risked | Security, Accuracy |
| enforcement_location | autocapture_nx/kernel/proof_bundle.py, plugins/builtin/storage_media_basic/plugin.py |
| regression_detection | tests/test_proof_bundle_streaming_memory.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Export bundle of large blobs; peak RSS stays under threshold; output hashes match previous exporter output. |

### PERF-07

| Field | Value |
| --- | --- |
| Recommendation | Add performance baselines and regression gates for key flows: boot, capture lag, query latency, proof export |
| Rationale | Prevents slow creep; aligns with SLO budgeting. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/0/2/2=5 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Performance, Accuracy, Citeability |
| risked | Security |
| enforcement_location | tools/gate_perf.py, autocapture_nx/ux/facade.py |
| regression_detection | tools/gate_perf.py (expanded suite); ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | CI fails if p95 boot/query/capture metrics regress > threshold; baselines stored with version pinning. |

### PERF-08

| Field | Value |
| --- | --- |
| Recommendation | Surface resource usage (CPU/RAM/disk) and auto-throttle policies in UI; make them deterministic and configurable |
| Rationale | Prevents runaway processing on laptops/desktop; makes performance behavior explainable. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/0/1/2=4 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Performance, Citeability |
| risked | Security, Accuracy |
| enforcement_location | autocapture/web/ui/index.html, autocapture_nx/runtime/governor.py |
| regression_detection | tests/test_ui_resource_panel.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Under load, governor reduces concurrency; UI shows reason and target budgets; turning on/off is auditable. |


## IX. QA

| id | scores | effort | risk | recommendation |
| --- | --- | --- | --- | --- |
| QA-01 | 0/1/4/3=8 | M | Low | Add deterministic golden fixtures for query outputs (with model stubs) including citations and provenance |
| QA-02 | 1/1/3/3=8 | L | Med | Add chaos tests for crash recovery: kill during writes, partial segments, interrupted exports; verify deterministic recovery |
| QA-08 | 0/2/1/4=7 | M | Low | Proof-bundle replay verification tests: tamper detection, missing files, and cross-version imports |
| QA-04 | 0/4/0/2=6 | M | Low | Security regression suite for sandbox guards: symlink/UNC traversal, import-time sockets, subprocess env leaks |
| QA-05 | 0/1/3/2=6 | M | Low | Migration tests: forward/backward migrations for each DB with fixture corpora and checksums |
| QA-03 | 1/1/2/1=5 | M | Low | Fuzz config and plugin manifest validation (schema + semantic rules) with corpus-based mutations |
| QA-07 | 2/0/1/1=4 | L | Med | Performance regression harness for Windows: capture 1m, run 5 queries, export proof bundle; track p95 |
| QA-06 | 0/1/1/1=3 | M | Med | UI smoke + accessibility tests executed in CI (headless) for critical screens |

### QA-01

| Field | Value |
| --- | --- |
| Recommendation | Add deterministic golden fixtures for query outputs (with model stubs) including citations and provenance |
| Rationale | Locks down correctness and prevents silent behavior drift. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/1/4/3=8 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Citeability, Security |
| risked | Performance |
| enforcement_location | tests/fixtures/*, tests/test_query_golden.py (new), plugins/builtin/answer_basic/plugin.py |
| regression_detection | tests/test_query_golden.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Run golden test; output JSON matches exactly (excluding timestamps) and includes provenance header and citations. |

### QA-02

| Field | Value |
| --- | --- |
| Recommendation | Add chaos tests for crash recovery: kill during writes, partial segments, interrupted exports; verify deterministic recovery |
| Rationale | Validates the repo’s recovery promises under real-world interruptions. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/3/3=8 |
| Effort | L |
| Risk | Med |
| Dependencies | FND-02, FND-04 |
| improved | Accuracy, Citeability, Performance |
| risked | Security |
| enforcement_location | tests/test_crash_recovery_chaos.py (new), autocapture_nx/kernel/loader.py |
| regression_detection | tests/test_crash_recovery_chaos.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Repeatedly kill process at random points; after recovery, integrity scan passes and no data is lost beyond last in-flight op. |

### QA-08

| Field | Value |
| --- | --- |
| Recommendation | Proof-bundle replay verification tests: tamper detection, missing files, and cross-version imports |
| Rationale | Guarantees citeability and integrity of exports. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/2/1/4=7 |
| Effort | M |
| Risk | Low |
| Dependencies | SEC-07 |
| improved | Citeability, Security |
| risked | Performance, Accuracy |
| enforcement_location | tests/test_proof_bundle_verify.py (expanded), autocapture_nx/kernel/proof_bundle.py |
| regression_detection | tests/test_proof_bundle_verify.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Modify bundle file; verify fails; valid bundle verifies; replay reads and reproduces citations deterministically. |

### QA-04

| Field | Value |
| --- | --- |
| Recommendation | Security regression suite for sandbox guards: symlink/UNC traversal, import-time sockets, subprocess env leaks |
| Rationale | Prevents future bypass regressions. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/4/0/2=6 |
| Effort | M |
| Risk | Low |
| Dependencies | SEC-01, SEC-02, SEC-09 |
| improved | Security, Citeability |
| risked | Performance, Accuracy |
| enforcement_location | tests/test_security_guards.py (new) |
| regression_detection | tests/test_security_guards.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Suite attempts known bypass patterns; all are blocked and produce expected deny counters without breaking allowed operations. |

### QA-05

| Field | Value |
| --- | --- |
| Recommendation | Migration tests: forward/backward migrations for each DB with fixture corpora and checksums |
| Rationale | Ensures upgrades/rollbacks are safe and deterministic. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/1/3/2=6 |
| Effort | M |
| Risk | Low |
| Dependencies | FND-08 |
| improved | Accuracy, Citeability |
| risked | Performance, Security |
| enforcement_location | tests/test_db_migrations.py (expanded) |
| regression_detection | tests/test_db_migrations.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Migrate fixture DB forward then backward; query results and hashes are identical to baseline. |

### QA-03

| Field | Value |
| --- | --- |
| Recommendation | Fuzz config and plugin manifest validation (schema + semantic rules) with corpus-based mutations |
| Rationale | Finds edge cases in validators and reduces operator config-bricking. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/1/2/1=5 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Accuracy, Performance |
| risked | Security, Citeability |
| enforcement_location | autocapture/config/validator.py, contracts/plugin_manifest.schema.json |
| regression_detection | tests/test_config_fuzz.py; tests/test_plugin_manifest_fuzz.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Fuzzer runs for N seeds; no crashes; invalid configs always produce deterministic error codes. |

### QA-07

| Field | Value |
| --- | --- |
| Recommendation | Performance regression harness for Windows: capture 1m, run 5 queries, export proof bundle; track p95 |
| Rationale | Targets the repo’s stated Windows focus and prevents regressions on real constraints. |
| Pillar scores (P1/P2/P3/P4=Total) | 2/0/1/1=4 |
| Effort | L |
| Risk | Med |
| Dependencies | PERF-07 |
| improved | Performance, Accuracy |
| risked | Security, Citeability |
| enforcement_location | tools/gate_perf.py, ops/dev/* |
| regression_detection | tools/gate_perf.py (windows suite); ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | On Windows runner, suite collects p95 metrics; fails if regression; stores baselines with version pinning. |

### QA-06

| Field | Value |
| --- | --- |
| Recommendation | UI smoke + accessibility tests executed in CI (headless) for critical screens |
| Rationale | Guards against front-end breakage and a11y regressions. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/1/1/1=3 |
| Effort | M |
| Risk | Med |
| Dependencies | UX-07 |
| improved | Accuracy, Citeability |
| risked | Performance, Security |
| enforcement_location | tests/test_ui_smoke.py (new) |
| regression_detection | tests/test_ui_smoke.py; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Headless browser loads dashboard/plugin manager/query; no console errors; basic a11y assertions pass. |


## X. Roadmap

| id | scores | effort | risk | recommendation |
| --- | --- | --- | --- | --- |
| RD-03 | 2/4/3/4=13 | L | High | Phase 2 (2026-04-01→2026-05-31): pipeline DAG + replay + signed proof bundles + egress approvals + PII redaction MVP |
| RD-01 | 1/3/2/3=9 | M | Low | Phase 0 (2026-02-06→2026-02-20): ship instance lock, atomic writes, provenance header, and dangerous-toggle protections |
| RD-04 | 4/1/2/2=9 | L | High | Phase 3 (2026-06-01→2026-07-31): WSL2 worker round-trip + optional GPU acceleration + incremental indexing/caching |
| RD-02 | 2/2/2/2=8 | L | Med | Phase 1 (2026-02-21→2026-03-31): plugin manager v2 core flows + config presets + metrics TTFR/query p95 |
| RD-05 | 1/2/2/3=8 | M | Low | Adopt a “regression = do not ship” gate set: integrity scan, contract pins, plugin locks, SLO budgets, UI smoke |
| RD-06 | 0/2/1/2=5 | S | Low | Write an operator runbook: backup/restore, safe-mode triage, plugin rollback, disk pressure, and integrity verification |

### RD-03

| Field | Value |
| --- | --- |
| Recommendation | Phase 2 (2026-04-01→2026-05-31): pipeline DAG + replay + signed proof bundles + egress approvals + PII redaction MVP |
| Rationale | Turns the system into a verifiable, replayable engine with hardened export and privacy controls. |
| Pillar scores (P1/P2/P3/P4=Total) | 2/4/3/4=13 |
| Effort | L |
| Risk | High |
| Dependencies | EXEC-01, EXEC-04, SEC-07, SEC-04, SEC-05 |
| improved | Security, Accuracy, Citeability, Performance |
| risked | None |
| enforcement_location | (planning) |
| regression_detection | Integrity scan + proof-bundle verify gates; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Replay works; proof bundles are signed and tamper-evident; egress requires approvals; redaction deterministic. |

### RD-01

| Field | Value |
| --- | --- |
| Recommendation | Phase 0 (2026-02-06→2026-02-20): ship instance lock, atomic writes, provenance header, and dangerous-toggle protections |
| Rationale | Immediate stability + auditability wins with low disruption; sets regression guards early. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/3/2/3=9 |
| Effort | M |
| Risk | Low |
| Dependencies | FND-01, FND-02, META-03, UX-06 |
| improved | Security, Accuracy, Citeability, Performance |
| risked | None |
| enforcement_location | (planning) |
| regression_detection | Release checklist + CI gates; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | All Phase 0 items land with tests; any regression => DO_NOT_SHIP; doctor + self-test pass on Windows 11. |

### RD-04

| Field | Value |
| --- | --- |
| Recommendation | Phase 3 (2026-06-01→2026-07-31): WSL2 worker round-trip + optional GPU acceleration + incremental indexing/caching |
| Rationale | Leverages RTX 4090/WSL2 for large workloads while keeping local-only default constraints. |
| Pillar scores (P1/P2/P3/P4=Total) | 4/1/2/2=9 |
| Effort | L |
| Risk | High |
| Dependencies | PERF-04, PERF-05, PERF-02, PERF-03 |
| improved | Performance, Accuracy, Citeability |
| risked | Security |
| enforcement_location | (planning) |
| regression_detection | Perf gates + determinism golden tests; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | GPU-offload is behind flags; when enabled, perf improves without changing outputs beyond tolerance; determinism tests pass. |

### RD-02

| Field | Value |
| --- | --- |
| Recommendation | Phase 1 (2026-02-21→2026-03-31): plugin manager v2 core flows + config presets + metrics TTFR/query p95 |
| Rationale | Reduces operator/user friction while cementing measurement for subsequent performance work. |
| Pillar scores (P1/P2/P3/P4=Total) | 2/2/2/2=8 |
| Effort | L |
| Risk | Med |
| Dependencies | UX-05, UX-09, OPS-02, EXT-02, EXT-03 |
| improved | Performance, Security, Accuracy, Citeability |
| risked | None |
| enforcement_location | (planning) |
| regression_detection | CI UI smoke + metrics gates; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Extension install/rollback works; metrics present; UI smoke passes; SLO summary stable. |

### RD-05

| Field | Value |
| --- | --- |
| Recommendation | Adopt a “regression = do not ship” gate set: integrity scan, contract pins, plugin locks, SLO budgets, UI smoke |
| Rationale | Operationalizes the 4 pillars as release policy, not documentation. |
| Pillar scores (P1/P2/P3/P4=Total) | 1/2/2/3=8 |
| Effort | M |
| Risk | Low |
| Dependencies | None |
| improved | Performance, Security, Accuracy, Citeability |
| risked | None |
| enforcement_location | tools/gate_*, tests/* |
| regression_detection | CI pipeline; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | CI fails if any gate fails; release checklist requires passing artifact bundles (doctor+diagnostics) for each build. |

### RD-06

| Field | Value |
| --- | --- |
| Recommendation | Write an operator runbook: backup/restore, safe-mode triage, plugin rollback, disk pressure, and integrity verification |
| Rationale | Reduces recovery time and prevents unsafe manual interventions. |
| Pillar scores (P1/P2/P3/P4=Total) | 0/2/1/2=5 |
| Effort | S |
| Risk | Low |
| Dependencies | None |
| improved | Security, Accuracy, Citeability |
| risked | None |
| enforcement_location | docs/runbook.md (new), docs/safe_mode.md |
| regression_detection | docs lint + link checker; ANY_REGRESS=>DO_NOT_SHIP |
| Acceptance test | Runbook covers all operator commands; each procedure references exact CLI commands and expected outputs; kept in CI. |


# Top lists

## Top-20 quick wins (Effort S/M, highest total)

| id | bucket | scores | effort | risk | recommendation |
| --- | --- | --- | --- | --- | --- |
| FND-03 | I. Foundation | 2/2/2/4=10 | M | Low | Add `autocapture integrity scan` to verify ledger chain, anchors, blob hashes, and metadata references |
| META-06 | II. Metadata | 0/3/2/4=9 | M | Low | Persist full policy snapshots (privacy + plugin permissions + egress settings) by hash, and include in ledger + proof bundle |
| META-01 | II. Metadata | 1/1/3/4=9 | M | Low | Persist a canonical effective-config snapshot per run (config.effective.json + sha256) and link it from run_manifest |
| FND-01 | I. Foundation | 1/3/2/3=9 | S | Low | Add an exclusive instance lock for (config_dir, data_dir) to prevent concurrent writers |
| RD-01 | X. Roadmap | 1/3/2/3=9 | M | Low | Phase 0 (2026-02-06→2026-02-20): ship instance lock, atomic writes, provenance header, and dangerous-toggle protections |
| EXEC-05 | III. Execution | 1/1/4/3=9 | M | Med | Eliminate nondeterminism sources (time.now, unordered dict iteration, RNG) from critical pipelines; enforce stable sort everywhere |
| FND-05 | I. Foundation | 2/1/3/3=9 | M | Med | Introduce content-addressed ingest IDs for file-based inputs (sha256→input_id) and dedupe at ingest boundary |
| SEC-07 | VII. Security | 0/3/1/4=8 | M | Low | Sign proof bundle manifest locally and verify on import/replay; include sha256 for all bundle files |
| META-02 | II. Metadata | 0/2/2/4=8 | M | Low | Capture plugin provenance: store (plugin_id, version, manifest_sha256, artifact_sha256, permissions) for every loaded plugin in run_manifest |
| OPS-03 | VI. Ops | 1/2/1/4=8 | M | Low | Provide a deterministic diagnostics bundle export (zip) with redaction: doctor report, config snapshot, locks, recent logs, telemetry |
| META-05 | II. Metadata | 0/1/3/4=8 | M | Low | Normalize citation addressing: require citations to reference (evidence_id, span_id, start/end offsets or time range) + stable locator |
| META-09 | II. Metadata | 0/1/3/4=8 | M | Low | Record determinism inputs explicitly: RNG seeds, locale/TZ, model versions, and any sampling parameters used |
| FND-04 | I. Foundation | 1/1/2/4=8 | M | Low | Record run-recovery actions as first-class journal/ledger events (quarantine, seal, replay) with before/after hashes |
| EXT-11 | IV. Extensions | 0/4/1/3=8 | M | Med | Cryptographically sign plugin_locks.json and approvals with local key; verify before boot |
| SEC-04 | VII. Security | 0/4/1/3=8 | M | Med | Default to approval_required=true for any egress, and require explicit per-destination allowlists; ledger every egress event |
| SEC-10 | VII. Security | 0/4/1/3=8 | M | Low | Harden cloud/gateway pathways: require explicit privacy.cloud.enabled AND egress approval; block by default and test |
| EXT-04 | IV. Extensions | 0/2/3/3=8 | M | Med | Enforce compatibility contracts: plugin declares kernel_api_version + contract_lock_hash; registry refuses mismatches |
| EXT-05 | IV. Extensions | 1/2/2/3=8 | M | Low | Add `plugins plan/apply` dry-run: compute capability graph, conflicts, and required permissions before applying changes |
| FND-02 | I. Foundation | 1/2/2/3=8 | M | Low | Centralize atomic-write (temp+fsync+rename) for all JSON/NDJSON state writes (config, run_state, approvals, audit) |
| RD-05 | X. Roadmap | 1/2/2/3=8 | M | Low | Adopt a “regression = do not ship” gate set: integrity scan, contract pins, plugin locks, SLO budgets, UI smoke |

## Top-20 big bets (highest total regardless of effort)

| id | bucket | scores | effort | risk | recommendation |
| --- | --- | --- | --- | --- | --- |
| RD-03 | X. Roadmap | 2/4/3/4=13 | L | High | Phase 2 (2026-04-01→2026-05-31): pipeline DAG + replay + signed proof bundles + egress approvals + PII redaction MVP |
| EXEC-06 | III. Execution | 1/2/3/4=10 | L | High | Introduce staged multi-store writes for evidence: write blob→write metadata→append journal→append ledger, with rollback markers |
| FND-03 | I. Foundation | 2/2/2/4=10 | M | Low | Add `autocapture integrity scan` to verify ledger chain, anchors, blob hashes, and metadata references |
| EXEC-04 | III. Execution | 2/1/3/4=10 | L | Med | Implement `autocapture replay` to re-run processing/indexing on an existing dataset without mutating original artifacts |
| META-07 | II. Metadata | 2/1/3/4=10 | L | Med | Introduce a content-addressed artifact manifest for all derived artifacts (OCR text, embeddings, indexes) with lineage pointers |
| META-06 | II. Metadata | 0/3/2/4=9 | M | Low | Persist full policy snapshots (privacy + plugin permissions + egress settings) by hash, and include in ledger + proof bundle |
| META-01 | II. Metadata | 1/1/3/4=9 | M | Low | Persist a canonical effective-config snapshot per run (config.effective.json + sha256) and link it from run_manifest |
| SEC-05 | VII. Security | 0/4/2/3=9 | L | High | Add PII detection/redaction at export/egress boundaries using configured recognizers; record redaction map in metadata |
| EXT-03 | IV. Extensions | 1/3/2/3=9 | L | Med | Add update + rollback with lock history and manifest/permission diffs (CLI + UI) |
| FND-01 | I. Foundation | 1/3/2/3=9 | S | Low | Add an exclusive instance lock for (config_dir, data_dir) to prevent concurrent writers |
| RD-01 | X. Roadmap | 1/3/2/3=9 | M | Low | Phase 0 (2026-02-06→2026-02-20): ship instance lock, atomic writes, provenance header, and dangerous-toggle protections |
| FND-08 | I. Foundation | 1/2/3/3=9 | L | Med | Add explicit DB migration framework with version pinning + rollback plan for all sqlite/state stores |
| EXEC-05 | III. Execution | 1/1/4/3=9 | M | Med | Eliminate nondeterminism sources (time.now, unordered dict iteration, RNG) from critical pipelines; enforce stable sort everywhere |
| EXEC-01 | III. Execution | 2/1/3/3=9 | L | Med | Formalize a persisted pipeline DAG (stages + deps) for capture→process→index→query, stored in state_tape |
| FND-05 | I. Foundation | 2/1/3/3=9 | M | Med | Introduce content-addressed ingest IDs for file-based inputs (sha256→input_id) and dedupe at ingest boundary |
| RD-04 | X. Roadmap | 4/1/2/2=9 | L | High | Phase 3 (2026-06-01→2026-07-31): WSL2 worker round-trip + optional GPU acceleration + incremental indexing/caching |
| SEC-07 | VII. Security | 0/3/1/4=8 | M | Low | Sign proof bundle manifest locally and verify on import/replay; include sha256 for all bundle files |
| META-02 | II. Metadata | 0/2/2/4=8 | M | Low | Capture plugin provenance: store (plugin_id, version, manifest_sha256, artifact_sha256, permissions) for every loaded plugin in run_manifest |
| OPS-03 | VI. Ops | 1/2/1/4=8 | M | Low | Provide a deterministic diagnostics bundle export (zip) with redaction: doctor report, config snapshot, locks, recent logs, telemetry |
| META-05 | II. Metadata | 0/1/3/4=8 | M | Low | Normalize citation addressing: require citations to reference (evidence_id, span_id, start/end offsets or time range) + stable locator |

# Special focus areas

## 1) Frictionless core workflow metrics (MEASURED)

- **Time-to-first-result (TTFR):** seconds from `run` start → first persisted segment + ledger event.
- **Capture lag p95:** already surfaced in SLO summary; extend to include per-source lag and disk-pressure pauses. (autocapture_nx/ux/facade.py:22-74)
- **Query latency p95:** end-to-end from request accepted → answer returned (split into retrieval vs answer).
- **Misconfiguration rate:** count of config validation errors per boot, and “config changed after error” loops.
- **Plugin crash rate:** crashes per plugin_id per hour; quarantine triggers.
- **Blocked-ops counters:** filesystem_guard denials, network_guard denials, blocked_extract count.
- **Coverage/completeness:** % of query time window backed by extracted spans; missing_spans_count.
- **Retries:** job retry counts and final outcomes.

Instrumentation locations (initial): autocapture/telemetry.py, autocapture_nx/ux/facade.py, autocapture/web/routes/metrics.py, autocapture_nx/kernel/query.py. (autocapture/web/routes/metrics.py:1-62; autocapture_nx/kernel/query.py:644-706)

## 2) Proving “processing happened against THIS input + THIS config”

- **Input identity:** evidence_id + blob sha256 + capture timestamps + source.
- **Config identity:** config_hash + embedded config.effective.json sha256.
- **Contract identity:** contract_lock_hash + schema_version(s).
- **Plugin identity:** plugin_lock_hash + per-plugin (manifest_sha256, artifact_sha256, permissions).
- **Execution identity:** run_id + query_id + stage/job IDs + deterministic ordering contract.
- **Provenance:** ledger_head_hash + anchor_ref + (optional) policy_snapshot_hash.
- **Outputs:** artifact sha256s + lineage pointers to inputs/config/plugin versions.
- **Verification:** integrity scan + proof-bundle signature verification.

Repo already records substantial pieces (ledger/journal/run_manifest). Key gap is surfacing and snapshotting (META-01/META-03). (autocapture_nx/kernel/loader.py:856-934; autocapture_nx/kernel/query.py:644-706)

## 3) Extension manager redesign (spec)

### Minimal viable spec (v2)
**IA:** Installed · Available (local paths) · Updates · Approvals · Health · Policies.

**Install (local-only):** select path/zip → validate manifest schema → compute hashes → show permissions → lock preview → approval → enable.

**Update:** detect new local version → diff (manifest/permissions/hashes) → apply atomically → self-test → rollback on fail.

**Rollback:** lock history (N=20) + rollback button; ledger records before/after hashes.

**Compatibility:** enforce kernel_api_version + contract_lock_hash (EXT-04).

**Sandboxing:** show hosting mode + job limits; inproc only for allowlisted IDs. (config/default.json:963-1008)

**Permissions:** filesystem roots + network scopes (default none). (contracts/plugin_manifest.schema.json:65-128)

**Health:** plugin self-test/heartbeat + crash-loop quarantine.

### Stretch goals
Signed plugins (publisher signatures), SBOM ingestion, reproducible plugin builds, and an offline local catalog.

## 4) Surfacing metadata (UX elements)

- **Provenance header chip:** run_id · query_id · config_hash · plugin_lock_hash · ledger_head · anchor status.
- **Coverage bar:** % of window covered by extracted spans; missing segments count.
- **Determinism badge:** deterministic ordering + seed.
- **Sampling/completeness:** show sample rate + rationale (MEASURED vs MODELED).
- **Pipeline timeline:** stage status with durations/retries/artifacts.
- **Confidence + evidence:** confidence per claim + citations; missing citations flagged.
- **Error cards:** error code + subsystem + one-click diagnostics export.

# Minimal canonical metadata schema proposal

Schema name: `acp.metadata.v1`

## Fields

| field | type | required | description |
| --- | --- | --- | --- |
| schema_version | string | yes | Schema identifier, e.g. '1.0'. |
| run.run_id | string | yes | Run identifier. |
| run.start_ts_utc | string (RFC3339) | yes | Run start time in UTC. |
| run.end_ts_utc | string (RFC3339) | no | Run end time in UTC. |
| run.config_hash | string (sha256) | yes | Hash of effective config. |
| run.config_snapshot_sha256 | string (sha256) | yes | Hash of config.effective.json stored with run. |
| run.contract_lock_hash | string (sha256) | yes | Hash of contracts/lock.json. |
| run.plugin_lock_hash | string (sha256) | yes | Hash of config/plugin_locks.json. |
| run.determinism | object | yes | TZ/locale + RNG seeds + any sampling params. |
| environment.os | string | yes | e.g. 'Windows-11-10.0.22631'. |
| environment.python | string | yes | Python version. |
| inputs[] | array<object> | yes | Each input (captured segment/file) with hashes and source metadata. |
| stages[] | array<object> | yes | Pipeline stages/jobs with timings, retries, status, artifacts. |
| provenance.ledger_head_hash | string | yes | Hash of last ledger entry at time of export/query. |
| provenance.anchor_ref | object | no | Anchor record pointer (type, ts, id/hash). |
| artifacts[] | array<object> | yes | Produced artifacts with sha256 + lineage pointers. |
| citations[] | array<object> | no | Citation spans used in answers. |
| evaluation | object | no | Coverage/quality metrics, pass/fail checks. |
| security.policy_snapshot_hash | string | yes | Hash of policy snapshot used for run/query. |
| security.egress_events[] | array<object> | no | If enabled, each egress decision with destination and redaction proof. |

## Example (truncated)

```json
{
  "schema_version": "1.0",
  "run": {
    "run_id": "run_2026-02-06T21-39-38Z_abcd1234",
    "start_ts_utc": "2026-02-06T21:39:38Z",
    "config_hash": "sha256:\u2026",
    "config_snapshot_sha256": "sha256:\u2026",
    "contract_lock_hash": "sha256:\u2026",
    "plugin_lock_hash": "sha256:\u2026",
    "determinism": {
      "tz": "America/Denver",
      "locale": "C.UTF-8",
      "rng_seed": "123456789",
      "sampling": {
        "enabled": false
      }
    }
  },
  "inputs": [
    {
      "evidence_id": "ev_\u2026",
      "kind": "capture.segment",
      "blob_sha256": "sha256:\u2026",
      "ts_start_utc": "\u2026",
      "ts_end_utc": "\u2026"
    }
  ],
  "stages": [
    {
      "stage_id": "stage.capture",
      "status": "ok",
      "start_ts_utc": "\u2026",
      "end_ts_utc": "\u2026",
      "artifacts": [
        "blob:\u2026"
      ]
    },
    {
      "stage_id": "stage.ocr",
      "status": "ok",
      "retries": 0,
      "artifacts": [
        "derived:\u2026"
      ],
      "derived_from": [
        "ev_\u2026",
        "config:\u2026"
      ]
    }
  ],
  "provenance": {
    "ledger_head_hash": "\u2026",
    "anchor_ref": {
      "type": "dpapi_hmac",
      "ts_utc": "\u2026",
      "hash": "\u2026"
    }
  },
  "artifacts": [
    {
      "artifact_id": "derived:ocr:\u2026",
      "mime": "text/plain",
      "sha256": "\u2026",
      "derived_from": [
        "ev_\u2026",
        "stage.ocr",
        "config:\u2026"
      ]
    }
  ],
  "evaluation": {
    "coverage_ratio": 0.92,
    "missing_spans_count": 3
  },
  "security": {
    "policy_snapshot_hash": "\u2026"
  }
}
```

# Minimal processing lineage model

Track immutable evidence and derived artifacts as a DAG:

```
Input (capture segment/blob)
  └─ evidence_record (id, sha256, timestamps, source)
       ├─ transform: decode → frames/audio chunks (derived_record)
       │     └─ transform: OCR/VLM → text spans (derived_record)
       │           └─ transform: embeddings/index → index artifacts
       └─ query stage → retrieval set → answer
             └─ citations → evidence spans + derived spans
```

Each transform/job writes: artifact(sha256), derived_record(lineage), and a ledger event.

Repo already has primitives for this; the redesign standardizes IDs and makes lineage explicit and user-visible. (autocapture_nx/kernel/proof_bundle.py:130-220; plugins/builtin/ledger_basic/plugin.py:60-156)

# UI/UX sketches (ASCII)

## Home / Activity Dashboard

```
+----------------------------------------------------------------------------------+
| Autocapture Prime — Activity (Today)        [Safe Mode: OFF]  [Egress: OFF]       |
+----------------------------------------------------------------------------------+
| Capture:  RUNNING  | Last segment: 14:38:12  | Lag p95: 1.2s | Disk: 812GB free   |
| Processing: IDLE   | Queue depth p95: 3      | OCR: OK       | VLM: OK           |
| Query p95: 420ms   | Errors (24h): 0         | Integrity: PASS (14:30)            |
+----------------------------------------------------------------------------------+
| Recent Activity                                                             [↻] |
| 14:39  query.execute   “what did I do…”      ok   coverage 92%  blocked_extract  |
| 14:38  capture.segment  seg_…                 ok   size 12MB                      |
| 14:35  plugin.crash     builtin.ocr.tesseract quarantined                         |
+----------------------------------------------------------------------------------+
| [Run Self-Test]  [Export Diagnostics Bundle]  [Export Proof Bundle]              |
+----------------------------------------------------------------------------------+
```

## Input ingest / status panel

```
+------------------ Input / Capture ------------------+
| data_dir:   D:\acp\data                              |
| run_id:     run_2026-02-06T21-39-38Z_abcd1234        |
| sources:    screen(2fps), audio(on), input_events(on)|
| state:      RUNNING                                  |
| disk guard: OK (min_free=20GB)                        |
| [Pause Capture] [Resume] [Open data_dir] [Copy Provenance] |
+-----------------------------------------------------+
```

## Extension manager main screen

```
+-------------------------- Extensions --------------------------+
| Tabs: [Installed] [Available] [Updates] [Approvals] [Health]   |
+----------------------------------------------------------------+
| Installed                                                      |
|  ✓ builtin.capture.windows     v1.0.0  subprocess  perms: fs(app) |
|  ✓ builtin.storage.encrypted   v1.0.0  inproc? NO   perms: fs(data) |
|  ! thirdparty.cool_plugin      v2.1.0  subprocess  perms: fs(*)  net(*)  [QUARANTINED]
|                                                                |
| Selected: thirdparty.cool_plugin                               |
|  - Hashes: manifest_sha256=…  artifact_sha256=…                |
|  - Compatibility: kernel_api=1.0  contract_lock=OK             |
|  - Permissions (diff vs current):                              |
|      filesystem: +C:\Users\Justin\Documents (NEW)              |
|      network:    +egress.gateway:443 (NEW)                     |
|  [Approve…] [Enable] [Rollback] [Run self-test]                |
+----------------------------------------------------------------+
```

## Run/job detail view (metadata + provenance + execution)

```
+------------------------------ Run Detail ------------------------------+
| run_id: run_…  start: 14:35  tz: America/Denver   safe_mode: OFF        |
| Provenance: config_hash=…  plugin_lock=…  contract_lock=…               |
| Ledger: head=…  anchor: dpapi_hmac@14:36 hash=…                          |
+------------------------------------------------------------------------+
| Stages (DAG)                                                            |
|  capture      OK  14:35→14:35  artifacts: seg_… (sha256…)                |
|  ocr          OK  14:35→14:36  artifacts: ocr_text_… (sha256…)           |
|  indexing     OK  14:36→14:37  artifacts: lexical.db (sha256…)          |
+------------------------------------------------------------------------+
| Artifacts                                                               |
|  - config.effective.json (sha256…) [download]                           |
|  - proof_bundle_run_…zip (sha256…) [export]                              |
|  - diagnostics_bundle_…zip (sha256…) [export]                            |
+------------------------------------------------------------------------+
```

# Open questions (non-blocking)

| # | Question |
| --- | --- |
| 1 | Is there a formal definition of the ‘kernel API version’ for plugins today, beyond contract schemas and plugin manifest fields? |
| 2 | What is the authoritative location/format of the effective config hash (is it sha256 over canonical JSON of the merged config)? |
| 3 | Are there any intended remote/multi-tenant use cases, or is allow_remote purely for localhost reverse-proxy scenarios (no evidence)? |
| 4 | What is the expected durability level for anchors (fsync currently absent in anchor writer)? |
| 5 | Is the WSL2 worker side implemented in this repo, or expected to be external (no evidence of a worker in snapshot)? |
| 6 | Are OCR/VLM components deterministic by design, or is approximate determinism acceptable with recorded model versions? |
| 7 | Should proof bundles be importable/replayable by a separate tool in this repo, or only verified (no evidence of an importer)? |
| 8 | What retention policy is intended when `no_deletion_mode=true` causes disk pressure (is auto-pausing the preferred behavior)? |
| 9 | Is there a desired policy for handling DPAPI failures (fail closed vs plaintext anchor records)? |
| 10 | Do we treat UI localStorage settings (e.g., privacy toggles) as authoritative, or must all settings be in config files? |
| 11 | What is the expected support window for contract lock versions and migrations? |
| 12 | Should plugin approvals be per-plugin/per-version (recommended) or global hashes as today? |

## DETERMINISM

- VERIFIED
- Scope: deterministic scoring/tables computed from this snapshot; repo runtime behavior not executed (no evidence).

## TS

- 2026-02-06T14:39:38-07:00


---

FOOTER_REPEAT — THREAD=PROJECT_AUTOCAPTURE_PRIME · CHAT_ID=UNKNOWN · TS=2026-02-06T14:39:38-07:00
