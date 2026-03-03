# Plan: Pipeline Catch-Up and Freshness Recovery

**Generated**: 2026-02-26  
**Estimated Complexity**: High

## Overview
The pipeline is functionally green on historical corpus correctness but operationally stale for recency.  
Current evidence shows Stage1/queryability counts are complete for historical frames, yet newest queryable frame time remains around `2026-02-21T02:52:06Z`, which is unacceptable against a 6-day retention horizon.

This plan restores continuous catch-up so idle windows reliably drain new capture data every day and keep queryable recency near real-time.

Primary strategy:
1. Fix source-of-truth routing for background processing (ingest path must not stall on stale mirror).
2. Add explicit freshness SLOs and fail-closed gates for stale processing.
3. Harden idle drain control loop to guarantee positive throughput whenever backlog exists.
4. Prove with deterministic gates, soak, and lineage artifacts.

## Baseline (from current artifacts)
- `artifacts/queryability/gate_queryability.json`
  - `frames_total=18087`, `frames_queryable=18087`, `stage1_ok=18087`, `retention_ok=18087`
- `artifacts/lineage/20260222T191057Z/stage1_stage2_lineage_queryability.json`
  - latest queryable frame window end: `2026-02-21T02:52:06.043Z`
- `artifacts/release/release_quickcheck_latest.json`
  - popup/q40/temporal strict pass
  - `real_corpus_strict_ok=false` (17/20 failed in that gate)

## Skills by Sprint (and Why)
- Sprint 0: `plan-harder`, `ccpm-debugging`, `config-matrix-validator`
  - Why: lock root cause and remove source-routing ambiguity before edits.
- Sprint 1: `ccpm-debugging`, `python-testing-patterns`, `deterministic-tests-marshal`
  - Why: implement metadata-source arbitration safely and prove determinism.
- Sprint 2: `resource-budget-enforcer`, `observability-slo-broker`, `python-observability`
  - Why: guarantee catch-up throughput within idle CPU/RAM budgets and emit actionable SLO metrics.
- Sprint 3: `golden-answer-harness`, `evidence-trace-auditor`, `deterministic-tests-marshal`
  - Why: ensure freshness changes improve real query correctness without citation regressions.
- Sprint 4: `state-recovery-simulator`, `audit-log-integrity-checker`, `policygate-penetration-suite`
  - Why: verify resilience, replay integrity, and fail-open/fail-closed behavior during faults.
- All sprints: `shell-lint-ps-wsl`
  - Why: command and runbook safety.

## Prerequisites
- Data paths available:
  - `/mnt/d/autocapture/metadata.db`
  - `/mnt/d/autocapture/metadata.live.db`
  - `/mnt/d/autocapture/derived/stage1_derived.db`
- Hypervisor keeps capture writing to `metadata.db`/spool contract.
- Query path remains `schedule_extract=false` and raw-off for retrieval.

## Sprint 0: Root-Cause Lock and SLO Contract
**Goal**: Convert “stale but green” into explicit measurable failure conditions.  
**Demo/Validation**:
- New artifact includes `freshness_lag_hours` and `latest_queryable_ts_utc`.
- Gate fails when freshness exceeds threshold.

### Task 0.1: Add Freshness Snapshot Tool
- **Location**: `tools/soak/processing_health_snapshot.py`, `tools/release_quickcheck.py`
- **Description**: Add deterministic fields:
  - `latest_capture_ts_utc`
  - `latest_stage1_complete_ts_utc`
  - `latest_queryable_ts_utc`
  - `freshness_lag_hours`
  - `db_reachability` (`metadata.db`, `metadata.live.db`, `stage1_derived.db`) with explicit failure reason codes
- **Complexity**: 4
- **Dependencies**: none
- **Acceptance Criteria**:
  - Snapshot computed from DBs only, no service calls.
  - Output schema stable across runs.
- **Validation**:
  - New unit tests for lag computation and missing-data behavior.

### Task 0.2: Freshness Fail-Closed Gate
- **Location**: `tools/release_gate.py`, `tools/gate_stage1_contract.py`
- **Description**: Add gate reasons:
  - `freshness_lag_exceeded`
  - `stage1_throughput_zero_with_backlog`
  Use explicit thresholds:
  - warn at `freshness_target_hours`
  - fail at `freshness_target_hours * 1.25` (default 12h target -> 15h fail)
- **Complexity**: 5
- **Dependencies**: Task 0.1
- **Acceptance Criteria**:
  - Release gate fails when lag is above configured max.
- **Validation**:
  - Deterministic gate tests with synthetic stale/fresh fixtures.

## Sprint 1: Metadata Source Arbitration Fix
**Goal**: Ensure background processing consumes fresh capture source while query runtime stays stable.  
**Demo/Validation**:
- During active capture, processing sees new frame IDs within one idle cycle.
- Query DB freshness advances automatically after processing.

### Task 1.1: Batch Metadata Source Selector
- **Location**: `autocapture_nx/cli.py`, `autocapture_nx/runtime/batch.py`, `tests/test_cli_batch_metadata_path.py`
- **Description**: Replace static “prefer live db” behavior for batch with freshness-aware selection:
  - Ingest source: freshest available capture source (`metadata.db` or handoff spool result).
  - Query source remains `metadata.live.db` for read stability.
  - Emit selector reason in batch manifest.
- **Complexity**: 8
- **Dependencies**: Sprint 0
- **Acceptance Criteria**:
  - Batch does not lock onto stale `metadata.live.db` when `metadata.db` is newer.
  - Explicit override env vars still honored.
- **Validation**:
  - Unit tests for selector matrix and override precedence.

### Task 1.2: Mirror/Projection Advancement Contract
- **Location**: `autocapture_nx/ingest/handoff_ingest.py`, `autocapture_nx/processing/idle.py`
- **Description**: Guarantee that Stage1-complete frames are reflected into query-visible layer (`metadata.live.db` + derived markers) with monotonic progress counters.
  Monotonic counters must include:
  - `stage1_complete_seen`
  - `stage1_complete_projected`
  - `stage2_complete_emitted`
  - `projection_failures`
- **Complexity**: 7
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Query-visible latest timestamp progresses when new frames are captured and idle processing runs.
  - Counter relation always holds: `stage1_complete_seen >= stage1_complete_projected >= stage2_complete_emitted`.
- **Validation**:
  - Integration test with synthetic capture writes + idle run + query-time read verification.

## Sprint 2: Catch-Up Throughput Controller
**Goal**: Make idle windows reliably burn down backlog instead of no-op loops.  
**Demo/Validation**:
- If backlog > 0 and idle allowed, `throughput_records_per_s > 0`.
- Projected lag decreases run-over-run.

### Task 2.1: Zero-Throughput Guard
- **Location**: `autocapture_nx/runtime/batch.py`
- **Description**: Detect repeated loops with:
  - `pending_records > 0`
  - `completed_records = 0`
  - no blocking reason
  and escalate deterministically (adaptive concurrency step-up and actionable blocked reason).
- **Complexity**: 6
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - No silent “healthy but doing nothing” state.
  - At most one idle cycle may report zero completions with backlog before explicit escalation reason is emitted.
- **Validation**:
  - Runtime batch tests with synthetic pending queues.

### Task 2.2: Idle Budget + Catch-Up Policy
- **Location**: `config/default.json`, `config/profiles/stage1_no_vlm_idle.json`, `tools/soak/admission_check.py`
- **Description**: Add policy knobs:
  - `freshness_target_hours`
  - `catchup_boost_when_lagged`
  - `max_lag_before_alert_hours`
  keeping CPU/RAM under 50% during idle.
  Enforce via measured metrics:
  - `idle_cpu_utilization_p95`
  - `idle_ram_utilization_p95`
  - sampled by `tools/soak/admission_check.py`
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Catch-up mode enters/exits with hysteresis and no budget violations.
  - `idle_cpu_utilization_p95 <= 0.50` and `idle_ram_utilization_p95 <= 0.50` in soak window.
- **Validation**:
  - Budget regression tests and admission-check fixtures.

## Sprint 3: Stage2+ and Query Correctness Under Fresh Data
**Goal**: As new data catches up, query correctness remains strict and citation-backed.  
**Demo/Validation**:
- Real-corpus strict matrix improves with fresh windows.
- No citation regressions from routing/controller changes.

### Task 3.1: Fresh-Window Real Corpus Gate
- **Location**: `tools/run_real_corpus_readiness.py`, `tools/release_gate.py`
- **Description**: Require minimum recency window for strict corpus readiness runs; stale windows must fail explicitly.
- **Complexity**: 5
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Real-corpus readiness cannot pass on stale corpus snapshots.
- **Validation**:
  - Tests for stale-window fail and fresh-window pass.

### Task 3.2: Citation-Chain Integrity on New Frames
- **Location**: `autocapture_nx/kernel/query.py`, `tools/gate_temporal40_semantic.py`
- **Description**: Ensure accepted answers on newly ingested frames cite normalized records (`derived.sst.*`, `obs.uia.*`, stage markers) only.
  Citation-chain validator must allow only:
  - `derived.sst.text.extra`
  - `obs.uia.focus`
  - `obs.uia.context`
  - `obs.uia.operable`
  - `derived.ingest.stage1.complete`
  - `derived.ingest.stage2.complete`
  - `retention.eligible`
- **Complexity**: 6
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Accepted answers have non-empty valid citation chains.
- **Validation**:
  - Citation gate tests and sampled strict runs.

## Sprint 4: Reliability, Recovery, and Overnight Soak
**Goal**: Prove stable unattended operation across nightly catch-up windows.  
**Demo/Validation**:
- Overnight soak shows monotonic recency improvement and bounded memory.
- Restart/resume keeps ledger/queryability consistent.

### Task 4.1: Restart-Safe Catch-Up Replay
- **Location**: `tools/repair_queryability_offline.py`, `tools/migrations/*`, `tests/*recovery*`
- **Description**: Verify replay idempotency and no duplicate/conflicting markers after interruption.
- **Complexity**: 6
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Stable counts and hashes after repeated replay runs.
- **Validation**:
  - Recovery simulation tests and checksum artifact.

### Task 4.2: Overnight SLA Soak Gate
- **Location**: `tools/wsl/start_soak.sh`, `tools/wsl/soak_verify.sh`, `tools/release_gate.py`
- **Description**: Add soak pass criteria:
  - lag trend strictly down
  - no persistent throughput zero when backlog exists
  - no memory-growth breach
  with explicit thresholds:
  - at least 2 consecutive snapshots with decreasing `freshness_lag_hours`
  - `throughput_records_per_s > 0` in every idle segment where `pending_records > 0`
  - RSS delta <= 10% versus soak baseline
- **Complexity**: 5
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Soak gate returns pass with freshness SLO met.
- **Validation**:
  - Soak summary artifact checked by release gate.

## Testing Strategy
- Unit:
  - metadata source selector and overrides
  - freshness lag calculation and gating
  - zero-throughput guard transitions
- Integration:
  - synthetic capture writes -> idle processing -> query-visible freshness advancement
  - stage1/stage2 markers and citation chain checks on new windows
- Determinism:
  - repeated gate runs produce same decision on same fixture input

## Acceptance Criteria (Global)
- Freshness:
  - `latest_queryable_ts_utc` must track recent capture windows (no multi-day lag under normal nightly idle).
  - `freshness_lag_hours` under configured threshold (default target: <= 12h, hard fail > 24h).
- Throughput:
  - when `pending_records > 0` and idle gate open, throughput must be positive after one escalation cycle.
- Correctness:
  - strict required suites still enforce evaluated totals with `skipped=0`, `failed=0`.
- Citeability:
  - accepted answers remain citation-backed from normalized layer only.

## Potential Risks & Gotchas
- Source split risk:
  - Batch reads one DB while query reads another can diverge.
  - Mitigation: explicit source arbitration telemetry + monotonic freshness assertions.
- Hot-writer instability:
  - Direct reads from `metadata.db` can fail under churn.
  - Mitigation: bounded retries, stability guard reason codes, no silent fallback.
- False green gates:
  - Historical pass can hide stale recency.
  - Mitigation: freshness gate mandatory in release and soak.
- Over-tuning for throughput:
  - Aggressive catch-up can violate idle budgets.
  - Mitigation: resource-budget gate and hysteresis-based controller.

## Rollback Plan
- Keep feature flags for new source arbitration and catch-up controller.
- Roll back to previous metadata routing via env override if regression appears.
- Preserve append-only audit records for all automatic routing decisions.
