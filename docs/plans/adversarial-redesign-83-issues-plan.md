# Plan: Adversarial Redesign (83 Issues) Full Implementation

**Generated**: 2026-02-08
**Estimated Complexity**: High

## Overview
Close all adversarial redesign coverage gaps tracked by `tools/run_adversarial_redesign_coverage.sh` by implementing (not stubbing) every item that is currently `missing` or `partial` in `docs/reports/adversarial-redesign-gap-2026-02-08.md`, while preserving the project non-negotiables:
- Localhost-only, fail closed.
- No deletion endpoints; archive/migrate only.
- Raw-first local store; sanitize only on explicit export/egress.
- Foreground gating: when user ACTIVE, only capture+kernel runs; pause other processing.
- Idle budgets: enforce CPU<=50% and RAM<=50%.
- Answers require citations by default.
- Keep WSL stable: avoid high parallelism and runaway subprocesses.

This plan is CLI+API first; UI items are implemented minimally (endpoints + deterministic tests) so they are verifiable but do not add heavy UI work (UI replacement is planned later).

## Inputs / Source Of Truth
- Spec: `docs/autocapture_prime_adversarial_redesign.md`
- Gap report: `docs/reports/adversarial-redesign-gap-2026-02-08.md`
- Gate: `tools/run_adversarial_redesign_coverage.sh`

## Prerequisites
- Working Python venv (`.venv`) with project deps installed.
- `ffmpeg` available for the MP4 fixture validation step.

## Global Acceptance Criteria (Definition Of Done)
- `tools/run_adversarial_redesign_coverage.sh` passes with `issues=0`.
- All referenced validators exist and are deterministic.
- `pytest -q` passes (use `-m:1` / single worker where applicable).
- Low-resource validation passes (screenshot + ffmpeg MP4 fixture pipeline).
- No new `TODO`, `FIXME`, or “not implemented” placeholders; add tracking issues only via docs (not code comments).

## Sprint 0: Stabilize Traceability + Low-Resource Gates
**Goal**: Make traceability a reliable contract and ensure validations are low-resource and deterministic.
**Demo/Validation**:
- Run `tools/run_adversarial_redesign_coverage.sh` and confirm gaps are precise and stable.
- Run low-resource fixture pipeline for PNG + MP4.

### Task 0.1: Normalize Traceability Inputs (Remove “(new)” Tokens From Paths)
- **Location**: `docs/autocapture_prime_adversarial_redesign.md`, `tools/traceability/adversarial_redesign_inventory.py`
- **Description**: Ensure `enforcement_location` and `regression_detection` fields contain repo-relative paths only (no parenthetical annotations like `(new)` in the path token). Keep “new” information in `notes` fields or prose.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Traceability generator computes status based on correct paths.
- **Validation**:
  - `python3 tools/traceability/generate_adversarial_redesign_traceability.py` output contains no evidence entries with spaces due to `(new)` artifacts.

### Task 0.2: Expand `adversarial_redesign_map.json` Overrides Only When Needed
- **Location**: `tools/traceability/adversarial_redesign_map.json`
- **Description**: Keep overrides minimal; use only to correct legacy doc ambiguity or split one recommendation into multiple concrete paths.
- **Complexity**: 3
- **Dependencies**: Task 0.1
- **Validation**:
  - `python3 tools/traceability/validate_adversarial_redesign_traceability.py`

### Task 0.3: Add a Single “Low Resource Validation” Runner (PNG + MP4)
- **Location**: `tools/run_low_resource_validation.sh` (existing; extend if needed)
- **Description**: Ensure the runner:
  - Uses single-process execution.
  - Avoids spawning many plugin-host subprocesses simultaneously.
  - Runs the screenshot fixture pipeline and then the ffmpeg MP4 pipeline.
- **Complexity**: 5
- **Dependencies**: None
- **Validation**:
  - Runner completes with stable outputs and bounded CPU/RAM.

## Sprint 1: Execution Model (DAG, Jobs, Budgets) + Plugin Host Stability
**Goal**: Fix the largest correctness/perf stability risks first, including the observed “too many python processes” issue.
**Demo/Validation**:
- Run a small end-to-end fixture job and verify:
  - Only bounded subprocesses exist (configurable cap).
  - Timeouts kill stuck plugin runners and ledger/audit records the termination.

### Task 1.1: Persist Pipeline DAG (Stages + Deps) In State Tape
- **Location**: `autocapture_nx/runtime/conductor.py`, `autocapture_nx/kernel/state_tape.py`
- **Description**: Introduce a canonical DAG structure with stable stage IDs, dependencies, and schema versioning; persist as part of state tape so replay/doctor can reason about the pipeline.
- **Complexity**: 7
- **Dependencies**: Sprint 0
- **Acceptance Criteria**:
  - DAG is stable under identical inputs/config.
- **Validation**:
  - Add `tests/test_pipeline_dag_determinism.py`.

### Task 1.2: Idempotent Job Runner With Retry Attempts Recorded
- **Location**: `autocapture_nx/runtime/conductor.py`, `plugins/builtin/ledger_basic/plugin.py`
- **Description**: Add bounded retries + backoff; record each attempt with deterministic IDs.
- **Complexity**: 7
- **Dependencies**: Task 1.1
- **Validation**:
  - Add `tests/test_job_retry_records.py`.

### Task 1.3: Unify Concurrency Controls (Semaphores + CPU/RAM Budgets + Deterministic Scheduling)
- **Location**: `autocapture_nx/runtime/governor.py`, `autocapture_nx/runtime/scheduler.py`
- **Description**: Ensure scheduler selects jobs deterministically under equal priorities; enforce CPU/RAM caps and per-stage semaphores.
- **Complexity**: 8
- **Dependencies**: Task 1.2
- **Validation**:
  - Add `tests/test_concurrency_budget_enforced.py`.

### Task 1.4: Tighten Subprocess Plugin Runtime Limits (Timeouts + Kill + Audit)
- **Location**: `autocapture_nx/plugin_system/host_runner.py`, `autocapture_nx/kernel/audit.py`
- **Description**: Implement strict per-call RPC timeouts; kill the process on timeout; record termination in audit (append-only).
- **Complexity**: 8
- **Dependencies**: Task 1.3
- **Validation**:
  - Add `tests/test_plugin_timeout_killed.py`.

### Task 1.5: Reduce Plugin Host Process Explosion (Cap + Reuse Where Safe)
- **Location**: `autocapture_nx/plugin_system/runtime.py`, `autocapture_nx/plugin_system/manager.py`, `autocapture_nx/plugin_system/host_runner.py`
- **Description**: Introduce:
  - A global cap on concurrent plugin host processes.
  - Deterministic teardown on completion.
  - Optional reuse for short-lived “create_plugin” flows (only if it does not weaken isolation).
- **Complexity**: 9
- **Dependencies**: Task 1.4
- **Acceptance Criteria**:
  - A fixture run does not leave N lingering python host_runner processes.
- **Validation**:
  - Extend `tests/test_plugin_timeout_killed.py` or add `tests/test_plugin_host_process_cap.py`.

### Task 1.6: Deterministic Retrieval Tie-Breaking Contract
- **Location**: `plugins/builtin/retrieval_basic/plugin.py`, `contracts/retrieval.schema.json` (new)
- **Description**: Define and enforce ordering `score -> evidence_id -> span_id` with schema + tests.
- **Complexity**: 6
- **Dependencies**: None
- **Validation**:
  - Add `tests/test_retrieval_tie_breaking.py`.

## Sprint 2: Foundation Reliability (Ingest IDs, Disk Pressure, Backup/Restore, Migrations, Time)
**Goal**: Make storage and recovery deterministic and portable between machines.
**Demo/Validation**:
- Create backup and restore into a fresh temp dir; verify integrity scan.

### Task 2.1: Content-Addressed Ingest IDs + Dedupe
- **Location**: `autocapture_nx/ingest/*` (new/extend), `plugins/builtin/storage_media_basic/plugin.py`
- **Description**: Compute `input_id` from sha256; dedupe at ingest boundary.
- **Complexity**: 7
- **Dependencies**: Sprint 1
- **Validation**:
  - Add `tests/test_ingest_dedupe.py`.

### Task 2.2: Disk-Pressure Fail-Safe Pause (Capture + Processing)
- **Location**: `autocapture_nx/capture/pipeline.py`, `autocapture_nx/storage/retention.py`
- **Description**: Preflight free-space; pause deterministically; surface a stable state code.
- **Complexity**: 7
- **Dependencies**: Sprint 1
- **Validation**:
  - Add `tests/test_disk_pressure_pause.py`.

### Task 2.3: Backup Create/Restore (Config + Locks + Anchors + Optional Data)
- **Location**: `autocapture_nx/cli.py`, `autocapture_nx/kernel/paths.py`
- **Description**: Deterministic archive format; restore verifies integrity and refuses partial restores.
- **Complexity**: 8
- **Dependencies**: Task 2.1
- **Validation**:
  - Add `tests/test_backup_restore.py`.

### Task 2.4: DB Migration Framework + Status Reporting
- **Location**: `autocapture_nx/storage/*`, `autocapture/indexing/*`, `autocapture_nx/kernel/doctor.py`
- **Description**: Add version pinning and per-DB migration registry with forward-only migrations by default; expose status.
- **Complexity**: 9
- **Dependencies**: Task 2.3
- **Validation**:
  - Add/expand `tests/test_db_migrations.py`.

### Task 2.5: Timestamp Normalization + Monotonic Durations
- **Location**: `autocapture_nx/kernel/determinism.py`, `autocapture_nx/kernel/run_state.py`
- **Description**: Store UTC + tz_offset, durations from monotonic clock; ensure determinism in serialization.
- **Complexity**: 6
- **Dependencies**: None
- **Validation**:
  - Add `tests/test_time_normalization.py`.

## Sprint 3: Metadata + Diagnostics (Policy Snapshots, Artifact Manifests, Health Matrix)
**Goal**: Make every run queryable and auditable without reprocessing, and make operator workflows deterministic.
**Demo/Validation**:
- Run `autocapture doctor` and `/health` and confirm component matrix includes stable fields.

### Task 3.1: Effective Config Snapshot Per Run
- **Location**: `autocapture_nx/kernel/loader.py`, `autocapture/config/load.py`
- **Description**: Persist `config.effective.json` + sha256; link from run manifest.
- **Complexity**: 5
- **Dependencies**: Sprint 2
- **Validation**:
  - Add `tests/test_run_config_snapshot.py`.

### Task 3.2: Plugin Provenance In Run Manifest
- **Location**: `autocapture_nx/plugin_system/registry.py`, `autocapture_nx/kernel/loader.py`
- **Description**: Record plugin_id/version/manifest hash/artifact hash/permissions at boot.
- **Complexity**: 6
- **Dependencies**: Sprint 1
- **Validation**:
  - Add `tests/test_plugin_provenance_in_manifest.py`.

### Task 3.3: Policy Snapshot Persistence By Hash (Ledger + Proof Bundle)
- **Location**: `autocapture_nx/kernel/policy_gate.py`, `plugins/builtin/ledger_basic/plugin.py`, `autocapture_nx/kernel/proof_bundle.py`
- **Description**: Persist full policy snapshot objects referenced by hash.
- **Complexity**: 8
- **Dependencies**: Sprint 2
- **Validation**:
  - Add `tests/test_policy_snapshot_exported.py`.

### Task 3.4: Health Checks / Doctor Matrix (Capture/OCR/VLM/Index/Retrieval/Answer)
- **Location**: `autocapture_nx/kernel/doctor.py`, `autocapture/web/routes/health.py`
- **Description**: Provide stable summary fields + full component matrix.
- **Complexity**: 7
- **Dependencies**: Sprint 1
- **Validation**:
  - Add `tests/test_component_health_matrix.py`, `tests/test_health_has_stable_fields.py`.

### Task 3.5: Structured JSONL Logging With Correlation IDs
- **Location**: `autocapture_nx/kernel/logging.py`, `autocapture_nx/plugin_system/host_runner.py`
- **Description**: Emit JSONL with `run_id`, `job_id`, `plugin_id`; rotate logs deterministically.
- **Complexity**: 8
- **Dependencies**: Sprint 1
- **Validation**:
  - Add `tests/test_logs_have_correlation_ids.py`.

## Sprint 4: Performance (Incremental Indexing, Caching, WSL2 Round-Trip)
**Goal**: Reduce steady-state CPU/RAM while keeping determinism and citeability.
**Demo/Validation**:
- Confirm query uses metadata only (no decode/reprocess), and indexing is incremental.

### Task 4.1: Incremental Indexing By Evidence Hash
- **Location**: `autocapture/indexing/*`
- **Description**: Process only new/changed evidence IDs; maintain deterministic ordering.
- **Complexity**: 8
- **Dependencies**: Sprint 2
- **Validation**:
  - Add `tests/test_incremental_indexing.py`.

### Task 4.2: Derived-Step Cache (OCR/VLM/Embeddings) Keyed By Hashes
- **Location**: `autocapture_nx/processing/*`, `plugins/builtin/*`
- **Description**: Cache by `(evidence_hash, extractor_version, config_hash)`; never recompute on query.
- **Complexity**: 8
- **Dependencies**: Sprint 3
- **Validation**:
  - Add `tests/test_extractor_cache_keys.py`.

### Task 4.3: WSL2 Job Loop Round-Trip + Backpressure
- **Location**: `autocapture/runtime/wsl2_queue.py`, `autocapture/runtime/routing.py`
- **Description**: Implement full request/response protocol with bounded polling and deterministic backpressure.
- **Complexity**: 9
- **Dependencies**: Sprint 1
- **Validation**:
  - Add `tests/test_wsl2_job_roundtrip.py`.

## Sprint 5: Security + QA (Export Redaction, Egress Approval, Proof Signatures, Regression Suites)
**Goal**: Complete security posture and harden with deterministic regression suites.
**Demo/Validation**:
- Run security guard tests and verify export redaction is deterministic and only applied on explicit export.

### Task 5.1: Filesystem Guard Hardening (Windows Edge Cases)
- **Location**: `autocapture_nx/windows/win_paths.py`, `autocapture_nx/plugin_system/runtime.py`
- **Description**: Normalize/resolve symlinks, normalize case/UNC, deny traversal consistently.
- **Complexity**: 8
- **Dependencies**: Sprint 1
- **Validation**:
  - Add `tests/test_filesystem_guard_windows_edge_cases.py`.

### Task 5.2: Egress Default Approval + Allowlist + Ledger Events
- **Location**: `autocapture/egress/client.py`, `autocapture/web/routes/egress.py`, `config/default.json`
- **Description**: Default `approval_required=true`; require per-destination allowlists; ledger each egress.
- **Complexity**: 7
- **Dependencies**: Sprint 3
- **Validation**:
  - Add `tests/test_egress_requires_approval_by_default.py`.

### Task 5.3: Export/Boundary Redaction (Deterministic) + Redaction Map
- **Location**: `autocapture/privacy/redaction.py`, `autocapture/egress/sanitize.py`
- **Description**: Detect/redact PII only on export/egress; persist a redaction map in exported metadata.
- **Complexity**: 9
- **Dependencies**: Task 5.2
- **Validation**:
  - Add `tests/test_redaction_deterministic.py`.

### Task 5.4: Proof Bundle Signature + Verify On Import/Replay
- **Location**: `autocapture_nx/kernel/proof_bundle.py`
- **Description**: Sign bundle manifest locally; verify on import; include sha256 for all files.
- **Complexity**: 8
- **Dependencies**: Sprint 3
- **Validation**:
  - Add `tests/test_proof_bundle_signature_verifies.py`, `tests/test_proof_bundle_verify.py`.

### Task 5.5: QA Golden + Chaos + Fuzz + Sandbox Regression Suite
- **Location**: `tests/test_query_golden.py` (new), `tests/test_crash_recovery_chaos.py` (new), `tests/test_security_guards.py` (new)
- **Description**: Add deterministic fixtures + stubbed model plugins to ensure stable answers/citations; add crash recovery chaos tests; add config/manifest fuzz corpus; add sandbox regression suite.
- **Complexity**: 10
- **Dependencies**: Sprints 1-4
- **Validation**:
  - New tests pass deterministically on repeated runs.

## Sprint 6: Minimal UI/Docs (To Satisfy Traceability, Not To Replace UI)
**Goal**: Implement doc/runbook + minimal UI compatibility surfaces required by redesign items.
**Demo/Validation**:
- `docs/runbook.md` covers operator flows.
- UI smoke tests (headless) run and pass.

### Task 6.1: Operator Runbook + Safe Mode Doc
- **Location**: `docs/runbook.md` (new), `docs/safe_mode.md` (new)
- **Description**: Provide deterministic procedures: backup/restore, plugin rollback, disk pressure, integrity verification, safe-mode triage.
- **Complexity**: 6
- **Dependencies**: Sprints 2-5
- **Validation**:
  - Add `tests/test_docs_consistency_smoke.py` or extend existing doc gates.

### Task 6.2: UI Smoke + a11y Baseline
- **Location**: `tests/test_ui_smoke.py` (new), `tests/test_accessibility_smoke.py` (new)
- **Description**: Minimal headless checks for critical pages; a11y checks for labels/focus order.
- **Complexity**: 7
- **Dependencies**: Sprint 3
- **Validation**:
  - Tests run in CI headless and pass deterministically.

## Testing Strategy
- Prefer unit tests for deterministic contracts (ordering, hashing, schema versioning).
- Use fixture-driven integration tests for:
  - PNG screenshot pipeline.
  - ffmpeg MP4 pipeline (decode -> extract -> index -> query).
- Run performance gates only after correctness gates pass; keep them single-worker in WSL.

## Potential Risks & Gotchas
- WSL stability: plugin-host subprocess storms can crash WSL; cap concurrency early (Sprint 1).
- Traceability parser pitfalls: parentheses or non-path tokens in doc fields cause false “missing”.
- “UI later” tension: implement minimal endpoints/tests for UX-* without building a full UI.
- Security boundaries: keep raw-first local store; ensure redaction is export/egress-only.
- Migrations: write forward-only migrations but keep rollback plan/documentation deterministic.

## Rollback Plan
- Each sprint lands as small commits; revert by `git revert` of the specific commit(s).
- For state/schema changes, add migrations that can be disabled via config flags during rollback window.

