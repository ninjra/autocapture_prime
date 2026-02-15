# Plan: Autocapture Prime Adversarial Redesign (Coverage To Zero)

**Generated**: 2026-02-08
**Estimated Complexity**: High

## Overview
Drive `tools/run_adversarial_redesign_coverage.sh` to `issues=0` while preserving the non-negotiables:
localhost-only, no local deletion, raw-first local store, foreground gating, idle CPU/RAM budgets, and citeable answers (citations by default).

This plan is ordered to prioritize the 4 pillars (Performance, Accuracy, Security, Citeability) while keeping WSL stable (avoid subprocess storms and avoid heavy parallelism).

## Prerequisites
- WSL: run tests single-threaded (no xdist).
- `ffmpeg` installed (Windows + WSL if capture can run in either environment).
- Repo up to date on `main` (use `git fetch` + `git pull --ff-only` in your own workflow as needed).

## Sprint 1: Coverage Unblockers + WSL Stability
**Goal**: Remove “missing” statuses that are purely traceability/test file gaps; ensure boot/query do not spawn excessive plugin hosts.
**Demo/Validation**:
- `bash tools/run_adversarial_redesign_coverage.sh` shows decreasing `issues`.
- `pytest -q` for newly added tests passes.

### Task 1.1: Eliminate Delete-In-Recovery Everywhere
- **Location**: `autocapture_nx/kernel/loader.py`
- **Description**: Replace any `unlink()` or destructive cleanup during recovery with archive/quarantine moves; ledger/journal before/after.
- **Acceptance Criteria**:
  - No `unlink()` used for recovery cleanup.
  - Recovery action is journaled + ledgered with deterministic sample fields.
- **Validation**:
  - `pytest -q tests/test_recovery_audit_entries.py`

### Task 1.2: Policy Snapshot Evidence + Proof Bundle Verification
- **Location**: `autocapture_nx/kernel/policy_snapshot.py`, `autocapture_nx/kernel/proof_bundle.py`, `plugins/builtin/ledger_basic/plugin.py`
- **Description**: Persist policy snapshots by hash and include in proof bundles; ensure verification detects missing/mismatch.
- **Acceptance Criteria**:
  - Ledger entries carry a policy snapshot hash.
  - Proof bundle includes all referenced snapshots.
- **Validation**:
  - `pytest -q tests/test_policy_snapshot_exported.py`

### Task 1.3: Plugin Provenance In Run Manifest
- **Location**: `autocapture_nx/kernel/loader.py`
- **Description**: Record per-plugin provenance in run manifest from `config/plugin_locks.json`.
- **Acceptance Criteria**:
  - `system.run_manifest` includes `plugin_provenance` with hashes + permissions.
- **Validation**:
  - `pytest -q tests/test_plugin_provenance_in_manifest.py`

### Task 1.4: Subprocess Timeout Kill Path Regression Test
- **Location**: `autocapture_nx/plugin_system/host.py`, `tests/test_plugin_timeout_killed.py`
- **Description**: Ensure RPC timeouts terminate plugin subprocess (best-effort) and don’t leak processes.
- **Acceptance Criteria**:
  - Timeout kills underlying subprocess.
- **Validation**:
  - `pytest -q tests/test_plugin_timeout_killed.py`

## Sprint 2: Operator & Health (CLI + API First)
**Goal**: Implement missing OPS/EXEC health + diagnostics items needed for 24/7 ops.
**Demo/Validation**:
- `/health` includes a stable summary and component matrix.
- `autocapture doctor bundle` produces deterministic zip with redaction on export boundaries.

### Task 2.1: Structured JSONL Logging + Correlation IDs (OPS-01)
- **Location**: `autocapture_nx/kernel/logging.py`, `autocapture/web/api.py`, `autocapture_nx/plugin_system/host_runner.py`
- **Description**: Add JSONL logs with `run_id/job_id/plugin_id` correlation, rotation, and redaction hooks.
- **Validation**:
  - `pytest -q tests/test_logs_have_correlation_ids.py`

### Task 2.2: Health Matrix (EXEC-08, OPS-04)
- **Location**: `autocapture_nx/kernel/doctor.py`, `autocapture/web/routes/health.py`
- **Description**: Stable health summary + component matrix (capture, OCR, VLM, indexing, retrieval, answer), last error codes.
- **Validation**:
  - `pytest -q tests/test_component_health_matrix.py tests/test_health_has_stable_fields.py`

### Task 2.3: Diagnostics Bundle Export (OPS-03)
- **Location**: `autocapture/web/routes/doctor.py`, `autocapture_nx/kernel/doctor.py`
- **Description**: Deterministic diagnostics bundle zip; redact only at export boundaries.
- **Validation**:
  - `pytest -q tests/test_diagnostics_bundle_redacts.py`

## Sprint 3: Execution Engine (DAG + Jobs + Budgets)
**Goal**: Implement EXEC-01/02/03 so capture/process/index/query scheduling is explicit, deterministic, and resource-bounded.
**Demo/Validation**:
- Persisted DAG in `state_tape`.
- Job runner attempt records in ledger.
- Concurrency budgets enforced in idle mode.

### Task 3.1: Persisted Pipeline DAG (EXEC-01)
- **Location**: `autocapture_nx/runtime/conductor.py`, `autocapture_nx/kernel/state_tape.py`, `autocapture_nx/kernel/query.py`
- **Validation**:
  - `pytest -q tests/test_pipeline_dag_determinism.py`

### Task 3.2: Idempotent Job Runner + Retry Records (EXEC-02)
- **Location**: `autocapture_nx/runtime/conductor.py`, `plugins/builtin/ledger_basic/plugin.py`
- **Validation**:
  - `pytest -q tests/test_job_retry_records.py`

### Task 3.3: Unified Concurrency + CPU/RAM Budgets (EXEC-03)
- **Location**: `autocapture_nx/runtime/governor.py`, `autocapture_nx/runtime/scheduler.py`, `autocapture_nx/capture/pipeline.py`
- **Validation**:
  - `pytest -q tests/test_concurrency_budget_enforced.py`

## Sprint 4: Export/Import + Migrations
**Goal**: Make replacement-machine migration frictionless and citeable: export/import all DBs + metadata, and versioned migrations.
**Validation**:
- `pytest -q tests/test_db_migrations.py`

## Sprint 5: Performance (Incremental Index + Cache)
**Goal**: Ensure 24/7 operation doesn’t regress: incremental indexing, extractor cache keys, streaming proof bundle IO.
**Validation**:
- `bash tools/gate_perf.py` (or project’s perf gate)

## Testing Strategy
- Keep unit tests deterministic, single-process by default.
- For end-to-end fixtures:
  - Screenshot: `bash /mnt/d/projects/autocapture_prime/tools/run_fixture_all.sh`
  - MP4: use the existing ffmpeg sample harness (deterministic JPEG frames) and verify query outputs use metadata only.

## Potential Risks & Gotchas
- “Coverage to zero” requires both code *and* validator files referenced in `docs/autocapture_prime_adversarial_redesign.md`.
- Some items reference UI artifacts; keep API/CLI implementations first and make UI validators minimal (or mark as future once UI is replaced).
- WSL stability depends on limiting subprocess fanout; avoid parallel test execution.

## Rollback Plan
- Changes are additive and gated by tests; revert per-commit if a regression appears.

