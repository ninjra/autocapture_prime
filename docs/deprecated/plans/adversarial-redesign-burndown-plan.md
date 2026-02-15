# Plan: Adversarial Redesign Burn-Down To Zero (Soak-Ready)

**Generated**: 2026-02-09
**Estimated Complexity**: High

## Overview
Burn down the remaining adversarial redesign items (currently 59 IDs not `implemented`) to reach:
- `tools/run_adversarial_redesign_coverage.sh` passes with `AUTOCAPTURE_REQUIRE_ADVERSARIAL_REDESIGN_IMPLEMENTED=1`.
- Deterministic, resource-bounded operation suitable for a 24h WSL soak (capture always-on; heavy processing only after idle >= 300s).
- Repo hygiene: minimal/no “unfinished work” markers; tests/gates cover every behavior change.

Strategy:
- Implement in vertical slices aligned to the 4 pillars (Performance, Accuracy, Security, Citeability) and soak requirements.
- For each redesign ID: add/confirm (1) implementation, (2) deterministic validator test, (3) traceability mapping update in `tools/traceability/adversarial_redesign_map.json`.
- Keep WSL stable by running targeted tests per slice (avoid full-suite loops until the end).

## Prerequisites
- Python venv ready: `.venv/` (existing).
- WSL has sufficient disk space on primary + spillover (secondary) mount.
- `ffmpeg` is installed (already done per user) for optional video fixtures, but video remains disabled by default.
- Gate commands to run during development (low resource):
  - `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 bash tools/run_adversarial_redesign_coverage.sh`

## One Round Of Questions (Needed Upfront)
1. **Consent semantics (SEC-08)**: Is “kernel running + capture enabled in config” sufficient as explicit consent (ledger a `capture_started` event on boot), or do you want an explicit one-time `autocapture consent --accept` command stored in state?
2. **Plugin signing key storage (EXT-11)**: OK to store a local signing key under `data_dir/vault/` (with permissions locked down) and rotate via a CLI command, or do you want to reuse existing keyring machinery?
3. **UI scope for adversarial UX items**: To satisfy UX validators, is minimal web UI (static HTML/JS) acceptable even though the tray/UI will be replaced later, as long as API+CLI are correct?

If you answer “yes/ok/minimal” to all three, implementation can proceed without further branching decisions.

## Sprint 1: Make The Gate Actionable (Traceability + Missing Validators)
**Goal**: Ensure every remaining ID has a concrete validator plan and that the gap report is never truncated/ambiguous.
**Demo/Validation**:
- `python3 tools/list_adversarial_redesign_gaps.py` produces a complete report with no truncation.
- Gate still fails, but only for truly unimplemented items (no “missing file paths” in evidence/validators).

### Task 1.1: Normalize Traceability Map For All Remaining IDs
- **Location**: `tools/traceability/adversarial_redesign_map.json`
- **Description**: Add explicit entries for each remaining ID with:
  - accurate `evidence` file paths (no globs like `plugins/builtin/*`)
  - `validators` pointing to deterministic tests
  - `notes` capturing any deliberate scope choices (eg “tray repo will implement UI indicator; this repo provides API+ledger events”)
- **Complexity**: 6/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - Every remaining ID is present in map file.
  - No entry references non-existent files.
- **Validation**:
  - `python3 tools/traceability/generate_adversarial_redesign_traceability.py`
  - `python3 tools/traceability/validate_adversarial_redesign_traceability.py` (structural)

### Task 1.2: Improve Gap Reporting For Full Fidelity Output
- **Location**: `tools/list_adversarial_redesign_gaps.py`, `docs/reports/`
- **Description**: Ensure the report includes the full set of IDs (no truncation in generated file) and includes the enforcement/regression text from the source doc for each missing/partial item.
- **Complexity**: 4/10
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Report lists every non-implemented ID with complete title + required enforcement + required validator.
- **Validation**:
  - Unit test: `tests/test_adversarial_gap_report_complete.py` (to add)

## Sprint 2: Execution Guarantees (EXEC-04..EXEC-07, Determinism)
**Goal**: Make the pipeline replayable, deterministic, and crash-recoverable without mutating originals.
**Demo/Validation**:
- Run replay on a fixture dataset and confirm derived artifacts get new IDs while raw evidence IDs remain unchanged.

### Task 2.1: Implement Replay As “New Derived Artifacts Only”
- **Location**: `autocapture_nx/kernel/replay.py`, `autocapture_nx/kernel/derived_records.py`, `autocapture_nx/kernel/proof_bundle.py`, `autocapture_nx/cli.py`
- **Description**:
  - Add a replay mode that reads an existing data_dir and re-runs processing/indexing into a new run namespace.
  - Ensure it never overwrites raw media/evidence blobs; derived artifacts are content-addressed with lineage pointers.
- **Complexity**: 8/10
- **Dependencies**: Sprint 1 traceability normalization
- **Acceptance Criteria**:
  - Replay produces new derived artifact IDs and manifests.
  - Ledger/journal append-only entries record replay attempt and outputs.
- **Validation**:
  - Add `tests/test_replay_produces_new_artifacts.py`

### Task 2.2: Determinism Enforcement Sweep
- **Location**: `autocapture_nx/kernel/query.py`, `plugins/builtin/retrieval_basic/plugin.py`, `autocapture_nx/kernel/canonical_json.py`, `autocapture_nx/kernel/rng.py`
- **Description**:
  - Remove/guard uses of `time.time()`, `datetime.now()`, randomized ordering, unordered dict iteration in critical paths.
  - Enforce stable sorts for retrieval and query assembly.
- **Complexity**: 7/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - Given identical inputs, query results are byte-for-byte stable (including ordering).
- **Validation**:
  - Add `tests/test_deterministic_retrieval_order.py`

### Task 2.3: Two-Phase Commit For Evidence Writes (Blob → Metadata → Journal → Ledger)
- **Location**: storage plugins under `plugins/builtin/storage_*`, `plugins/builtin/journal_basic/plugin.py`, `plugins/builtin/ledger_basic/plugin.py`
- **Description**:
  - Implement staged write markers to allow crash recovery without partial “committed” evidence.
  - Add rollback markers (append-only) if a stage fails.
- **Complexity**: 9/10
- **Dependencies**: Task 2.2 (deterministic IDs/records)
- **Acceptance Criteria**:
  - Crash between stages results in either (a) clean retry, or (b) explicit “rolled back” marker; no dangling references.
- **Validation**:
  - Add `tests/test_two_phase_commit_recovery.py`

### Task 2.4: On-Query Extraction Scheduling (No Reprocessing On Query)
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/processing/idle.py`, `autocapture/web/routes/query.py`
- **Description**:
  - If extraction is missing, query must report “blocked/pending” and optionally schedule a job rather than doing work inline.
- **Complexity**: 7/10
- **Dependencies**: Conductor/scheduler modules already present
- **Acceptance Criteria**:
  - Query never triggers media processing inline.
  - Scheduling creates a ledgered job record.
- **Validation**:
  - Add `tests/test_schedule_extract_from_query.py`

## Sprint 3: Extension System Hardening (EXT-01..EXT-12)
**Goal**: Safe, deterministic plugin lifecycle with local install, approvals, rollback, compatibility, and observability.
**Demo/Validation**:
- Install a local plugin path in dry-run, see permission diff, apply, then rollback, with full history.

### Task 3.1: Plugin Lifecycle State Machine (installed→locked→approved→enabled→healthy)
- **Location**: `autocapture_nx/plugin_system/manager.py`, `autocapture_nx/plugin_system/registry.py`, `autocapture/web/routes/plugins.py`
- **Complexity**: 8/10
- **Validation**: `tests/test_plugin_lifecycle_state_machine.py`

### Task 3.2: Local-Only Plugin Install With Manifest Validation + Preview
- **Location**: `autocapture_nx/plugin_system/manager.py`, `autocapture_nx/plugin_system/manifest.py`, `contracts/plugin_manifest.schema.json`, `config/plugin_locks.json`
- **Complexity**: 7/10
- **Validation**: `tests/test_plugin_install_local_path.py`

### Task 3.3: Update + Rollback With Lock History + Permission Diffs
- **Location**: `autocapture_nx/plugin_system/manager.py`, `autocapture/web/routes/plugins.py`, `autocapture/web/ui/index.html`
- **Complexity**: 8/10
- **Validation**: `tests/test_plugin_update_rollback.py`

### Task 3.4: Compatibility Gate (kernel_api_version + contract_lock_hash)
- **Location**: `autocapture_nx/plugin_system/contracts.py`, `autocapture_nx/plugin_system/registry.py`, `contracts/lock.json`
- **Complexity**: 6/10
- **Validation**: `tests/test_plugin_compatibility_gate.py`

### Task 3.5: Plugins Plan/Apply Dry-Run (Capability Graph + Conflicts)
- **Location**: `autocapture_nx/plugin_system/manager.py`, `autocapture_nx/plugin_system/trace.py`
- **Complexity**: 7/10
- **Validation**: `tests/test_plugins_plan_output_deterministic.py`

### Task 3.6: Permission Prompt Required For Privileged Changes
- **Location**: `autocapture_nx/plugin_system/sandbox.py`, `autocapture_nx/kernel/policy_gate.py`, `autocapture_nx/plugin_system/manager.py`
- **Complexity**: 7/10
- **Validation**: `tests/test_plugin_permission_prompt_required.py`

### Task 3.7: In-Process Allowlist Enforcement
- **Location**: `autocapture_nx/plugin_system/runtime.py`, `autocapture_nx/plugin_system/registry.py`
- **Complexity**: 5/10
- **Validation**: `tests/test_inproc_allowlist_enforced.py`

### Task 3.8: Plugin Crash-Loop Quarantine
- **Location**: `autocapture_nx/plugin_system/runtime.py`, `autocapture_nx/kernel/state_tape.py`
- **Complexity**: 7/10
- **Validation**: `tests/test_plugin_crash_loop_quarantine.py`

### Task 3.9: Plugin Logs Endpoint (Localhost Only)
- **Location**: `autocapture/web/routes/plugins.py`, `autocapture_nx/plugin_system/trace.py`
- **Complexity**: 4/10
- **Validation**: `tests/test_plugin_logs_endpoint.py`

### Task 3.10: Lockfile SBOM + Signature Verification
- **Location**: `config/plugin_locks.json`, `autocapture_nx/plugin_system/manager.py`, `autocapture_nx/kernel/backup_bundle.py`
- **Complexity**: 9/10
- **Validation**:
  - `tests/test_plugin_lock_contains_sbom.py`
  - `tests/test_plugin_locks_signature_verified.py`

### Task 3.11: Capabilities Matrix Endpoint
- **Location**: `autocapture/web/routes/health.py`, `autocapture/web/routes/plugins.py`, `autocapture_nx/kernel/doctor.py`
- **Complexity**: 5/10
- **Validation**: `tests/test_capabilities_matrix_endpoint.py`

## Sprint 4: Metadata & Provenance Contracts (META-04, META-07..META-09)
**Goal**: Every derived artifact has lineage; every run records determinism inputs; query includes evaluation metadata.
**Demo/Validation**:
- Export a proof bundle and verify lineage graph and determinism manifest.

### Task 4.1: Enforce Schema Versions Everywhere
- **Location**: `contracts/*.schema.json`, `autocapture_nx/kernel/canonical_json.py`, `autocapture_nx/kernel/provenance.py`
- **Complexity**: 6/10
- **Validation**: `tests/test_schema_version_enforced.py`

### Task 4.2: Artifact Manifest Lineage (Content-Addressed)
- **Location**: `autocapture_nx/kernel/derived_records.py`, `autocapture_nx/kernel/state_tape.py`
- **Complexity**: 9/10
- **Validation**: `tests/test_artifact_manifest_lineage.py`

### Task 4.3: Add Evaluation Contract To Query Outputs
- **Location**: `contracts/evaluation.schema.json` (add), `autocapture_nx/kernel/query.py`
- **Complexity**: 6/10
- **Validation**: `tests/test_query_evaluation_fields.py`

### Task 4.4: Determinism Inputs Manifest
- **Location**: `contracts/run_manifest.schema.json` (add), `autocapture_nx/kernel/loader.py`, `autocapture_nx/kernel/state_tape.py`
- **Complexity**: 7/10
- **Validation**: `tests/test_manifest_determinism_fields.py`

## Sprint 5: Ops & Perf Gates (OPS-05..OPS-08, PERF-01..PERF-08)
**Goal**: Soak test reliability: throughput baseline, budgets enforced, GPU failures fail closed, and operator actions are ledgered.

### Task 5.1: Operator Commands Ledgered (Start/Stop Capture, Pause/Resume Processing)
- **Location**: `autocapture_nx/cli.py`, `plugins/builtin/ledger_basic/plugin.py`
- **Validation**: `tests/test_operator_commands_ledgered.py`

### Task 5.2: Doctor Reports DB Versions + Migrations
- **Location**: `autocapture_nx/kernel/doctor.py`, `autocapture_nx/storage/migrations.py`
- **Validation**: `tests/test_doctor_reports_db_versions.py`

### Task 5.3: Self-Test Harness (Fast, Deterministic)
- **Location**: `tools/run_fixture_pipeline.py`, `autocapture_nx/ux/fixture.py`
- **Validation**: `tests/test_self_test_harness.py`

### Task 5.4: Capture Throughput Baseline (0.5s Active)
- **Location**: `plugins/builtin/capture_screenshot_windows/plugin.py`, `autocapture_nx/capture/screenshot_policy.py`
- **Validation**: `tests/test_capture_throughput_baseline.py`

### Task 5.5: Incremental Indexing + Extractor Cache Keys
- **Location**: `autocapture/indexing/lexical.py`, `autocapture/indexing/vector.py`, `autocapture_nx/processing/sst/extract.py`
- **Validation**:
  - `tests/test_incremental_indexing.py`
  - `tests/test_extractor_cache_keys.py`

### Task 5.6: WSL2 Job Roundtrip + GPU Offload Flag
- **Location**: `autocapture_nx/runtime/scheduler.py`, `plugins/builtin/vlm_*`
- **Validation**:
  - `tests/test_wsl2_job_roundtrip.py`
  - `tests/test_gpu_offload_flagged.py`

### Task 5.7: Proof Bundle Streaming Memory
- **Location**: `autocapture_nx/kernel/proof_bundle.py`
- **Validation**: `tests/test_proof_bundle_streaming_memory.py`

### Task 5.8: SLO Budget Regression Gate
- **Location**: `tools/gate_perf.py`, `autocapture/web/routes/metrics.py`
- **Validation**: `tests/test_slo_budget_regression_gate.py`

## Sprint 6: QA, Security, UX (QA-*, SEC-*, UX-*)
**Goal**: End-to-end confidence: golden query tests, crash recovery tests, secrets/redaction, minimal UI to satisfy UX validators.

### Task 6.1: Golden Query Harness Using Checked-in Fixtures
- **Location**: `tests/test_query_golden.py`, `docs/test sample/`
- **Validation**: `tests/test_query_golden.py`

### Task 6.2: Crash Recovery Chaos (Bounded)
- **Location**: `tests/test_crash_recovery_chaos.py`
- **Validation**: `tests/test_crash_recovery_chaos.py`

### Task 6.3: Config Fuzz + Security Guards
- **Location**: `autocapture/config/validator.py`, `tests/test_config_fuzz.py`, `tests/test_security_guards.py`

### Task 6.4: PII Redaction At Export/Egress Only (Raw-First Preserved)
- **Location**: `autocapture/privacy/redaction.py` (add), `autocapture/egress/sanitize.py` (add)
- **Validation**: `tests/test_redaction_deterministic.py`

### Task 6.5: Key Rotation / Rewrap Plan
- **Location**: `autocapture/crypto/keyring.py`, `plugins/builtin/storage_encrypted/plugin.py`
- **Validation**: `tests/test_key_rotation_rewrap_plan.py`

### Task 6.6: Proof Bundle Signing + Verification
- **Location**: `autocapture_nx/kernel/proof_bundle.py`, `autocapture/crypto/dpapi.py`
- **Validation**: `tests/test_proof_bundle_signature_verifies.py`

### Task 6.7: Secrets Hygiene Gate + Log Redaction
- **Location**: `tools/gate_secrets.py` (add), `autocapture_nx/kernel/logging.py`
- **Validation**:
  - `tests/test_log_redaction.py`
  - `tools/gate_secrets.py`

### Task 6.8: Consent + Start/Stop Ledger Events (No Tray Repo Dependency)
- **Location**: `autocapture/web/ui/index.html`, `autocapture/web/routes/run.py`, `plugins/builtin/ledger_basic/plugin.py`
- **Validation**: `tests/test_capture_start_stop_ledgered.py`

### Task 6.9: Minimal UX Work To Satisfy Validators (Static UI)
- **Location**: `autocapture/web/ui/index.html`, `autocapture/web/ui/app.js`, `autocapture/web/routes/*`
- **Validation**:
  - `tests/test_ui_dashboard_renders.py`
  - `tests/test_pause_resume_idempotent.py`
  - `tests/test_run_detail_contains_provenance.py`
  - `tests/test_query_ui_shows_blocked_extract.py`
  - `tests/test_extension_manager_core_flows.py`
  - `tests/test_dangerous_toggle_requires_confirm.py`
  - `tests/test_accessibility_smoke.py`
  - `tests/test_error_to_diagnostics_flow.py`
  - `tests/test_config_diff_viewer.py`
  - `tests/test_docs_consistency_smoke.py`

## Sprint 7: RD Roadmap Items (RD-01..RD-04) As Verifiable Docs
**Goal**: Replace `(planning)` placeholders with versioned docs + tests so they’re traceable and enforced.
**Demo/Validation**:
- `tools/run_adversarial_redesign_coverage.sh` passes with RD items marked implemented and validated.

### Task 7.1: Add/Update Roadmap Sections + Milestone Criteria
- **Location**: `docs/roadmap.md`, `docs/runbook.md`
- **Validation**: `tests/test_roadmap_sections_present.py` (to add)

## Testing Strategy
- Per-sprint: run only the validators introduced/modified in that sprint.
- Daily: run `bash tools/run_adversarial_redesign_coverage.sh` with thread caps.
- Before soak: run the fixture pipeline end-to-end (screenshot-only by default) and confirm:
  - capture writes never drop events (spool fallback + flush sentinel)
  - ingestion produces metadata-only queries (no media reprocessing on query)
  - GPU-required steps fail closed if unavailable

## Potential Risks & Gotchas
- Some adversarial evidence paths in the source doc use globs or refer to external repos (tray/UI). Mitigation: map to this repo’s actual implementation and document the cross-repo boundary in `notes`.
- “Never partial data” implies two-phase commit and explicit incomplete markers; without this, crash loops will create ambiguous state. Mitigation: Sprint 2 Task 2.3.
- UX tests can become flaky if using a real browser. Mitigation: prefer DOM-level static checks in Python for these validators.

## Rollback Plan
- Each sprint lands in a separate PR/commit group; rollback is `git revert` of that sprint’s merge commit.
- Plugin lock changes are append-only with history; rollback via `autocapture plugins rollback --to <lock_id>`.

