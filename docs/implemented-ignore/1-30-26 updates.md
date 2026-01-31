## Assumptions (max 10)

1. Single user, single machine (Windows 11 x64; 64 GB RAM; RTX 4090).
2. Strictly localhost: UI/API never exposed beyond `127.0.0.1`.
3. Capture policy is “raw-first”: **no masking/filtering/deletion locally**; media stored indefinitely.
4. Screen capture is **change-driven**: any visible change (even clock minute tick) must result in a new stored media artifact (hash differs ⇒ saved; hash identical ⇒ skip).
5. Capture is enabled during HID/user activity; capture must remain reliable under distraction/fatigue/mis-clicks.
6. While the user is active, **only kernel + capture pipeline** may run; all other processing must pause.
7. When idle, GPU may saturate; **CPU and RAM must never exceed 50%** usage (hard constraint).
8. Cloud is optional and **only via explicit egress/export** with sanitization; user can view everything when decrypted locally.
9. Primary interaction is **natural-language Q&A** with citations and a “What happened today” flow.
10. Plugin-first architecture remains: plugins are first-class and can override core behavior.

---

## Repo findings (evidence this is grounded in your codebase)

* Capture config already exposes knobs for `diff_epsilon`, `duplicate_threshold`, FPS bounds, `always_store_fullres`, `record_video`, encoder selection (`nvenc_webp`, `nvenc_avif`, etc.), queue backpressure (`max_pending`), and disk guards (`staging_min_free_mb`, `data_min_free_mb`).
* Capture orchestrator already has ROI enqueue backpressure and records `captures_skipped_backpressure_total` and `roi_queue_depth` (good foundation for “provable pipeline ran / didn’t run”).
* Metrics already exist for capture outcomes and resource reporting: `captures_taken_total`, `captures_dropped_total`, `captures_skipped_*`, plus `process_cpu_percent`, `process_rss_mb`, and GPU gauges.
* Plugin system already supports discovery sources (built-in / directory / Python entrypoints), enable/disable/lock, safe mode, and a policy gate concept.
* Policy gate implementation exists and enumerates permission categories (e.g., `allow_openai`, `allow_network`, `allow_shell`, `allow_filesystem`) with deny-by-default patterns you can tighten for localhost-only. 
* Web UI is a tabbed single-page script with an “unlock” token in URL params and a plugin panel that shows manifest/code SHA256 and approval actions (good, but UX/IA is currently too fragile for your use case).
* There are destructive endpoints and UI/tray paths for deletion (`/api/delete_range`, `/api/delete_all`) which conflict with your “indefinite retention / no deletion” requirement.
* MediaStore supports encrypted media files (e.g., `.acenc`) and performs staging cleanup on failure (strong baseline for crash safety).
* Processing lineage already threads through `frame_hash` into embedding payloads and stores `FrameRecord.frame_hash` and `ArtifactRecord.derived_from` (you’re close to “provable processing against captured metadata”).

---

# D) Red-team failure scenarios (defensive)

## A) Red-team as a User (≥10): real-life failure modes

Each scenario includes **Detection signals** and **Mitigation**.

1. **Accidental pause / silent pause**

   * Detection: `last_capture_age` grows while HID active; `captures_taken_total` flat; UI shows “Paused”.
   * Mitigation: tray + UI show persistent red banner; require long-press confirm to pause; auto-remind every N minutes (no auto-resume without explicit opt-in). (Recs V-6, VI-6)

2. **Fullscreen app causes capture gaps**

   * Detection: “fullscreen paused” reason events; capture gaps coincide with fullscreen transitions.
   * Mitigation: default `block_fullscreen=False` in your “Memory Replacement (Raw)” preset; if user toggles pause, record explicit “policy pause” event with reason. (Recs I-3, II-2)

3. **User assumes processing ran, but it’s paused due to activity**

   * Detection: pipeline state “Paused (User active)”; processing lag counters.
   * Mitigation: “Proof chips” per answer: Captured ✅ / OCR ⏸ / Embed ⏸ with timestamps; “Run now (idle-only)” button that waits for idle transition rather than running immediately. (Recs V-8, III-3)

4. **Mis-click disables a plugin and breaks recall**

   * Detection: plugin disable action in audit log; sudden drop in derived artifacts.
   * Mitigation: “Undo” for plugin toggles; “safe revert” if recall quality drops (heuristic). (Recs IV-7, V-5)

5. **Storage fills; capture halts; user doesn’t notice**

   * Detection: disk watermark triggers; `disk_low_total` increments; capture stops. (Disk guards already exist in config)
   * Mitigation: hard-stop with explicit “CAPTURE HALTED: DISK LOW” + tray notification; provide “migrate to external drive” wizard. (Recs I-5, I-4)

6. **Confusion between raw vs sanitized views**

   * Detection: user is in “sanitized” view; redactions visible.
   * Mitigation: persistent “RAW / SANITIZED” toggle with explanation; raw is default locally; sanitized only for export. (Recs V-9, VII-5)

7. **Timeline overwhelm (low patience) → user gives up**

   * Detection: rapid tab switching; short sessions; repeated empty searches.
   * Mitigation: “Low-cognitive-load mode”: single Q&A box + 3 suggested queries + “Today summary” + “Last 5 contexts”. (Recs V-1, V-5)

8. **Keyboard/motor errors cause wrong time range**

   * Detection: frequent time-range edits.
   * Mitigation: time range presets (“last 15m / 1h / today”) + “jump to time” with large controls. (Recs V-2, V-7)

9. **High-frequency screen changes create massive data; user fears “it’s not working” due to lag**

   * Detection: queue depth rises; `captures_dropped_total` climbs; persist latency increases.
   * Mitigation: show “Capture keeping up / behind” indicator; always record drops with reasons; do not silently skip. (Recs VI-1, VIII-3)

10. **User trusts an answer with weak evidence**

* Detection: answer has few/low-confidence citations; missing media.
* Mitigation: enforce “citations required” default; show confidence + direct evidence previews. (Recs III-6, V-4)

11. **Multi-monitor gaps**

* Detection: per-monitor last-capture timestamps diverge.
* Mitigation: per-monitor capture badges; “monitor missing” warning. (Recs II-4, V-6)

12. **User expects recall during activity (but processing can’t run)**

* Detection: Q&A issued while user active.
* Mitigation: fallback to lexical OCR-only retrieval for immediate responses; offer “improve answer when idle” auto-refresh. (Recs III-3, VIII-7)

---

## B) Red-team as a System Admin/Operator (≥10): failure/ops modes

1. **Misconfig binds server to LAN**

   * Detection: bind_host not loopback; offline guard not restricting.
   * Mitigation: enforce loopback-only at runtime; fail closed if host != `127.0.0.1`; add Windows firewall rule. (Rec VII-1)

2. **Plugin conflict / override collision**

   * Detection: multiple plugins register same extension; nondeterministic order.
   * Mitigation: explicit priority + conflict UI; block enable unless resolved. (Rec IV-11)

3. **Update/rollback failure**

   * Detection: plugin enable triggers boot crash; supervisor restart loops.
   * Mitigation: atomic update with rollback; safe-mode wizard. (Recs IV-2, IV-8)

4. **SQLite contention causes capture lag**

   * Detection: increased retry rates; write latencies; capture backlog.
   * Mitigation: keep transactions short; batch writes; isolate capture journal from heavy reads. (Recs I-1, VIII-5)

5. **Media encryption key loss**

   * Detection: decrypt failures when reading `.acenc`.
   * Mitigation: key escrow locally (DPAPI-protected), backup key material to external drive with explicit warnings. (Rec VII-2, I-6)

6. **NVENC/driver regression breaks encoding**

   * Detection: store_media failures; CPU fallback engaged.
   * Mitigation: multi-encoder fallback ladder; health check at startup; alert when falling back. (Rec VIII-1)

7. **Retention worker deletes data (policy violation)**

   * Detection: retention deletion metrics increment; delete endpoints called.
   * Mitigation: compile-time “no deletion mode” that removes endpoints and pruning paths. (Rec I-2)

8. **Partial pipeline outage (capture OK, processing dead)**

   * Detection: worker heartbeats stale; derived artifacts stop appearing.
   * Mitigation: UI/tray show “Processing stopped” with reason; auto-restart on idle; diagnostics bundle. (Recs III-5, VI-3)

9. **Index corruption**

   * Detection: citations resolve to missing spans/media; integrity checker flags missing media. (Integrity patterns exist in tests)
   * Mitigation: nightly consistency sweep and repair; mark stale answers. (Rec III-9)

10. **Disk I/O errors / corruption**

* Detection: hash mismatch between DB and media; read failures.
* Mitigation: periodic hash verification + redundant local backups. (Recs I-8, I-6)

11. **CPU/RAM exceed 50% and degrade foreground processes**

* Detection: `process_cpu_percent` or RSS crosses thresholds.
* Mitigation: hard caps via Job Objects; dynamic worker throttling. (Recs VIII-2, III-10)

12. **Unsafe plugin permissions**

* Detection: plugin granted `allow_network` / `allow_shell`.
* Mitigation: deny-by-default, UI permission prompts, and out-of-process sandbox. (Recs IV-6, VII-6)

---

# A) Master recommendations tables (by bucket, in required order)

**Legend:** P1=Performant, P2=Security, P3=Accuracy, P4=Citeability. Total Σ out of 16.

---

## I. Foundation: Capture + Kernel stability (integrity, offline-first, crash recovery, journaling, backups)

| ID   | Recommendation (one line)                                                                                                             | Rationale                                                                                          | P1 | P2 | P3 | P4 |  Σ | Effort | Risk | Dependencies        | Acceptance test                                                                             |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | -: | -: | -: | -: | -: | ------ | ---- | ------------------- | ------------------------------------------------------------------------------------------- |
| I-1  | Add an append-only **Capture Journal** + reconciler (staging→committed)                                                               | Guarantees crash-safe persistence and provable “captured” events even if DB write fails mid-flight |  3 |  2 |  4 |  3 | 12 | M      | Med  | MediaStore, DB      | Kill process during write; on restart, journal replays/marks orphaned items; no silent loss |
| I-2  | Implement **No-Deletion Mode**: remove/disable delete endpoints + retention pruning; replace with archive/migrate                     | Your requirement is indefinite local retention; destructive paths must not exist                   |  2 |  3 |  4 |  4 | 13 | S/M    | Low  | API routes, tray    | Grep/route test proves `/api/delete_*` absent; retention worker never unlinks files         |
| I-3  | Add preset **“Memory Replacement (Raw)”**: `diff_epsilon=0`, exact-only dedupe, `always_store_fullres=true`, `block_fullscreen=false` | Aligns capture with “any pixel change ⇒ saved” policy using existing config knobs                  |  2 |  1 |  4 |  3 | 10 | S      | Med  | presets/config      | Run with clock minute tick: produces new media artifact + new hash each minute              |
| I-4  | Create **segment-based media store** (append-only) with per-frame hashes + periodic keyframes                                         | Indefinite retention needs scaling; avoids millions of files and reduces filesystem overhead       |  4 |  2 |  4 |  4 | 14 | L      | High | MediaStore, index   | Sustained 10 fps for 1 hr: storage remains consistent, random access works, hashes verify   |
| I-5  | Two-tier disk watermarks: soft backpressure + hard “CAPTURE HALTED: DISK LOW” banner                                                  | Prevents silent failure when disk is low; makes failure obvious and actionable                     |  3 |  2 |  3 |  3 | 11 | S      | Low  | disk guard, UI      | Simulate low disk: capture stops + banner + tray alert + event recorded                     |
| I-6  | Add encrypted **local backup + restore** workflow (external drive)                                                                    | Indefinite retention without backups is eventual data loss                                         |  2 |  4 |  4 |  4 | 14 | M      | Med  | encryption, tooling | Restore onto fresh machine: hashes/citations resolve; ledger continuity intact              |
| I-7  | Persist immutable **config snapshot** + plugin versions per session_id                                                                | Makes captures and derived artifacts reproducible and auditable                                    |  1 |  2 |  3 |  4 | 10 | S      | Low  | DB migration        | For any frame, UI shows config hash + plugin versions; export includes it                   |
| I-8  | Run **startup integrity sweep**: DB↔media existence + hash check; surface issues                                                      | Converts corruption/missing files into explicit, visible “broken evidence” states                  |  2 |  2 |  4 |  4 | 12 | S      | Low  | integrity module    | Delete a media file: sweep marks affected items; answers referencing it become “stale”      |
| I-9  | Crash-loop safe mode: if restarts >N, enter capture-only + diagnostics prompt                                                         | Avoids repeated thrash and preserves capture while preventing further corruption                   |  3 |  2 |  3 |  2 | 10 | M      | Low  | supervisor          | Force repeated crash: system enters safe mode; capture continues; UI shows reason           |
| I-10 | Split kernel into Windows Service (capture+DB) and separate user-space UI/processing group                                            | Improves stability and isolates “always-on” capture from UI/process failures                       |  3 |  3 |  3 |  2 | 11 | L      | Med  | packaging/install   | Reboot: service resumes capture; UI can be restarted without impacting capture              |

---

## II. Metadata: schema, provenance, surfacing, trust signals, auditability

| ID    | Recommendation                                                                                           | Rationale                                                                              | P1 | P2 | P3 | P4 |  Σ | Effort | Risk | Dependencies          | Acceptance test                                                                |
| ----- | -------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | -: | -: | -: | -: | -: | ------ | ---- | --------------------- | ------------------------------------------------------------------------------ |
| II-1  | Define canonical **Frame v2** schema and treat it as the single source of truth                          | Reduces model drift (`EventRecord`/`CaptureRecord`/`FrameRecord`) and makes UI simpler |  2 |  1 |  4 |  4 | 11 | L      | High | DB migration, UI      | Migration produces identical counts; every artifact references Frame v2 row    |
| II-2  | Add `capture_trigger` + `change_reason` + diff stats to metadata                                         | Makes “why did we capture this?” auditable (critical for your verification needs)      |  1 |  1 |  3 |  4 |  9 | M      | Low  | capture pipeline      | Item detail shows trigger=screen_change; diff stats non-null                   |
| II-3  | Store **two hashes**: `raw_pixels_hash` (pre-encode) + `encoded_bytes_hash`                              | Proves pixel-level uniqueness while allowing encoded storage optimizations             |  3 |  2 |  4 |  4 | 13 | M      | Med  | hashing utils         | Same frame encoded twice: raw hash equal; encoded hash may differ; both stored |
| II-4  | Always surface core metadata at top of UI item detail (hashes, timestamps, monitor, app)                 | Reduces cognitive load and makes “capture happened” instantly checkable                |  1 |  1 |  3 |  4 |  9 | S      | Low  | UI                    | Item detail shows hash + captured_at + monitor_id without scrolling            |
| II-5  | Compute `trust_level` (green/yellow/red) for each day/session and each answer                            | “Conservative” trust model: system warns when evidence/processing is incomplete        |  1 |  1 |  3 |  4 |  9 | M      | Low  | metrics + integrity   | Introduce dropped frames: trust becomes yellow/red; UI shows why               |
| II-6  | Store provenance ledger head (`entry_hash`) in DB and show/export it                                     | Gives a tamper-evident pointer for “I can prove this existed” workflows                |  1 |  3 |  3 |  4 | 11 | M      | Med  | ledger                | Export ledger-only bundle; verifier confirms hash chain continuity             |
| II-7  | Standardize artifact metadata: `job_id`, `engine`, `engine_version`, `attempts`, `last_error`, `timings` | Makes “processing actually ran” provable and debuggable                                |  1 |  1 |  4 |  4 | 10 | M      | Low  | artifact models       | Every artifact row has job_id+engine_version; UI lists failures per job        |
| II-8  | Add HID-session rollups: `active_seconds`, `captures_taken`, `drops_by_reason`                           | Frictionless capture must be measured and tied to user activity                        |  2 |  1 |  4 |  3 | 10 | M      | Med  | activity monitor      | For a 30-min session, dashboard shows captures/min + drop counts               |
| II-9  | Implement local-only **entity hash map** for export sanitization (salted, rotatable)                     | Enables “sanitize only on egress” while still letting you interpret exports locally    |  1 |  4 |  3 |  3 | 11 | L      | High | NLP/entity extraction | Export shows hashed entities; local UI can reveal originals after unlock       |
| II-10 | Add stronger DB constraints (FK + NOT NULL where required)                                               | Prevents partial/invalid states that destroy trust and citations                       |  1 |  2 |  4 |  3 | 10 | M      | Med  | migrations            | Attempt to insert artifact without frame: fails; integrity checker passes      |

---

## III. Processing pipeline: correctness, lineage, idempotency, replay, debuggability

| ID     | Recommendation                                                                          | Rationale                                                                 | P1 | P2 | P3 | P4 |  Σ | Effort | Risk | Dependencies     | Acceptance test                                                          |
| ------ | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- | -: | -: | -: | -: | -: | ------ | ---- | ---------------- | ------------------------------------------------------------------------ |
| III-1  | Make all workers **idempotent** via `dedupe_key=(type, engine_version, input_hash)`     | Ensures safe replay and eliminates duplicate derived artifacts            |  3 |  1 |  4 |  3 | 11 | M      | Med  | DB constraints   | Re-run OCR job: no duplicate artifacts; status updates occur             |
| III-2  | Introduce a first-class **JobRun** model (job_id everywhere) + UI DAG                   | Core requirement: prove processing ran against specific captured metadata |  2 |  1 |  4 |  4 | 11 | L      | Med  | schema + UI      | For any answer, UI shows job graph + inputs/outputs + hashes             |
| III-3  | Enforce “active user ⇒ processing paused”: non-capture workers scale to 0 in foreground | Meets your non-negotiable “never interfere” requirement                   |  4 |  1 |  3 |  2 | 10 | S      | Low  | governor/pause   | While mouse moves: workers stop; when idle: workers resume               |
| III-4  | Add deterministic **replay engine** (time range/frame_hash) that records diffs          | Enables auditing and debugging regressions without losing history         |  2 |  1 |  4 |  4 | 11 | L      | Med  | job graph        | Replay last hour: produces new job_id; diff view shows changes           |
| III-5  | Add processing watchdog + heartbeat escalation + auto-retry policy                      | Prevents silent pipeline stalls and supports conservative trust           |  2 |  1 |  4 |  3 | 10 | M      | Low  | workers          | Force worker hang: watchdog marks job stalled; retries; UI shows failure |
| III-6  | Make “citations required” the default answer policy                                     | Prevents uncited hallucinations and enforces evidence-backed recall       |  1 |  1 |  4 |  4 | 10 | M      | Med  | answer API + UI  | Query returns 400/soft-fail if no citations; UI explains why             |
| III-7  | Store summaries as artifacts with input list + prompt/model hash                        | Ensures summaries are reproducible and citable                            |  1 |  1 |  3 |  4 |  9 | M      | Low  | artifact models  | Summary artifact shows exact frames/spans used; clicking opens evidence  |
| III-8  | Add per-job debug bundle export (inputs/hashes/versions/logs)                           | Makes pipeline failures actionable without guessing                       |  1 |  3 |  3 |  4 | 11 | M      | Med  | diagnostics      | Export bundle for failed job; contains everything needed to reproduce    |
| III-9  | Nightly (idle-only) DB↔index consistency sweeps with repair                             | Prevents gradual drift that destroys recall quality                       |  2 |  1 |  4 |  3 | 10 | M      | Low  | index layer      | Remove index entries: sweep restores; citations remain resolvable        |
| III-10 | Add dynamic budgeter: maximize GPU while enforcing CPU<50%, RAM<50%                     | Meets hard QoS constraint and avoids system slowdowns                     |  4 |  1 |  3 |  2 | 10 | L      | Med  | runtime governor | Stress test: CPU never exceeds 50%; GPU may hit 100% when idle           |

---

## IV. Plugin manager: install/update/rollback, compatibility, sandboxing, permissions, health checks, UX

| ID    | Recommendation                                                               | Rationale                                                                      | P1 | P2 | P3 | P4 |  Σ | Effort | Risk | Dependencies    | Acceptance test                                                                   |
| ----- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | -: | -: | -: | -: | -: | ------ | ---- | --------------- | --------------------------------------------------------------------------------- |
| IV-1  | Redesign plugin IA: Installed / Catalog / Updates / Permissions / Health     | Reduces operator error and cognitive load (your current UX is too error-prone) |  2 |  3 |  3 |  2 | 10 | M      | Low  | web UI          | Usability test: enable/disable and approve hashes in <15s without mistakes        |
| IV-2  | Atomic install/update with staging + hash verification + rollback            | Prevents half-installed states and “boot broken” failures                      |  2 |  3 |  3 |  2 | 10 | M      | Med  | plugin FS ops   | Interrupt install mid-way: system remains usable; previous version still loads    |
| IV-3  | Compatibility gating (app/schema/python/OS/GPU constraints in manifest)      | Stops incompatible plugins before they break capture/processing                |  1 |  2 |  4 |  2 |  9 | M      | Low  | manifest schema | Try enabling incompatible plugin: blocked with explicit reason                    |
| IV-4  | Two-phase enable: sandbox load → health check → enable                       | Converts runtime crashes into safe failed enable attempts                      |  2 |  3 |  3 |  2 | 10 | M      | Med  | plugin runtime  | Plugin throws on import: enable fails safely; no crash loop                       |
| IV-5  | Permission UX: render PolicyGate permissions and require explicit approval   | Aligns with least privilege and reduces accidental risk                        |  1 |  4 |  2 |  2 |  9 | S/M    | Low  | policy gate     | Plugin requests network: UI warns; default deny; enable requires explicit allow   |
| IV-6  | Default “untrusted plugins run out-of-process” with IPC + JobObject caps     | Enforces CPU/RAM limits and reduces blast radius                               |  2 |  4 |  3 |  2 | 11 | L      | High | IPC framework   | Misbehaving plugin pegs CPU: JobObject caps; core remains stable                  |
| IV-7  | Plugin health dashboard: last error, latency, memory, denials, restart count | Makes ops visible and prevents silent plugin failures                          |  2 |  2 |  3 |  2 |  9 | M      | Low  | metrics + UI    | Plugin failure increments counter; UI shows error + disable button                |
| IV-8  | Safe mode recovery wizard (tray + UI)                                        | Minimizes downtime after plugin regressions                                    |  2 |  2 |  3 |  1 |  8 | M      | Low  | tray + UI       | Force crash on startup: safe mode launches; user can re-enable plugins one-by-one |
| IV-9  | Optional plugin signing + trust levels                                       | Adds a strong integrity check for plugin supply chain                          |  1 |  4 |  2 |  2 |  9 | L      | Med  | signing infra   | Unsigned plugin blocked if signing required; signed plugin verifies               |
| IV-10 | Unified plugin logs/traces (per-plugin view)                                 | Speeds debugging and reduces operator guesswork                                |  1 |  2 |  3 |  2 |  8 | M      | Low  | logging         | Select plugin → see last 200 log lines with correlation IDs                       |

### Plugin manager redesign (minimal viable spec + stretch)

**Minimal viable spec (MVS)**

* **Information architecture**

  * **Installed**: enabled/disabled, version, trust level, last health, permissions summary
  * **Catalog**: built-in + local directory + installed packages + “import bundle”
  * **Updates**: available updates, pinned versions, rollback points
  * **Permissions**: matrix by plugin vs permission (`network`, `filesystem`, `shell`, `openai`) (based on PolicyGate)
  * **Health**: self-tests, recent errors, resource usage

* **Core flows**

  1. **Install** → validate manifest → compute hashes → show diff vs currently installed → stage → activate
  2. **Enable** → permission prompt → sandbox load → health check → activate
  3. **Update** → stage new → run self-test → atomic switch → keep rollback snapshot
  4. **Rollback** → select previous snapshot → activate → record audit entry
  5. **Doctor** (UI wrapper around existing `plugins doctor`)

**Stretch goals**

* Per-plugin performance budgets and auto-throttle
* Extension override conflict resolver with explicit priority graph
* Signed update channels and “quarantine new plugin until observed stable for N hours”

---

## V. UI/UX for memory replacement: timeline, recall flows, search, summaries, “what happened today”, cognitive accessibility

| ID   | Recommendation                                                              | Rationale                                                            | P1 | P2 | P3 | P4 |  Σ | Effort | Risk | Dependencies    | Acceptance test                                                          |
| ---- | --------------------------------------------------------------------------- | -------------------------------------------------------------------- | -: | -: | -: | -: | -: | ------ | ---- | --------------- | ------------------------------------------------------------------------ |
| V-1  | Make Home = **Today + Omnibox** (Q&A-first)                                 | Your primary job-to-be-done is recall, not configuration             |  1 |  1 |  3 |  4 |  9 | M      | Low  | UI              | Open UI → type question → see evidence-backed answer + citations         |
| V-2  | Session-grouped timeline (HID sessions + app focus) with gap markers        | Helps you reason about “what happened” under cognitive load          |  1 |  1 |  4 |  3 |  9 | M      | Low  | host events     | Timeline shows sessions with durations and apps; gaps show reasons       |
| V-3  | Item detail view: raw media + metadata/provenance + processing status       | Direct verification: “did it capture? did it process? against what?” |  1 |  1 |  3 |  4 |  9 | M      | Low  | UI + APIs       | Click item → see frame_hash + job_id + derived artifacts list            |
| V-4  | “Explain answer” panel with retrieval trace + top spans                     | Makes citeability explicit and reduces blind trust                   |  1 |  1 |  3 |  4 |  9 | M      | Med  | retrieval trace | Every answer can show its citations and open the exact evidence          |
| V-5  | Cognitive accessibility modes: low-choice UI + big targets + keyboard-first | Supports distraction/fatigue and reduces mis-click risk              |  1 |  1 |  2 |  2 |  6 | M      | Low  | UI              | Keyboard-only navigation works; reduced-motion toggle works              |
| V-6  | Capture status panel everywhere (top bar + tray parity)                     | You must never wonder “is it working right now?”                     |  2 |  1 |  3 |  3 |  9 | S/M    | Low  | metrics         | Panel shows last_capture_age, drops, disk, paused reason                 |
| V-7  | “Fast recall templates” (time/app/person)                                   | Reduces cognitive effort to form useful queries                      |  1 |  1 |  3 |  3 |  8 | S      | Low  | UI              | One click: “What happened today?” returns cited summary                  |
| V-8  | “Proof chips” per answer: Captured/OCR/Embed/Summary with job_id + hashes   | Visual proof that processing ran on captured evidence                |  1 |  1 |  3 |  4 |  9 | M      | Low  | lineage APIs    | Clicking chip opens the underlying artifact and its inputs               |
| V-9  | Export flow (sanitized only) with preview + warnings + audit entry          | Required for safe cloud egress without altering local raw store      |  1 |  4 |  2 |  3 | 10 | M      | Med  | export pipeline | Export shows hashed entities; exported bundle contains manifest + proofs |
| V-10 | Tray companion: status + toggles + safe mode; remove delete actions         | Meets “tray companion” requirement without violating no-deletion     |  1 |  2 |  2 |  1 |  6 | S/M    | Low  | tray app        | Tray shows last capture time; can pause processing; cannot delete        |

---

## VI. Observability/Ops: logs, metrics, tracing, user-visible status, error budgets, diagnostics bundles

| ID    | Recommendation                                                                              | Rationale                                                     | P1 | P2 | P3 | P4 |  Σ | Effort | Risk | Dependencies     | Acceptance test                                                            |
| ----- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------- | -: | -: | -: | -: | -: | ------ | ---- | ---------------- | -------------------------------------------------------------------------- |
| VI-1  | Define “Frictionless Capture” SLOs and show them in UI                                      | Measurement is required; otherwise you can’t trust the system |  2 |  1 |  3 |  3 |  9 | S/M    | Low  | metrics/UI       | Dashboard shows SLO pass/fail and last 24h error budget                    |
| VI-2  | Add metrics: `screen_change_detect_ms`, `persist_commit_ms`, queue depth p95                | Quantifies where capture friction/failure happens             |  2 |  1 |  3 |  2 |  8 | M      | Low  | capture pipeline | Under load test, histograms report; UI shows p95 values                    |
| VI-3  | Diagnostics bundle generator (no raw media by default)                                      | Makes failures debuggable without guesswork                   |  1 |  3 |  3 |  2 |  9 | M      | Low  | diagnostics      | Generate bundle; contains config snapshot, plugin list, logs, DB integrity |
| VI-4  | Correlation IDs everywhere: `frame_id`, `job_id`, `plugin_id` in logs                       | Turns “what happened?” into something answerable              |  1 |  1 |  3 |  2 |  7 | M      | Low  | logging          | Search logs by frame_id shows capture + processing chain                   |
| VI-5  | Explicit pipeline state machine in UI (“Capture running”, “Processing paused: user active”) | Prevents silent assumptions about processing                  |  1 |  1 |  3 |  2 |  7 | S/M    | Low  | UI               | While user active, UI shows processing paused reason                       |
| VI-6  | Silent failure detector: HID active but no captures ⇒ alert event + tray notify             | Catches your worst-case: thinking it worked when it didn’t    |  2 |  1 |  4 |  2 |  9 | S/M    | Low  | activity monitor | Simulate capture thread dead: within T seconds, alert appears              |
| VI-7  | Error budget tracking for drop rate and pipeline lag                                        | Creates a conservative trust signal you can rely on           |  1 |  1 |  3 |  2 |  7 | M      | Low  | metrics          | Weekly view shows budget consumption; spikes highlight incident windows    |
| VI-8  | Runbook integrated into UI (localhost-only, restore, safe mode)                             | Reduces time-to-recovery during outages                       |  1 |  1 |  2 |  1 |  5 | S      | Low  | docs/UI          | “Help → Recovery” shows steps; links to diagnostics export                 |
| VI-9  | Idle-only self-heal tasks: orphan cleanup, reindex, vector sidecar checks                   | Prevents gradual degradation without impacting foreground use |  2 |  1 |  3 |  2 |  8 | M      | Med  | sched/governor   | Under idle, tasks run; under activity, they stop immediately               |
| VI-10 | Enforce CPU/RAM caps with alerts + auto-throttle                                            | Hard requirement; must be visible and automatic               |  4 |  1 |  2 |  1 |  8 | M      | Med  | governor         | CPU never >50% in perf test; UI flags any breach                           |

### Frictionless capture metrics (explicit proposal)

Use existing metrics as baseline (already present): capture counters and drop reasons plus CPU/RAM/GPU gauges.

Add/standardize these **user-facing** metrics:

* **Capture freshness**

  * `last_capture_age_seconds` (per monitor + global)
  * `capture_gap_seconds` (sum per day/session)
* **Capture completeness**

  * `captures_taken_total`
  * `captures_dropped_total` by reason (disk low, backpressure, encoder fail)
  * `captures_skipped_duplicate_total` (should be near 0 in strict-change mode)
* **Capture latency**

  * `screen_change_detect_ms` (new)
  * `store_media_ms` / `persist_commit_ms` (new split; you already have `store_media_ms`)
* **Resource safety**

  * `process_cpu_percent`, `process_rss_mb`, `gpu_utilization` (existing)
  * plus `throttle_events_total` (new) whenever governor clamps CPU/RAM

---

## VII. Security/Privacy: least privilege, encryption, secrets, PII controls, local-first options, consent

| ID     | Recommendation                                                             | Rationale                                                             | P1 | P2 | P3 | P4 |  Σ | Effort | Risk | Dependencies   | Acceptance test                                                         |
| ------ | -------------------------------------------------------------------------- | --------------------------------------------------------------------- | -: | -: | -: | -: | -: | ------ | ---- | -------------- | ----------------------------------------------------------------------- |
| VII-1  | Enforce loopback-only: bind host + offline guard + firewall rule           | Strictly localhost must be enforced, not just configured              |  1 |  4 |  1 |  1 |  7 | S      | Low  | net layer      | Attempt access from LAN fails; app refuses non-loopback bind            |
| VII-2  | Default-on at-rest encryption (DB+media), Windows Hello unlock + auto-lock | Protects raw media at rest while staying local-first                  |  1 |  4 |  2 |  1 |  8 | M      | Med  | encryption     | Lock session: API denies protected endpoints; unlock restores access    |
| VII-3  | Remove unlock token from URL; use secure in-memory session and short TTL   | Reduces token leakage risk (screen recordings, logs, browser history) |  1 |  4 |  1 |  1 |  7 | M      | Med  | web UI         | Refresh doesn’t expose token; token expires; must re-unlock             |
| VII-4  | Append-only audit log for privileged actions (unlock/export/plugin/config) | Makes sensitive actions reviewable and tamper-evident                 |  1 |  3 |  2 |  3 |  9 | M      | Low  | ledger         | Perform actions; audit entries appear; chain verifies                   |
| VII-5  | Export-only sanitization: entity hashing/redaction; never mutate local raw | Meets “sanitize only on cloud egress” requirement                     |  1 |  4 |  3 |  3 | 11 | L      | High | NLP/export     | Export bundle contains only sanitized artifacts + policy manifest       |
| VII-6  | Tighten PolicyGate defaults + per-plugin allowlists managed in UI          | Least privilege for plugin system; reduces blast radius               |  1 |  4 |  2 |  2 |  9 | S/M    | Low  | plugin system  | Plugin attempts network without allow: denied + logged + visible in UI  |
| VII-7  | Add CSP + CSRF hardening even on localhost                                 | Prevents local browser-based attacks and plugin UI injection          |  1 |  3 |  1 |  1 |  6 | M      | Low  | web server     | CSRF tests pass; CSP blocks inline script injection                     |
| VII-8  | Secrets scanning + log redaction tests in CI                               | Prevents accidental leakage of keys/tokens in logs                    |  1 |  3 |  1 |  1 |  6 | S      | Low  | CI             | CI fails if tokens detected; runtime logs redact                        |
| VII-9  | Enforce vendor binary SHA verification (ffmpeg/qdrant) and fail closed     | Protects supply chain for sidecars/binaries                           |  1 |  4 |  1 |  1 |  7 | S      | Low  | vendor tooling | Corrupt binary hash ⇒ startup fails with explicit error                 |
| VII-10 | Export review UI: show hashed entity dictionary locally (after unlock)     | Keeps you in control of what leaves the machine                       |  1 |  4 |  2 |  2 |  9 | L      | High | NLP/export     | User reviews entity list; selects exclusions; export reflects selection |

---

## VIII. Performance (Windows 11 + RTX 4090): indexing speed, GPU acceleration, latency budgets

| ID      | Recommendation                                                                                  | Rationale                                                           | P1 | P2 | P3 | P4 |  Σ | Effort | Risk | Dependencies | Acceptance test                                                                        |
| ------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | -: | -: | -: | -: | -: | ------ | ---- | ------------ | -------------------------------------------------------------------------------------- |
| VIII-1  | Default GPU encoding (`nvenc_webp`/`nvenc_avif`), lossless; CPU fallback ladder                 | Maintains capture throughput while respecting CPU cap               |  4 |  1 |  2 |  1 |  8 | S      | Low  | encoder      | Disable NVENC: CPU fallback works; capture continues; UI warns                         |
| VIII-2  | Enforce CPU/RAM caps with Windows Job Objects (workers + plugin subprocesses)                   | Only reliable way to guarantee “never over 50%”                     |  4 |  2 |  2 |  1 |  9 | L      | Med  | Windows APIs | Stress test: process CPU ≤ 50%; RSS ≤ 32GB; violations prevented                       |
| VIII-3  | Change-driven capture: Desktop Duplication dirty-rect based; no polling; record drops if behind | Best path to “any change ⇒ capture” without wasting CPU             |  4 |  1 |  4 |  3 | 12 | M/L    | Med  | win_directx  | Animated screen: captures reflect changes; if behind, drop events recorded and visible |
| VIII-4  | BLAKE3 raw frame hashing (pre-encode), parallelized                                             | Keeps hashing fast enough for high-frequency change capture         |  3 |  1 |  3 |  2 |  9 | M      | Low  | hashing      | Hash throughput test meets target; hashes stable across runs                           |
| VIII-5  | Short DB transactions + batched commits + fsync scheduling                                      | Reduces lock contention and capture stalls                          |  3 |  1 |  2 |  1 |  7 | M      | Med  | DB layer     | Under load, DB busy retries decrease; capture backlog reduced                          |
| VIII-6  | Idle-only GPU OCR/embedding (TensorRT/ONNX) with memory guard                                   | Maximizes idle GPU use while keeping CPU/RAM under cap              |  4 |  1 |  3 |  1 |  9 | L      | High | model stack  | Idle run saturates GPU; CPU remains <50%; memory remains <50%                          |
| VIII-7  | Optimize retrieval: lexical-first fallback, vector sidecar localhost, minimal payload           | Keeps Q&A responsive even when processing is paused                 |  3 |  1 |  2 |  2 |  8 | M      | Low  | retrieval    | While user active, Q&A returns OCR-based results quickly; improves when idle           |
| VIII-8  | Shard media paths by hash prefix (or segment store) to avoid filesystem hot spots               | Improves performance at large scale                                 |  3 |  1 |  2 |  1 |  7 | M      | Low  | MediaStore   | 10M artifacts: directory counts remain bounded; lookups stay fast                      |
| VIII-9  | Define latency budgets and track p95: capture persist, UI queries, retrieval                    | Prevents performance regressions from becoming “invisible failures” |  2 |  1 |  2 |  1 |  6 | S      | Low  | metrics      | Perf CI fails if p95 exceeds thresholds                                                |
| VIII-10 | GPU preemption on activity: release GPU allocations immediately on user input                   | Avoids stutter during active use                                    |  4 |  1 |  2 |  1 |  8 | M      | Med  | governor     | Move mouse during idle OCR run → OCR pauses within 1s; GPU frees                       |

---

## IX. QA/Test strategy: unit/integration/e2e, golden datasets, chaos testing, migration tests

| ID    | Recommendation                                                        | Rationale                                                 | P1 | P2 | P3 | P4 |  Σ | Effort | Risk | Dependencies | Acceptance test                                                     |
| ----- | --------------------------------------------------------------------- | --------------------------------------------------------- | -: | -: | -: | -: | -: | ------ | ---- | ------------ | ------------------------------------------------------------------- |
| IX-1  | Golden dataset for capture→OCR→embedding→answer with citations        | Regression safety for the whole “memory replacement” loop |  1 |  1 |  4 |  4 | 10 | M      | Low  | test infra   | CI proves answer cites expected spans and media                     |
| IX-2  | Chaos tests: crash during persist, disk full, DB locked, encoder fail | Ensures no silent failures and validates recovery paths   |  2 |  1 |  4 |  3 | 10 | M      | Med  | harness      | Each chaos case produces alert + recoverable state                  |
| IX-3  | Migration tests with ledger continuity and citation validity          | Schema changes must not invalidate your past memories     |  1 |  2 |  4 |  4 | 11 | M      | Med  | migrations   | Upgrade across versions: old answers still resolve to evidence      |
| IX-4  | E2E “Today Q&A” test: asks question, checks citations resolve         | Guarantees citeability stays real, not aspirational       |  1 |  1 |  3 |  4 |  9 | M      | Low  | e2e rig      | Clicking citation opens correct media + span bbox                   |
| IX-5  | Fuzz plugin manifests + install sources (zip/dir/pkg)                 | Hardens plugin manager and prevents parse/path issues     |  1 |  3 |  2 |  1 |  7 | M      | Low  | fuzz harness | Malformed manifests never crash; errors are surfaced clearly        |
| IX-6  | Resource budget tests: CPU/RAM never exceed 50%; GPU allowed in idle  | Verifies a hard nonfunctional requirement continuously    |  3 |  1 |  2 |  1 |  7 | M      | Med  | perf rig     | Under load, CPU/RAM caps respected; alerts fire on attempted breach |
| IX-7  | Windows integration tests for DirectX capture + RawInputListener      | Validates platform-specific core functionality            |  2 |  1 |  3 |  1 |  7 | L      | Med  | CI runners   | Multi-monitor change capture works on real Win11 runner             |
| IX-8  | Localhost-only security tests (bind + offline guard + CSP)            | Prevents accidental exposure regressions                  |  1 |  4 |  1 |  1 |  7 | S/M    | Low  | server       | Tests confirm only loopback accessible; CSRF/CSP headers present    |
| IX-9  | Provenance chain tamper-detection tests                               | Ensures your proof system actually proves something       |  1 |  2 |  3 |  4 | 10 | M      | Low  | ledger       | Modify ledger entry: verifier detects break; UI flags               |
| IX-10 | Accessibility test suite (keyboard nav, focus order, contrast)        | Keeps UI usable under disability constraints              |  1 |  1 |  2 |  1 |  5 | M      | Low  | UI tests     | Automated checks pass; manual checklist verified per release        |

---

## X. Roadmap: phased plan (Phase 0–3) + quick wins + leverage

| ID  | Project / Phase                                                                              | Rationale                                                         | P1 | P2 | P3 | P4 |  Σ | Effort | Risk | Dependencies         | Acceptance test                                                               |
| --- | -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- | -: | -: | -: | -: | -: | ------ | ---- | -------------------- | ----------------------------------------------------------------------------- |
| X-0 | **Phase 0:** No-deletion + strict raw capture preset + capture health UI + foreground gating | Stabilize kernel and make “is it working?” obvious                |  3 |  3 |  4 |  4 | 14 | M      | Med  | I-2, I-3, V-6, III-3 | You can verify capture freshness in 2 seconds; no delete paths exist          |
| X-1 | **Phase 1:** JobRun/lineage model + proof chips + citations-required answers                 | Makes processing provable and conservative by default             |  2 |  2 |  4 |  4 | 12 | L      | Med  | III-2, III-6, V-8    | Every answer includes resolvable citations and job_id trail                   |
| X-2 | **Phase 2:** Indefinite retention scaling (segment store) + backup/restore + archive/migrate | Solves the inevitable storage wall without deleting memories      |  4 |  3 |  4 |  4 | 15 | L      | High | I-4, I-6             | 6-month simulated retention works; restore recovers citations                 |
| X-3 | **Phase 3:** Plugin manager hardening (atomic updates, sandbox, permissions UX)              | Reduces plugin-caused outages and security risks                  |  2 |  4 |  4 |  2 | 12 | L      | High | IV-2, IV-6, VII-6    | Bad plugin cannot crash kernel; rollback is one click                         |
| X-4 | “What happened today” digest (idle GPU) + evidence-backed summaries                          | High-leverage UX improvement for memory replacement               |  3 |  1 |  4 |  4 | 12 | L      | Med  | III-7, VIII-6        | Daily digest cites frames/spans and opens evidence on click                   |
| X-5 | Sanitized export packages with local reversible entity map                                   | Enables safe cloud workflows without compromising local raw store |  1 |  4 |  3 |  3 | 11 | L      | High | II-9, VII-5          | Export contains no raw media/PII; local view can map hashes back after unlock |

---

# B) Top-20 quick wins (highest Σ, Effort = S or M)

(IDs refer to tables above.)

1. I-2 (Σ13, S/M) — No-deletion mode
2. II-3 (Σ13, M) — raw_pixels_hash + encoded_bytes_hash
3. I-8 (Σ12, S) — startup integrity sweep
4. I-5 (Σ11, S) — disk watermark + hard halt banner
5. III-1 (Σ11, M) — idempotent processing via dedupe_key
6. III-5 (Σ10, M) — watchdog + heartbeats + retries
7. III-6 (Σ10, M) — citations-required default
8. IV-5 (Σ9, S/M) — permission UX for plugins
9. V-6 (Σ9, S/M) — always-visible capture status panel
10. V-8 (Σ9, M) — proof chips per answer
11. VI-1 (Σ9, S/M) — frictionless capture SLO dashboard
12. VI-6 (Σ9, S/M) — silent failure detector (HID active but no captures)
13. VII-1 (Σ7, S) — enforce localhost bind + firewall
14. VII-9 (Σ7, S) — fail-closed vendor SHA verification
15. VIII-1 (Σ8, S) — GPU encoding default + fallback ladder
16. VIII-4 (Σ9, M) — BLAKE3 raw hashing
17. IX-1 (Σ10, M) — golden dataset for end-to-end recall
18. IX-2 (Σ10, M) — chaos tests for capture/persist failures
19. IX-3 (Σ11, M) — migration tests with ledger continuity
20. IX-8 (Σ7, S/M) — localhost-only security regression tests

---

# C) Top-20 big bets (highest Σ regardless of effort)

1. X-2 (Σ15, L) — segment store + backup/restore + archive/migrate
2. I-4 (Σ14, L) — segment-based media store
3. I-6 (Σ14, M) — encrypted backups + restore
4. X-0 (Σ14, M) — Phase 0 stabilization package
5. II-3 (Σ13, M) — raw + encoded hash dual system
6. I-2 (Σ13, S/M) — no-deletion mode
7. VIII-3 (Σ12, M/L) — dirty-rect change-driven capture
8. X-1 (Σ12, L) — job/lineage + proof-first answers
9. X-3 (Σ12, L) — plugin sandbox + atomic updates
10. X-4 (Σ12, L) — cited daily digest + summaries
11. III-2 (Σ11, L) — JobRun DAG + UI
12. III-4 (Σ11, L) — deterministic replay + diffs
13. III-8 (Σ11, M) — per-job debug bundles
14. II-6 (Σ11, M) — provenance ledger head pointer + export
15. II-9 (Σ11, L) — local reversible entity hash map
16. VII-5 (Σ11, L) — export-only sanitization pipeline
17. IV-6 (Σ11, L) — out-of-process plugin sandbox
18. IX-3 (Σ11, M) — migration tests with citation validity
19. I-1 (Σ12, M) — capture journal + reconciler
20. VIII-2 (Σ9, L) — Job Objects CPU/RAM enforcement (high leverage for QoS constraint)

---

# E) Minimal canonical metadata schema proposal (fields + types + examples)

This is a **minimal** schema aligned with what you already store (`FrameRecord`, `ArtifactRecord`, `derived_from`, `frame_hash`).

## Core entities

### 1) `Frame` (authoritative captured media row)

| Field                | Type        | Example                               |
| -------------------- | ----------- | ------------------------------------- |
| `frame_id`           | UUID/string | `"f1"`                                |
| `captured_at_utc`    | datetime    | `"2026-01-30T20:14:05.123Z"`          |
| `monotonic_ts`       | float       | `123456.78`                           |
| `session_id`         | string      | `"boot_2026-01-30T19:55Z"`            |
| `capture_trigger`    | enum        | `"screen_change"`                     |
| `monitor_id`         | string      | `"m1"`                                |
| `monitor_bounds`     | int[4]      | `[0,0,3840,2160]`                     |
| `app_name`           | string      | `"chrome.exe"`                        |
| `window_title`       | string      | `"Docs — Autocapture"`                |
| `raw_media_path`     | string      | `"media/ab/cd/<hash>.webp"`           |
| `raw_pixels_hash`    | string      | `"b3:<…>"`                            |
| `encoded_bytes_hash` | string      | `"sha256:<…>"`                        |
| `codec`              | enum        | `"webp_lossless"`                     |
| `bytes`              | int         | `4821930`                             |
| `encryption`         | object      | `{ "enabled": true, "key_id": "k1" }` |
| `privacy_flags`      | object      | `{ "cloud_allowed": false }`          |
| `schema_version`     | int         | `2`                                   |

> Note: you already have `frame_hash`, `privacy_flags`, `monitor_bounds`, etc. in `FrameRecord`.

### 2) `Artifact` (derived outputs; OCR, embeddings, summaries, etc.)

| Field                   | Type     | Example                                               |
| ----------------------- | -------- | ----------------------------------------------------- |
| `artifact_id`           | string   | `"a1"`                                                |
| `frame_id`              | string   | `"f1"`                                                |
| `artifact_type`         | enum     | `"ocr_spans"`                                         |
| `engine`                | string   | `"paddleocr"`                                         |
| `engine_version`        | string   | `"2.7.0"`                                             |
| `job_id`                | string   | `"job_2026-01-30T20:15Z_0003"`                        |
| `derived_from`          | object   | `{ "frame_hash": "b3:…", "raw_pixels_hash": "b3:…" }` |
| `upstream_artifact_ids` | string[] | `[]`                                                  |
| `status`                | enum     | `"done"` / `"failed"`                                 |
| `timings_ms`            | object   | `{ "run": 83 }`                                       |
| `last_error`            | string   | `null`                                                |

> Your existing `ArtifactRecord` already contains `artifact_type`, `engine`, `engine_version`, and `derived_from`.

### 3) `CitableSpan` (fine-grained citeable units)

Minimum fields:

* `span_id`, `artifact_id`, `frame_id`, `text`, `bbox_norm`, `span_hash`, `created_at`

(You already generate stable ids and store spans as citeable records; keep that pattern.)

---

# F) Minimal processing lineage model (captured → processed → derived insights)

## Lineage rule (non-negotiable)

Every derived object must include:

* `job_id`
* `input frame_id(s)`
* `input hash(es)` (at least `raw_pixels_hash` or `frame_hash`)
* `engine + engine_version`
* deterministic `artifact_id` (or `dedupe_key`)

You already propagate `frame_hash` into embedding payloads (good).

## Minimal graph (what you should persist and show)

```
[Frame f1]
  hashes: raw_pixels_hash, encoded_bytes_hash
  |
  +--> [Artifact a_ocr] type=ocr_spans job=J1 derived_from{hashes}
  |        |
  |        +--> [CitableSpan s1..sn] (bbox + text)  <-- citations point here
  |
  +--> [Artifact a_embed] type=embeddings job=J2 derived_from{hashes}
  |
  +--> [RetrievalTrace t1] query="..." job=J3 inputs{indexes@version}
  |
  +--> [Answer ans1] cites [s3, s9, ...] + references frames [f1,f7,...]
```

## UI-visible proof requirements

For any answer:

* show citations → spans → frame → raw media
* show job chain with timestamps and engine versions
* show “missing evidence” explicitly if media or spans are absent (conservative)

---

# G) UI/UX sketch (ASCII/wireframe)

## 1) Home / “Today” view (Q&A-first)

```
┌──────────────────────────────────────────────────────────────────────┐
│  Autocapture (LOCAL)   [Capture: ● RUNNING] [Processing: ⏸ USER ACTIVE] │
│  Last capture: 2s ago | Drops (1h): 0 | Disk: OK | CPU: 12% | RAM: 18% │
├──────────────────────────────────────────────────────────────────────┤
│  Ask (natural language)                                                 │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  What was I doing around 3pm?                                     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│  Suggested: [What happened today] [Last time I saw "invoice"] [Yesterday]│
├──────────────────────────────────────────────────────────────────────┤
│  Answer                                                                 │
│  "You were editing ... at 3:02pm and reviewing ..."                     │
│  Proof: [Captured ✅ f7] [OCR ✅ a_ocr] [Embed ⏸] [Summary ⏸]            │
│  Citations: (s3) (s9) (s12)                                             │
├──────────────────────────────────────────────────────────────────────┤
│  Today Timeline (sessions + gaps)                                       │
│  2:45–3:20  Chrome (Docs)   ▓▓▓▓▓▓▓▓▓▓   Gap: none                       │
│  3:20–3:40  VSCode          ▓▓▓▓▓▓       Gap: 12s (disk check)           │
│  3:40–4:05  Email           ▓▓▓▓▓▓▓▓▓    Gap: none                       │
└──────────────────────────────────────────────────────────────────────┘
```

## 2) Capture status panel (drill-down)

```
Capture Status
- State: RUNNING
- Mode: Memory Replacement (Raw)
- Trigger: Screen-change + HID-active
- Per-monitor:
  - m1: last 1.8s ago, 0 drops (1h)
  - m2: last 2.1s ago, 0 drops (1h)
- Queue:
  - pending frames: 3 / max 1000
  - persist p95: 120ms
- Disk:
  - data free: 2.3TB (hard stop at 20GB)
  - staging free: 100GB
- Recent alerts: none
```

## 3) Plugin manager main screen

```
Plugins
┌───────────────┬───────────────────────────────────────────────────────┐
│ Installed      │  Selected: ocr.paddle                                 │
│  ● enabled     │  Version: 1.4.2  |  Source: entrypoint                │
│  ○ disabled    │  Status: HEALTHY (last check 2m ago)                  │
│               │  Permissions: [filesystem: read] [network: DENIED]     │
│  Search: ____  │  Hashes: manifest SHA256 ... | code SHA256 ...        │
├───────────────┼───────────────────────────────────────────────────────┤
│ ocr.paddle     │  Actions: [Disable] [Run self-test] [Pin version]     │
│ embed.local    │           [Update…] [Rollback…] [View logs]           │
│ export.sanitize│                                                       │
└───────────────┴───────────────────────────────────────────────────────┘
Install: [From folder] [From zip bundle] [From local wheel] [From git…]
Safe mode: [ON/OFF]  (If ON: no third-party plugins load)
```

## 4) Item detail view showing metadata + provenance + processing status

```
Frame f7  (Captured 2026-01-30 15:02:11.221 -0700)
┌──────────────────────────────┬────────────────────────────────────────┐
│ [RAW SCREENSHOT PREVIEW]     │  Core metadata                          │
│                              │  frame_hash: b3:...                     │
│                              │  raw_pixels_hash: b3:...                │
│                              │  encoded_bytes_hash: sha256:...         │
│                              │  app: chrome.exe                        │
│                              │  window: "Docs — ..."                   │
│                              │  monitor: m1 [0,0,3840,2160]            │
│                              │  trigger: screen_change                 │
│                              │  trust: GREEN (no drops in ±2m)         │
├──────────────────────────────┴────────────────────────────────────────┤
│ Processing                                                               │
│  OCR: DONE  (artifact a_ocr, job J1, engine paddleocr@2.7.0, 83ms)      │
│  Embeddings: PENDING (paused: user active)                              │
│  Summary: NOT RUN                                                       │
│ Evidence                                                                 │
│  Spans: s3 "..." [bbox]  | s9 "..." [bbox]   (click opens highlight)    │
└────────────────────────────────────────────────────────────────────────┘
```

---

# Open questions (≤12, non-blocking)

1. How many monitors and typical resolutions (e.g., 1×4K vs 2×4K)? This drives storage and capture throughput sizing. 1 8k
2. Do you want audio capture (mic/system) under the “all media is raw” rule, or strictly screen + events?  yes, as a separate capture plugin
3. Are there any app categories you explicitly want to **pause capture** for (not delete), e.g., password managers?  no, i want everything captured, security will be on the encryption and pII proxy through promptops for anything external.
4. Should fullscreen DRM-protected surfaces be “best effort” capture with explicit “unavailable” markers, or hard-fail? yes best effort with explicit. 
5. What is the target minimum “last capture age” you consider acceptable while active (e.g., <2s, <5s)? trigger ss on any HID input, mouse or keyboard or etc, and then a recommended amount after that. goal is to capture anytime any content on the screenshot changes, so if the hash does not match then save it. but while the user is active atleast every .5 seconds to check the hash of a screenshot between HID. 
6. Is an external drive available and preferred for archival migration + backups (and what capacity class)? we are not even remotely near that.  you have to get this shit functioning before we worry about running out of space.
7. Which local LLM runtime is preferred for Q&A (Ollama, llama.cpp, vLLM, other), and must it be offline-only? ollama, but open to others if they are more optimal for the 4 pillars
8. Should plugin installation be allowed to fetch from the internet (pip/git) or only from local sources (zip/folder/wheel)? yes. 
9. Do you want the tray companion to support a “panic pause capture” action (no deletion), and should it require confirmation? no, capture is guaranteed, privacy is enforced on the metadata only.
10. Are you willing to accept lossless delta-encoding/segment containers as “raw” (reconstructable exact pixels), or must each frame be a standalone image file? a standalone image file, as the processing pipeline would have to be drastically changed to support the delta imho, open to it changing if it is better for the 4 pillars though.
11. Do you need per-day “immutable freeze” checkpoints (e.g., end-of-day commit) to strengthen proof/audit? yes that would be great. i intend this to be my memory assistant for the rest of my life once we get it working. so the databases and whatnot will ultimately need to be able to be transferred to a new machine, make sure nothing could interfere with that like encryption or configs or etc.
12. Should the UI default to “conservative answers only” (citations required) even if it means more “I don’t know yet” responses? yes. never ever make shit up. be deterministic when possible and clearly state when you cannot cite or be deterministic.


