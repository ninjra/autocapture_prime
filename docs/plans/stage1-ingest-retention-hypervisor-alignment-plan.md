# Plan: Stage1 Ingest Retention Hypervisor Alignment

**Generated**: 2026-02-20  
**Estimated Complexity**: High

## Overview
Deliver a **flawless, frictionless Stage 1** that rapidly ingests media + metadata into a canonical evidence layer, marks frames retention-ready as early as policy allows, and decouples downstream analysis from raw media reads. The implementation is split across `autocapture_prime` and `hypervisor` with strict contract tests, throughput controls, and citation-first correctness gates.

Primary outcomes:
- Stage 1 is fast enough to run in idle and optionally in active mode (when within strict CPU/RAM limits).
- Downstream stages consume Stage 1 artifacts (not raw media) by default.
- Retention pressure is reduced by proving readiness quickly and deterministically.
- Accuracy and citeability are preserved with explicit evidence lineage and strict golden evaluation.

## Assumptions
- Hypervisor is still implementing prior prompt; this plan is the delta to close remaining gaps.
- `request_user_input` tool is unavailable in this mode; ambiguities are converted into explicit defaults and acceptance criteria.
- `40/40, 0 skipped, 0 failed` strict semantics remain mandatory for sign-off.

## Prerequisites
- Local access to both repos:
  - `/mnt/d/projects/autocapture_prime`
  - `/mnt/d/projects/hypervisor`
- Live data root and sidecar artifacts:
  - `/mnt/d/autocapture/metadata.db`
  - `/mnt/d/autocapture/uia/latest.snap.json`
  - `/mnt/d/autocapture/uia/latest.snap.sha256`
- Test/gate executables in both repos.
- Stable localhost-only VLM stack for heavy downstream steps.

## Skills By Section
- Sprint 0-1: `ccpm-debugging`, `config-matrix-validator`, `shell-lint-ps-wsl`
  - Why: eliminate contract drift and environment drift first.
- Sprint 2-3: `resource-budget-enforcer`, `testing`, `python-testing-patterns`
  - Why: build fast Stage 1 with deterministic behavior under load.
- Sprint 4: `evidence-trace-auditor`, `golden-answer-harness`
  - Why: enforce citeability and strict correctness gates.
- Sprint 5: `deterministic-tests-marshal`, `state-recovery-simulator`
  - Why: soak reliability, crash tolerance, and reproducible overnight operation.

## Sprint 0: Contract Lock And Scope Freeze
**Goal**: Freeze one authoritative Stage 1 contract shared by both repos so implementation cannot diverge.  
**Demo/Validation**:
- Single contract doc and fixtures accepted by both repos.
- `contract_validate` jobs pass in both repos.

### Task 0.1: Publish Stage 1 Canonical Contract
- **Location**:  
  - `autocapture_prime/docs/windows-sidecar-capture-interface.md`  
  - `hypervisor/docs/contracts/autocapture_stage1_contract.md` (canonical peer doc)
- **Description**: Define Stage 1 output set and required fields:
  - `evidence.capture.frame` (media hash, dimensions, ts, source window/process)
  - `evidence.hid.raw` / `derived.input.summary` linkage
  - `evidence.uia.snapshot` + `uia_ref` linkage
  - Stage completion marker contract (`derived.ingest.stage1.complete` or equivalent)
  - Retention eligibility marker criteria and timing
  - Marker timing is explicit:
    - write `derived.ingest.stage1.complete` immediately after Stage 1 writes succeed
    - write `retention.eligible` in same transaction batch (or same loop turn) when Stage 1 completeness is true
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Both repos reference identical field names and semantics.
  - Required IDs, hashes, and timestamps are deterministic.
- **Validation**:
  - Schema/fixture validation command in both repos passes.

### Task 0.2: Freeze Stage 1 Readiness Rules
- **Location**:
  - `autocapture/storage/retention.py`
  - Hypervisor ingestion worker policy module
- **Description**: Encode exact rule for “ready to reap raw image”:
  - Stage 1 complete marker present
  - `retention.eligible` marker present
  - Required lineage pointer present (frame -> stage1 bundle -> metadata refs)
- **Complexity**: 5
- **Dependencies**: Task 0.1
- **Acceptance Criteria**:
  - No ambiguous “processed” definition remains.
- **Validation**:
  - Unit tests for ready/not-ready permutations.

## Sprint 1: Stage 1 Pipeline (Fast, Complete, Deterministic)
**Goal**: Implement a minimal-heavy but information-complete Stage 1 that extracts all relevant ingest-time facts needed for downstream analysis and citation.  
**Demo/Validation**:
- Process 1,000-frame synthetic/live mix with Stage 1 completion markers and retention markers.
- Downstream query path can answer from Stage 1-derived artifacts without reopening raw image for common cases.

### Task 1.1: Build Stage 1 Bundle Writer
- **Location**:
  - `autocapture_nx/processing/idle.py`
  - `autocapture_nx/runtime/batch.py`
  - Hypervisor sidecar ingestion worker
- **Description**: Emit canonical Stage 1 bundle per frame with:
  - Frame metadata + stable hash(es)
  - UIA linkage metadata and normalized node summaries
  - HID raw references + normalized event summaries
  - Deterministic lineage IDs
- **Complexity**: 7
- **Dependencies**: Sprint 0
- **Acceptance Criteria**:
  - Stage 1 bundle exists for every ingested frame.
  - IDs stable across reruns.
- **Validation**:
  - Unit + integration tests for stable IDs and required keys.

### Task 1.2: Enforce Metadata-First UIA Consumption In Stage 1
- **Location**:
  - `plugins/builtin/processing_sst_uia_context/plugin.py`
  - Hypervisor metadata writer path
- **Description**:
  - Resolve `uia_ref.record_id` from metadata first.
  - Fallback only on metadata lookup failure.
  - Strict hash gate on fallback (`latest.snap.sha256`).
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - No fallback use when metadata has valid snapshot.
  - Fallback hash mismatch is rejected fail-open (no crash).
- **Validation**:
  - Delta tests for metadata-first, fallback mismatch, deterministic IDs.

### Task 1.3: Stage 1 Completion + Retention Eligibility Write
- **Location**:
  - `autocapture_nx/processing/idle.py`
  - Hypervisor ingestion completion hook
  - `autocapture/storage/retention.py`
- **Description**:
  - Write `retention.eligible` as part of Stage 1 completion, including reason code.
  - Ensure marker write is not dependent on heavy Stage 2/3 analysis.
- **Complexity**: 8
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Every Stage 1-complete frame has retention marker.
  - Missing marker is observable and alertable:
    - metric `stage1_missing_retention_marker_count`
    - metric `stage1_retention_marker_ratio`
    - alert threshold: marker ratio < 0.999 over 5-minute window OR missing count > 0 for 2 consecutive windows.
- **Validation**:
  - Metadata DB count checks:
    - `evidence.capture.frame`
    - Stage 1 complete marker
    - `retention.eligible`
  - Soak/postcheck asserts marker ratio threshold.

## Sprint 2: Intelligent Batch Scheduling And Active-Mode Safety
**Goal**: Keep Stage 1 continuously draining backlog with bounded parallelism and policy-safe active-mode behavior.  
**Demo/Validation**:
- 10-hour soak simulation with sustained throughput and no crash.
- Active-mode Stage 1 runs only when budget checks pass.

### Task 2.1: Queue + Worker Pool For Stage 1
- **Location**:
  - `autocapture_nx/runtime/batch.py`
  - `autocapture_nx/processing/idle.py`
  - `tools/soak/run_golden_qh_soak.sh`
- **Description**:
  - Implement bounded queue + worker pools.
  - Separate worker caps for Stage 1 vs heavy stages.
- **Complexity**: 8
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Multi-image processing no longer serial bottleneck.
  - No unbounded memory growth.
- **Validation**:
  - Throughput benchmark + stability test.

### Task 2.2: Cheap-First Deferral Rules
- **Location**:
  - `autocapture_nx/processing/idle.py`
  - config defaults/schema for idle intelligent batch
- **Description**:
  - Hash/delta repeat detection to defer expensive VLM work.
  - Preserve accuracy by carrying forward deterministic prior-derived outputs only when safe.
- **Complexity**: 7
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Reduced heavy-stage load with no strict-correctness regression.
- **Validation**:
  - Unit tests for defer/no-defer decision boundaries.
  - Golden diff test before/after.

### Task 2.3: Active-Mode Stage 1 Budget Gating
- **Location**:
  - `autocapture/runtime/conductor.py`
  - `autocapture_nx/runtime/batch.py`
- **Description**:
  - Allow Stage 1 in active mode only when CPU/RAM budget headroom exists.
  - Hard cap per-iteration work to avoid UI impact.
  - Telemetry source/cadence:
    - use conductor resource sampling at 1s cadence
    - mark telemetry stale after 3s; stale telemetry disables active-mode Stage 1 (fail-safe).
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - No budget violations under active synthetic load.
- **Validation**:
  - Resource budget tests + telemetry assertions.
  - Stale-telemetry tests proving fail-safe disable behavior.

## Sprint 3: Retention SLA Control Loop (6-Day Safety)
**Goal**: Guarantee processing completes before retention horizon.  
**Demo/Validation**:
- ETA projection shows backlog drains < 6 days.
- Automatic scaling actions logged when lag risk rises.

### Task 3.1: ETA/Lag Projection Metrics
- **Location**:
  - `autocapture_nx/runtime/batch.py`
  - `tools/soak/admission_check.py`
- **Description**:
  - Emit `pending_records`, `completed_records`, `throughput_records_per_s`, `projected_lag_hours`, `retention_risk`.
  - Retention risk formula:
    - `projected_lag_hours = pending_records / max(throughput_records_per_s, epsilon) / 3600`
    - `retention_risk = projected_lag_hours > (retention_horizon_hours * lag_warn_ratio)`
    - defaults: `retention_horizon_hours=144`, `lag_warn_ratio=0.8` (risk at >115.2h).
- **Complexity**: 5
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - SLA metrics present in run manifests and soak summaries.
- **Validation**:
  - Unit tests for finite and infinite-lag scenarios.

### Task 3.2: Auto-Tune On Retention Risk
- **Location**:
  - `autocapture_nx/runtime/batch.py`
  - `config/default.json`
  - `contracts/config_schema.json`
- **Description**:
  - Increase safe Stage 1 parallelism when risk flagged.
  - Respect hard upper bounds and active-mode caps.
- **Complexity**: 6
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Deterministic scaling response under synthetic backlog surge.
  - Response SLO:
    - scale-up action emitted within 2 scheduler loops after `retention_risk=true`.
- **Validation**:
  - Tests covering scale-up/hold/limit conditions.

## Sprint 4: Accuracy + Citeability Lock
**Goal**: Prove no tradeoff against correctness/citeability while accelerating Stage 1.  
**Demo/Validation**:
- Strict matrix:
  - `evaluated=40`
  - `skipped=0`
  - `failed=0`
- Citation chain validation passes.

### Task 4.1: Stage1-Only Citation Chain Validation
- **Location**:
  - `tools/run_advanced10_queries.py`
  - `tools/eval_q40_matrix.py`
  - citation/provenance tests
- **Description**:
  - Ensure answers can cite Stage 1 + derived outputs without raw media dependency for target questions.
- **Complexity**: 7
- **Dependencies**: Sprint 1-3
- **Acceptance Criteria**:
  - No uncitable answer counted as pass.
- **Validation**:
  - Evidence-trace audit in CI and soak postcheck.

### Task 4.2: Strict Golden Re-Gate
- **Location**:
  - `tools/q40.sh`
  - `tools/release_gate.py`
  - `tools/soak/admission_check.py`
- **Description**:
  - Promote strict q40 and citation checks to release/soak admission requirements.
- **Complexity**: 5
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Admission fails if strict/citation semantics regress.
- **Validation**:
  - Controlled failing fixture confirms fail-closed behavior.

## Sprint 5: Production Rollout And Overnight Ops
**Goal**: Deploy as nightly default with observability and rollback safety.  
**Demo/Validation**:
- Overnight soak passes with expected throughput and stability.
- Ops runbook includes one-command health checks and rollback.

### Task 5.1: Ops Runbook And Dashboards
- **Location**:
  - `docs/runbooks/release_gate_ops.md`
  - `docs/runbooks/stage1_ingest_ops.md` (new)
- **Description**:
  - Add on-call checks for Stage 1 lag, retention-ready ratio, UIA linkage health.
- **Complexity**: 4
- **Dependencies**: Sprint 3-4
- **Acceptance Criteria**:
  - Operator can detect/diagnose lag and marker drift in <5 minutes.
- **Validation**:
  - Runbook dry-run checklist.

### Task 5.2: Controlled Rollout + Backout
- **Location**:
  - profile/config flags for intelligent batch and SLA control
- **Description**:
  - Enable by profile, canary on subset, then full rollout.
  - Keep rollback flags documented and tested.
- **Complexity**: 5
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Toggle rollback restores prior behavior without data loss.
- **Validation**:
  - Canary pass/fail and rollback rehearsal.

## Testing Strategy
- Unit:
  - Stage 1 bundle completeness
  - deterministic IDs
  - retention marker writes
  - defer/throttle rules
  - SLA projection math
- Integration:
  - frame -> uia_ref -> uia snapshot -> obs.uia.* -> retention.eligible
  - metadata-first + fallback hash gate
- System:
  - 10-hour soak with parallel workers
  - active-mode budget compliance
- Correctness:
  - strict q40 (40/40, 0 skip, 0 fail)
  - citation chain audit

## Potential Risks & Gotchas
- Hypervisor/autocapture contract drift after partial deploy.
  - Mitigation: schema fixture handshake and bidirectional contract CI.
- Markers written in one path but not another.
  - Mitigation: single shared marker writer API + path coverage tests.
- Deferred heavy analysis hurting edge-case accuracy.
  - Mitigation: strict allowlist for deferral and mandatory golden diff gate.
- WSL vs Windows keyring/runtime divergence for live processing.
  - Mitigation: keep live writer execution on compatible host path; validate in both environments.
- Over-aggressive scaling causing instability.
  - Mitigation: bounded caps, backpressure, and soak admission gates.

## Rollback Plan
- Disable intelligent batch and SLA pressure flags in profile:
  - `processing.idle.intelligent_batch.enabled=false`
  - `processing.idle.sla_control.enabled=false`
- Keep Stage 1 marker writing enabled (do not rollback this unless corruption is proven).
- Revert to last known-good release gate + soak configuration.
- Re-run strict q40 and citation audit before re-enabling.
