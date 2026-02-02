# Plan: Redteam Docs Implementation

**Generated**: 2026-02-02
**Estimated Complexity**: High

## Overview
Implement the requirements in `docs/redteam-plan.md`, `docs/redteam-specs.md`, and `docs/blueprints/autocapture_nx_blueprint.md` (plus its spec scaffolding in `docs/spec/autocapture_nx_blueprint_2026-01-24.md`) on the NX stack, with emphasis on capture completeness, foreground gating, storage pressure handling, multi-plugin orchestration, traceability, and accessibility-first UX. NX (`autocapture_nx`) is the sole target; legacy `autocapture/` is deprecated for new work. All non‑negotiables (localhost-only, no deletion, raw-first, foreground gating, idle budgets, citations, tray restrictions) remain enforced and auditable.

## Prerequisites
- Windows 11 host + WSL/Linux backend available for doctor and path validation.
- FFmpeg available (bundled or system) for capture checks.
- Python test environment capable of running `pytest` (MOD-021 suites).
- UI assets in `autocapture/web/ui/` present (re-upload repomix if any missing UI files).
- Canonical data dir decided: recommend `D:\autocapture` mapped to `/mnt/d/autocapture` to keep Windows host capture + WSL backend on one canonical store.

## Sprint 0: Blueprint Alignment + Legacy Deprecation
**Goal**: Bring the blueprint spec into a valid, traceable state and formally deprecate legacy `autocapture/` surfaces.\n**Demo/Validation**:\n- `pytest tests/test_blueprint_spec_validation.py -q`\n\n### Task 0.1: Fill blueprint spec scaffolding\n- **Location**: `docs/spec/autocapture_nx_blueprint_2026-01-24.md`, `docs/blueprints/autocapture_nx_blueprint.md`\n- **Description**: Populate Source_Index/Coverage_Map/Modules/ADRs in the spec file to satisfy validator; reference blueprint items and map to modules/tests.\n- **Complexity**: 6\n- **Dependencies**: none\n- **Acceptance Criteria**:\n  - Spec validator passes and all SRC/MOD/ADR references are consistent.\n- **Validation**:\n  - `pytest tests/test_blueprint_spec_validation.py -q`\n\n### Task 0.2: Blueprint gap tracker (I001–I130)\n- **Location**: `docs/reports/blueprint-gap-2026-02-02.md`\n- **Description**: Enumerate all blueprint items (I001–I130), mark implemented vs missing, and reference modules/tests for implemented items. Use this tracker to gate subsequent sprints.\n- **Complexity**: 5\n- **Dependencies**: Task 0.1\n- **Acceptance Criteria**:\n  - Tracker lists every I### with status + module/test references.\n- **Validation**:\n  - Manual review; tracker referenced from subsequent sprints.\n\n### Task 0.3: Deprecate legacy `autocapture/` surfaces\n- **Location**: `autocapture/__init__.py`, `autocapture/ux/facade.py`, `README.md`, `autocapture/web/api.py`\n- **Description**: Add deprecation warnings and docs guidance directing usage to `autocapture_nx`. Ensure NX remains the canonical runtime and legacy modules are not extended.\n- **Complexity**: 3\n- **Dependencies**: none\n- **Acceptance Criteria**:\n  - Deprecation warnings are visible; docs point to NX entrypoints.\n- **Validation**:\n  - `pytest tests/test_ux_facade_parity.py -q` (ensure no runtime regressions).\n*** End Patch}]}***/success output ="Done!"}


## Sprint 1: Requirements Mapping & Safety Gates
**Goal**: Make the redteam requirements traceable to code/tests/ADRs and lock non-negotiables into deterministic gates.
**Demo/Validation**:
- Run `pytest tests/test_blueprint_spec_validation.py -q` (or equivalent spec gate).
- Run `pytest tests/test_no_deletion_mode.py -q` and `pytest tests/test_raw_first_local.py -q`.

### Task 1.1: Create/refresh SRC → module/ADR/test coverage map
- **Location**: `docs/redteam-specs.md`
- **Description**: Update Coverage_Map and Validation_Checklist entries to point to real module paths, ADRs, and tests for every SRC. Add missing MOD/ADR entries if needed.
- **Complexity**: 5
- **Dependencies**: none
- **Acceptance Criteria**:
  - Coverage_Map lists each SRC exactly once with module/ADR/test references.
  - Validation_Checklist items can be verified in-tree.
- **Validation**:
  - Manual scan + `pytest tests/test_blueprint_spec_validation.py -q` (or equivalent spec gate).

### Task 1.2: Add ADRs for key policy decisions (no-holes, storage pressure, foreground gating)
- **Location**: `docs/adr/`
- **Description**: Add ADRs documenting “no holes” media storage, storage pressure state machine, and foreground gating behavior; link SRC references.
- **Complexity**: 4
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - ADRs created with Sources and referenced by Coverage_Map.
- **Validation**:
  - ADR files readable; Coverage_Map updated.

### Task 1.3: Audit localhost-only binding enforcement
- **Location**: `autocapture/web/auth.py`, `autocapture/web/api.py`, `autocapture_nx/tray.py`, `contracts/config_schema.json`
- **Description**: Ensure bind host is forced to 127.0.0.1, config validation rejects other hosts, and UI/tray fail closed on non-loopback.
- **Complexity**: 3
- **Dependencies**: none
- **Acceptance Criteria**:
  - Remote bind attempts fail closed with explicit error.
- **Validation**:
  - `pytest tests/test_localhost_binding.py -q`

### Task 1.4: Lock “no deletion” policy into retention/compaction gates
- **Location**: `autocapture/storage/retention.py`, `autocapture/storage/compaction.py`, `autocapture/runtime/conductor.py`
- **Description**: Ensure retention/compaction paths are disabled or converted to archive-only modes; no delete endpoints or pruning remain accessible.
- **Complexity**: 4
- **Dependencies**: none
- **Acceptance Criteria**:
  - Retention paths do not delete evidence/media locally.
- **Validation**:
  - `pytest tests/test_no_deletion_mode.py -q`

## Sprint 2: Foreground Gating + Resource Budgets
**Goal**: Enforce “active user = capture only” with CPU/RAM <= 50% budgets; gate all heavy processing before enabling heavier pipelines.
**Demo/Validation**:
- Simulate user activity → heavy processing pauses; capture continues.

### Task 2.1: Tighten RuntimeGovernor enforcement (CPU/RAM caps, active gating)
- **Location**: `autocapture/runtime/governor.py`, `autocapture/runtime/budgets.py`, `autocapture/runtime/resources.py`
- **Description**: Ensure budgets enforce 50% CPU/RAM limits; active user forces ACTIVE_CAPTURE_ONLY.
- **Complexity**: 5
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Heavy jobs blocked when active or over budget; GPU allowed.
- **Validation**:
  - `pytest tests/test_resource_budget_enforcement.py -q` and `pytest tests/test_governor_gating.py -q`.

### Task 2.2: GPU concurrency cap enforcement
- **Location**: `autocapture/runtime/governor.py`, `autocapture/runtime/scheduler.py`
- **Description**: Enforce GPU concurrency caps in governor decisions; fail closed when limits are exceeded.
- **Complexity**: 4
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - GPU-heavy jobs respect concurrency limits under load.
- **Validation**:
  - Add `tests/test_gpu_concurrency_cap.py` (or extend `tests/test_gpu_lag_guard.py`).

### Task 2.3: Gate idle processing & query-time extraction
- **Location**: `autocapture/runtime/conductor.py`, `autocapture_nx/processing/idle.py`, `autocapture_nx/kernel/query.py`
- **Description**: Ensure idle extraction, OCR/VLM, embeddings only run when idle; add explicit “blocked: user active” reasons.
- **Complexity**: 5
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Query extraction blocked when active; UI reports reason.
- **Validation**:
  - `pytest tests/test_query_processing_status.py -q`.

### Task 2.4: Per-plugin/step work queue budgets
- **Location**: `autocapture_nx/processing/sst/pipeline.py`, `autocapture/runtime/scheduler.py`, `autocapture_nx/plugin_system/host.py`
- **Description**: Enforce max items/runtime/VRAM estimates per plugin; implement backoff on failure.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Plugin runs respect budgets and are preemptible; no implicit max-providers limit is enforced.
- **Validation**:
  - `pytest tests/test_plugin_host_timeout.py -q` and `pytest tests/test_resource_budgets.py -q`.

## Sprint 3: No-Holes Capture + Raw-First Storage
**Goal**: Always store raw pixels locally (vault for excluded), gate derived artifacts, and prevent local sanitization except explicit export.
**Demo/Validation**:
- Ingest an excluded frame → media_path is present, derived queue skipped.
- Run `pytest tests/test_raw_first_local.py -q`.

### Task 3.1: Add privacy-excluded capture semantics and vault storage
- **Location**: `autocapture_nx/capture/pipeline.py`, `autocapture_nx/kernel/frame_evidence.py`, `autocapture_nx/kernel/metadata_store.py`
- **Description**: Always persist raw pixels; when excluded, set `privacy_excluded=true`, write to vault namespace, and skip derived pipeline enqueue unless explicit opt-in exists.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - `media_path` never null for excluded frames; derived processing skips by default.
- **Validation**:
  - New/updated tests in `tests/test_raw_first_local.py` and `tests/test_storage_append_only.py`.

### Task 3.2: Implement MediaVault namespace + encryption-at-rest defaults
- **Location**: `autocapture/storage/keys.py`, `autocapture/storage/sqlcipher.py`, `autocapture_nx/kernel/loader.py`, `contracts/config_schema.json`
- **Description**: Add vault path handling and encryption capability with opt‑in migration (do not force by default). Key lifecycle prompts and migration UI added in Sprint 7.
- **Complexity**: 6
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Vault paths exist; encryption_required/enable states are enforced and doctor-checked; opt‑in migration path is available.
- **Validation**:
  - `pytest tests/test_storage_encrypted.py -q` and `pytest tests/test_keyring_require_protection.py -q`.

### Task 3.3: Move redaction/sanitization to explicit export only
- **Location**: `autocapture_nx/processing/sst/compliance.py`, `autocapture/ux/redaction.py`, `autocapture/web/routes/egress.py`
- **Description**: Ensure local derived artifacts are stored unredacted; redaction occurs only in export/egress pipeline.
- **Complexity**: 5
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Derived records remain raw; egress sanitizes.
- **Validation**:
  - `pytest tests/test_sanitizer_no_raw_pii.py -q`.

### Task 3.4: Capture defaults tuning (video + bitrate)
- **Location**: `config/default.json`, `contracts/config_schema.json`, `tests/test_config_defaults.py`
- **Description**: Ensure record_video defaults, bitrate guidance, and max_pending defaults align with spec for 4K/8K capture.
- **Complexity**: 3
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Defaults match spec; overrides accepted without schema changes.
- **Validation**:
  - `pytest tests/test_config_defaults.py -q`.

## Sprint 4: Storage Pressure + Heartbeat + Doctor + WSL Bridge
**Goal**: Degrade processing before capture under disk pressure, add heartbeat invariant, and make WSL+FFmpeg doctor deterministic.
**Demo/Validation**:
- Simulate disk pressure → processing pauses, capture continues; UI banner shows state and reason.

### Task 4.1: Storage pressure state machine (green/yellow/red/black)
- **Location**: `autocapture/storage/pressure.py`, `autocapture_nx/capture/pipeline.py`, `autocapture_nx/kernel/alerts.py`
- **Description**: Implement explicit state transitions and actions (pause processing → reduce bitrate → stop segments → halt capture). Emit events/alerts.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Yellow pauses processing; red reduces capture quality; black halts capture only as last resort.
- **Validation**:
  - `pytest tests/test_capture_disk_pressure_degrade.py -q`.

### Task 4.2: Heartbeat row + status integration
- **Location**: `autocapture_nx/kernel/telemetry.py`, `autocapture_nx/ux/facade.py`, `autocapture/web/ui/app.js`
- **Description**: Record heartbeat every N seconds with last frame timestamp, HID/event timestamp, queue sizes, disk free; expose in `/api/status` and UI banner.
- **Complexity**: 5
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Heartbeat visible; UI shows Capturing/Degraded/Stopped and last frame age.
- **Validation**:
  - Add tests in `tests/test_silence_alerts.py` or new heartbeat test.

### Task 4.3: Doctor WSL + FFmpeg validation
- **Location**: `autocapture_nx/kernel/loader.py`, `autocapture_nx/kernel/paths.py`, `autocapture_nx/capture/pipeline.py`
- **Description**: Detect WSL, choose valid storage root, validate actual path and FFmpeg availability; show explicit errors.
- **Complexity**: 5
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Doctor reports precise path and FFmpeg failures; WSL paths resolved deterministically.
- **Validation**:
  - `pytest tests/test_doctor_report_schema.py -q` and `pytest tests/test_wsl2_routing_integration.py -q`.

### Task 4.4: WSL bridge endpoints + dashboard storage widget
- **Location**: `autocapture/web/routes/storage.py`, `autocapture/web/routes/media.py`, `autocapture/web/ui/app.js`, `autocapture/web/ui/styles.css`
- **Description**: Add/extend WSL bridge endpoints for Windows↔WSL access (as needed) and implement a dashboard storage widget using `/api/storage/*` data.
- **API Proposal (draft)**:
  - `GET /api/wsl/bridge/status` → `{ ok, wsl_detected, host_os, linux_mounts: [...], data_dir_windows, data_dir_wsl, recommended_root, reason }`
  - `POST /api/wsl/bridge/resolve` (body: `{ windows_path? , wsl_path? }`) → `{ ok, windows_path, wsl_path, mapped, reason }`
  - `GET /api/wsl/bridge/validate?path=...&kind=data|config|media` → `{ ok, exists, writable, kind, reason }`
- **Complexity**: 4
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Storage widget renders capacity/forecast; bridge endpoints return expected paths/status.
- **Validation**:
  - `pytest tests/test_ui_routes.py -q` and manual UI check.

### Task 4.5: Tray/banner messaging for degraded capture
- **Location**: `autocapture_nx/tray.py`, `autocapture/web/ui/app.js`, `autocapture/web/ui/styles.css`
- **Description**: Ensure tray tooltip/menu and UI banner reflect disk pressure states; no capture pause actions added.
- **Complexity**: 3
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Tray and UI show clear states; no pause/delete actions added to tray.
- **Validation**:
  - `pytest tests/test_tray_menu_policy.py -q`.

## Sprint 5: Multi-Plugin Orchestration + Isolation
**Goal**: Support multi-plugin fanout per step, ensure plugin isolation, and persist artifact + run metadata.
**Demo/Validation**:
- Configure two OCR plugins; both run; artifacts stored separately with provenance.

### Task 5.1: Scalar → list routing compatibility
- **Location**: `contracts/config_schema.json`, `autocapture/ux/plugin_options.py`, `autocapture_nx/processing/sst/pipeline.py`
- **Description**: Accept list or scalar for routing; preserve backward compatibility; do not impose max-providers limit unless user sets it explicitly.
- **Complexity**: 4
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Both forms accepted; list triggers fanout; default max_providers=0 (unlimited).
- **Validation**:
  - `pytest tests/test_plugin_capability_policies.py -q`.

### Task 5.2: Plugin-provided settings schema/defaults plumbing
- **Location**: `autocapture_nx/plugin_system/manifest.py`, `autocapture_nx/plugin_system/manager.py`, `autocapture/web/routes/plugins.py`
- **Description**: Ensure plugin manifests expose `settings_schema` and `default_settings`; UI can fetch and render them.
- **Complexity**: 4
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - `/api/plugins/{id}/settings` (or equivalent) returns schema + defaults.
- **Validation**:
  - `pytest tests/test_plugin_manager_nx.py -q`.

### Task 5.3: ArtifactRecord + PluginRun stores
- **Location**: `autocapture_nx/kernel/derived_records.py`, `autocapture_nx/kernel/metadata_store.py`, `contracts/evidence.schema.json`
- **Description**: Store outputs keyed by (frame_id, artifact_type, engine, engine_version); store plugin runs with config hash + inputs/outputs.
- **Complexity**: 6
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Artifacts immutable; plugin run metadata persists and is queryable.
- **Validation**:
  - `pytest tests/test_derived_records.py -q`.

### Task 5.4: Enforce plugin isolation + audit log
- **Location**: `autocapture_nx/plugin_system/host.py`, `autocapture_nx/kernel/audit.py`
- **Description**: Prevent plugin mutation of other outputs or global config; log privileged behaviors append-only.
- **Complexity**: 5
- **Dependencies**: Task 5.3
- **Acceptance Criteria**:
  - Isolation enforced; audit entries created for privileged actions.
- **Validation**:
  - `pytest tests/test_plugin_exec_audit.py -q`.

## Sprint 6: Trace API + Evidence UX
**Goal**: Provide trace endpoints for frame/event with full provenance and evidence overlays by default.
**Demo/Validation**:
- `/api/trace/frame/{id}` returns metadata + artifacts; UI shows overlayed evidence and a timeline/DAG view.

### Task 6.1: Add trace endpoints and payloads
- **Location**: `autocapture/web/routes/trace.py`, `autocapture_nx/ux/facade.py`
- **Description**: Add `/api/trace/frame/{frame_id}` and `/api/trace/event/{event_id}`; include artifacts, plugin runs, ledger entries.
- **Complexity**: 5
- **Dependencies**: Task 5.3
- **Acceptance Criteria**:
  - New endpoints respond with full trace payload.
- **Validation**:
  - `pytest tests/test_trace_facade.py -q`.

### Task 6.2: Citable overlays as default evidence view
- **Location**: `autocapture/web/ui/app.js`, `autocapture/web/ui/styles.css`, `autocapture/web/routes/citations.py`
- **Description**: Default evidence view shows screenshot with bbox/span highlights; clicking span filters evidence list.
- **Complexity**: 4
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - UI shows overlay and span filtering works.
- **Validation**:
  - `pytest tests/test_citation_overlay_contract.py -q`.

### Task 6.3: UI Trace Viewer timeline + DAG
- **Location**: `autocapture/web/ui/app.js`, `autocapture/web/ui/styles.css`
- **Description**: Add synchronized timeline + DAG visualization for trace results.
- **Complexity**: 5
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Timeline + DAG view renders and links to artifacts.
- **Validation**:
  - Manual UI check + `pytest tests/test_ui_accessibility.py -q`.

### Task 6.4: Ensure citations required by default + uncitable handling
- **Location**: `autocapture/memory/answer_orchestrator.py`, `autocapture/memory/verifier.py`, `autocapture_nx/kernel/query.py`
- **Description**: Ensure responses fail closed without citations; return explicit “uncitable/indeterminate” message when evidence missing.
- **Complexity**: 3
- **Dependencies**: none
- **Acceptance Criteria**:
  - No fabricated answers; uncitable responses are explicit.
- **Validation**:
  - `pytest tests/test_query_citations_required.py -q`.

## Sprint 7: UX Presets + Policy Transparency + Clipboard + Now/Rewind
**Goal**: Accessibility-first settings, policy transparency, clipboard capture with sensitivity, key backup prompts, and safe-mode navigation.
**Demo/Validation**:
- Preset cards + advanced accordion; policy badges shown; clipboard captured locally and blocked from cloud.

### Task 7.1: `/api/settings/schema` contract
- **Location**: `autocapture/web/routes/settings.py`, `autocapture_nx/ux/settings_schema.py`
- **Description**: Ensure schema endpoint returns defaults, current values, groupings, and descriptions; add tests.
- **Complexity**: 4
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Endpoint payload matches spec contract.
- **Validation**:
  - Add `tests/test_settings_schema_endpoint.py` (or extend `tests/test_config.py`).

### Task 7.2: Preset/advanced settings UX + grouping metadata
- **Location**: `contracts/config_schema.json`, `autocapture_nx/ux/settings_schema.py`, `autocapture/web/ui/app.js`
- **Description**: Add `ui_group/ui_subgroup/advanced/order/sensitive` metadata, emit defaults+current+groupings; implement preset cards and “show only overrides.” Gate UI changes behind a feature flag.
- **Complexity**: 6
- **Dependencies**: Task 7.1
- **Acceptance Criteria**:
  - Presets apply config patches; advanced view collapsible; overrides-only toggle works.
- **Validation**:
  - `pytest tests/test_settings_preview_tokens.py -q`.

### Task 7.3: Per-plugin settings UX (collapsed, defaults summary, overrides count)
- **Location**: `autocapture/web/ui/app.js`, `autocapture/web/ui/styles.css`, `autocapture/web/routes/plugins.py`
- **Description**: Always-collapsed plugin settings panels; “Using defaults” / “Overrides: N” summary; reset to defaults control. Gate UI changes behind a feature flag.
- **Complexity**: 5
- **Dependencies**: Task 5.2
- **Acceptance Criteria**:
  - Plugin panels default-collapsed with clear status and reset button.
- **Validation**:
  - Manual UI check + `pytest tests/test_ui_accessibility.py -q`.

### Task 7.4: Cognitive Safe Mode navigation
- **Location**: `autocapture/web/ui/index.html`, `autocapture/web/ui/app.js`, `autocapture/web/ui/styles.css`
- **Description**: Default nav shows Now/Rewind/Search/Status; settings/plugins secondary. Gate UI changes behind a feature flag.
- **Complexity**: 4
- **Dependencies**: Task 7.2
- **Acceptance Criteria**:
  - Default UI opens on Now; navigation order matches spec.
- **Validation**:
  - Manual UI check + `pytest tests/test_ui_accessibility.py -q`.

### Task 7.5: PolicyGate badges + egress sanitization UI
- **Location**: `autocapture/plugins/policy_gate.py`, `autocapture/web/ui/app.js`, `autocapture/web/routes/egress.py`
- **Description**: Surface per-plugin data handling badges; enforce no cloud images by default; ensure egress sanitization only on export.
- **Complexity**: 5
- **Dependencies**: Task 3.3
- **Acceptance Criteria**:
  - Badges reflect policy; blocked egress explains why.
- **Validation**:
  - `pytest tests/test_policy_gate.py -q`.

### Task 7.6: Encryption opt‑in migration
- **Location**: `autocapture_nx/kernel/loader.py`, `autocapture_nx/kernel/keyring.py`, `autocapture/web/ui/app.js`, `contracts/config_schema.json`
- **Description**: Add opt‑in migration flow to enable encryption-at-rest for existing installs; store migration state and ensure doctor surfaces status.
- **Complexity**: 5
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Opt‑in flow available; migration state recorded; doctor reports status.
- **Validation**:
  - Add/extend `tests/test_storage_migrations.py`.

### Task 7.7: Key backup status + first-run prompt + export flow
- **Location**: `autocapture_nx/kernel/keyring.py`, `autocapture_nx/kernel/key_rotation.py`, `autocapture/web/ui/app.js`, `autocapture_nx/kernel/audit.py`
- **Description**: Show backup status in dashboard; add first-run prompt; add local export flow (USB path) with audit logging.
- **Complexity**: 5
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Backup status visible; first-run prompt shown; export writes keys locally and logs audit entry.
- **Validation**:
  - `pytest tests/test_key_export_import_roundtrip.py -q`.

### Task 7.8: Clipboard capture with sensitive default + cloud block
- **Location**: `config/default.json`, `contracts/config_schema.json`, `autocapture_nx/processing/idle.py`, `autocapture/plugins/policy_gate.py`
- **Description**: Enable clipboard capture by default; mark sensitive; block cloud plugins from clipboard-derived text.
- **Complexity**: 4
- **Dependencies**: Task 3.3
- **Acceptance Criteria**:
  - Clipboard captured locally; no cloud egress.
- **Validation**:
  - `pytest tests/test_clipboard_capture.py -q`.

### Task 7.9: Now/Rewind/Search UX actions
- **Location**: `autocapture/web/routes/query.py`, `autocapture/web/routes/timeline.py`, `autocapture_nx/ux/facade.py`, `autocapture/web/ui/app.js`
- **Description**: Add `/api/now` and “rewind 5 minutes” UX action; default search window = last 60 minutes with app/window cue.
- **Complexity**: 5
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Now/Rewind/Search panels respond quickly with frame/event context.
- **Validation**:
  - `pytest tests/test_retrieval_timeline_refs.py -q`.

## Testing Strategy
- Run focused suites per sprint (listed above) plus `pytest tests/test_pillar_gates_report.py -q` at end.
- Add deterministic tests for new behaviors (heartbeat, no-holes, storage pressure states, multi-plugin fanout, settings schema).
- Manual UI verification for presets, status banner, evidence overlays, timeline/DAG, and navigation order.

## Potential Risks & Gotchas
- WSL path translation may still fail if Windows drives are not mounted; add explicit doctor guidance and fallback paths.
- Disabling local redaction could expose sensitive data in derived artifacts; ensure export-only sanitization is airtight.
- Multi-plugin fanout could increase load; enforce budgets and ensure foreground gating is respected.
- Retention/compaction disabling may impact disk growth; add archive/migrate options to avoid deletion.

## Rollback Plan
- Revert config schema changes and disable new UI paths; keep previous defaults.
- Toggle new features behind config flags to allow immediate rollback.
- Restore prior retention behavior only if explicitly requested (still no deletions by default).
