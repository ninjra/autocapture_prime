# Plan: Stage1 Stage2 Golden Background Preprocessing Pipeline

**Generated**: 2026-02-26  
**Estimated Complexity**: High

## Overview
Make Stage1 + Stage2+ run as a deterministic golden background preprocessing pipeline so query answering is corpus-backed, citation-backed, and independent from raw media after Stage1 completion.

Current live blockers this plan targets:
- Stage1 partial only (`stage1_ok=11805`, `frames_total=18087`)
- Retention validation collapsed (`retention_ok=30`)
- Stage2 completion missing (`derived.ingest.stage2.complete=0`)
- Background throughput stalled (`pending_records=8779`, `throughput_records_per_s=0`)

Approach:
1. Lock one executable Stage1 completeness contract and enforce it before retention.
2. Restore Stage2 completion path and index freshness from normalized artifacts.
3. Unblock idle scheduler throughput and prove SLA control.
4. Gate strict correctness with deterministic artifacts (`40 + temporal 40`).
5. Prove overnight stability (memory/budget/restart safety).

## Prerequisites
- Data roots available:
  - `/mnt/d/autocapture/metadata.db`
  - `/mnt/d/autocapture/metadata.live.db`
  - `/mnt/d/autocapture/derived/stage1_derived.db`
- Query services reachable when online gates run (`8787`, `8788`).
- Stage1 raw-off policy remains in force for query path.
- Synthetic replay lane remains available when live writer/DB is unstable.

## Requirement Clarifications (resolved as defaults)
- No `request_user_input` tool in current mode; ambiguities are converted to explicit defaults in tasks.
- Strict semantics remain hard-gated:
  - Evaluated must equal expected total
  - Skipped must be 0
  - Failed must be 0
- Stage1 is the only raw-media consumer; Stage2+ and query must use normalized layer only.

## Skills by Sprint (and Why)
- Sprint 0: `ccpm-debugging`, `config-matrix-validator`, `shell-lint-ps-wsl`
  - Why: establish root cause and remove hidden config/contract drift before implementation.
- Sprint 1: `evidence-trace-auditor`, `python-testing-patterns`, `deterministic-tests-marshal`
  - Why: enforce Stage1 completeness semantics and deterministic validation.
- Sprint 2: `resource-budget-enforcer`, `observability-slo-broker`, `perf-regression-gate`
  - Why: restore Stage2 throughput while respecting idle budgets and proving lag controls.
- Sprint 3: `golden-answer-harness`, `evidence-trace-auditor`, `deterministic-tests-marshal`
  - Why: strict correctness and citation integrity for golden question gauntlets.
- Sprint 4: `state-recovery-simulator`, `policygate-penetration-suite`, `audit-log-integrity-checker`
  - Why: soak resilience, fail-closed behavior, and integrity under restart/fault conditions.
- All sprints: `shell-lint-ps-wsl`
  - Why: command correctness and operator-safe one-line runbooks.

## Sprint 0: Baseline Freeze and Blocker Reproduction
**Goal**: Capture deterministic baseline and lock contract/gate inputs.  
**Demo/Validation**:
- Baseline artifacts published under `artifacts/queryability/` and `artifacts/release/`.
- Repro commands produce identical failure taxonomy twice in a row.

### Task 0.1: Capture Stage1/Stage2 Baseline Snapshot
- **Location**: `tools/soak/stage1_completeness_audit.py`, `tools/soak/processing_health_snapshot.py`, `artifacts/queryability/`
- **Description**: Generate current counts and reason taxonomy for Stage1, retention, Stage2, throughput.
- **Complexity**: 3
- **Dependencies**: None
- **Acceptance Criteria**:
  - Snapshot includes `frames_total`, `stage1_ok`, `retention_ok`, `stage2_ok`, `pending_records`, `throughput_records_per_s`.
- **Validation**:
  - Same snapshot query run twice produces same schema and monotonic timestamps.

### Task 0.2: Freeze Golden Contract Inputs
- **Location**: `docs/contracts/real_corpus_expected_answers_v1.json`, `docs/query_eval_cases*.json`, `tools/release_gate.py`
- **Description**: Pin expected totals and strict gates so no hidden fallback/disable paths alter pass criteria.
- **Complexity**: 4
- **Dependencies**: Task 0.1
- **Acceptance Criteria**:
  - Required strict gates cannot be disabled without explicit release override flag.
- **Validation**:
  - `tests/test_release_gate.py` strict-disable tests pass.

### Task 0.3: Contract/Config Drift Matrix
- **Location**: `tools/gate_config_matrix.py`, `tools/gate_plugin_enablement.py`, `artifacts/release/non_vlm_readiness_latest.json`
- **Description**: Produce current plugin/config readiness matrix for Stage1/Stage2 critical components.
- **Complexity**: 4
- **Dependencies**: Task 0.1
- **Acceptance Criteria**:
  - Explicit `Y/N` status for each required plugin capability and gate.
- **Validation**:
  - Matrix tool returns deterministic JSON with `failed_count`.

## Sprint 1: Stage1 Completeness and Retention Correctness
**Goal**: Stage1 completeness is deterministic and retention markers only exist when contract-valid.  
**Demo/Validation**:
- `retention_ok == stage1_ok` for contract-complete frame set.
- No frame marked retention-eligible while failing Stage1 completeness contract.

### Task 1.1: Stage1 Completeness Contract Hard Gate
- **Location**: `autocapture/storage/stage1.py`, `autocapture_nx/processing/idle.py`, `autocapture_nx/ingest/handoff_ingest.py`
- **Description**: Enforce frame completeness prerequisites (UIA linkage/bboxes/hwnd/title/pid, source linkage, marker coherence) before retention marker emission.
- **Complexity**: 8
- **Dependencies**: Sprint 0
- **Acceptance Criteria**:
  - `retention.eligible` only for Stage1 contract-valid frame rows.
  - Invalid legacy markers are quarantined/reason-coded (non-destructive).
  - Rejected retention candidates emit deterministic reason telemetry (`stage1_rejection_reason`, count, source_record_id).
- **Validation**:
  - Unit tests for each failure reason + integration test for idempotent marker writes.

### Task 1.2: Stage1 Historical Revalidation + Repair Path
- **Location**: `tools/migrations/revalidate_stage1_markers.py`, `tools/repair_queryability_offline.py`, `tests/`
- **Description**: Re-audit old markers, repair missing Stage1 linkage artifacts where possible, and re-evaluate eligibility.
- **Complexity**: 7
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Revalidation report includes before/after counts and reason distribution.
  - No false-positive retention marker remains.
  - Soft-launch recovery mode can re-emit previously blocked markers after successful revalidation (explicitly flagged and auditable).
- **Validation**:
  - Migration integration fixtures (mixed-validity corpus) pass deterministically.

### Task 1.3: UIA Contract Completeness at Stage1
- **Location**: `plugins/builtin/processing_sst_uia_context/plugin.py`, `autocapture_nx/ingest/uia_obs_docs.py`, `tests/test_sst_uia_context_plugin.py`
- **Description**: Ensure metadata-first UIA resolution, fallback hash gate, deterministic IDs, valid bbox output, and linkage fields always attached.
- **Complexity**: 7
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - `obs.uia.focus/context/operable` emitted or deterministic no-op with explicit reason.
- **Validation**:
  - Unit/integration tests for metadata-first, fallback mismatch reject, deterministic IDs.

## Sprint 2: Stage2 Projection, Index Freshness, and Idle Throughput
**Goal**: Stage2+ records are created, indexed, and drain backlog in idle mode within budget.  
**Demo/Validation**:
- `derived.ingest.stage2.complete` increases from 0 and tracks Stage1-complete set.
- Stage2 index freshness counters show successful indexing and bounded lag.
- Background throughput > 0 with decreasing pending backlog.

### Task 2.1: Stage2 Completion Marker Path Recovery
- **Location**: `autocapture_nx/processing/idle.py`, `autocapture_nx/ingest/stage2_projection_docs.py`, `autocapture/storage/stage1.py`
- **Description**: Ensure Stage2 projection and completion marker writes execute for every eligible Stage1 frame and are idempotent.
- **Complexity**: 8
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Stage2 marker exists with `projection_ok=true` when projection docs succeed.
- **Validation**:
  - Integration tests for inserted/re-run marker behavior and error taxonomy.

### Task 2.2: Index Freshness Enforcement for Stage2 Docs
- **Location**: `autocapture_nx/processing/idle.py`, `autocapture_nx/kernel/query.py`, `tests/test_idle_processor.py`
- **Description**: Immediately index new Stage2 docs and track stale/fresh counters and lag metrics.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Newly projected docs become retrievable without manual backfill/index jobs.
- **Validation**:
  - Idle processor integration test proves retrieval hit immediately after projection.

### Task 2.3: Backlog Drain Control Loop
- **Location**: `autocapture_nx/runtime/batch.py`, `tools/soak/processing_health_snapshot.py`, `tools/soak/admission_check.py`
- **Description**: Tune adaptive idle scaling to avoid zero-throughput with backlog and emit deterministic lag/risk signals.
- **Complexity**: 7
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - `throughput_records_per_s > 0` while `pending_records > 0` during idle windows.
  - Idle drain remains within budget (`CPU<=50%`, `RAM<=50%`) with explicit violation counters.
- **Validation**:
  - Soak/admission check asserts throughput and lag trend toward zero.
  - Resource budget regression tests assert no sustained budget breach.

### Task 2.4: Metadata DB Instability Guardrails
- **Location**: `autocapture_nx/runtime/batch.py`, `tools/migrations/backfill_stage2_projection_docs.py`
- **Description**: Fail-safe behavior for DB churn/I/O errors with retry/backoff and deterministic blocked reasons rather than silent no-op loops.
- **Complexity**: 6
- **Dependencies**: Task 2.3
- **Acceptance Criteria**:
  - No silent infinite loop; explicit `blocked_reason` and guard telemetry emitted.
- **Validation**:
  - Fault-injection tests for disk I/O errors and unstable-writer scenarios.

## Sprint 3: Golden Strict Correctness (40 + Temporal 40)
**Goal**: Strict correctness and citeability pass on normalized corpus results.  
**Demo/Validation**:
- `evaluated=80`, `skipped=0`, `failed=0`
- Accepted answers have valid citations and matching evidence chains.

### Task 3.1: Unified Strict Manifest + Scoring Lock
- **Location**: `tools/query_eval_suite.py`, `tools/build_query_stress_pack.py`, `docs/query_eval_cases*.json`
- **Description**: Merge original and temporal sets into one strict manifest and lock exact-match policy.
- **Complexity**: 5
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Single strict manifest hash is published and reused by all runs.
- **Validation**:
  - Determinism test across repeated runs.

### Task 3.2: Citation Integrity Gate
- **Location**: `tools/gate_temporal40_semantic.py`, `tools/gate_screen_schema.py`, `autocapture_nx/kernel/query.py`
- **Description**: Reject accepted answers lacking citation chain to normalized records and resolve mismatch taxonomy.
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Every accepted claim has resolvable evidence IDs and hashable locator chain.
- **Validation**:
  - Evidence-chain audit tests and strict gate reports.

### Task 3.3: Stage2 Evidence Chain Audit
- **Location**: `tools/query_eval_suite.py`, `tools/gate_queryability.py`, `autocapture_nx/kernel/query.py`, `artifacts/queryability/`
- **Description**: Add a deterministic audit that verifies accepted answers resolve to normalized Stage2 evidence (`derived.sst.*`, `obs.uia.*`) and records evidence-set hash per accepted answer.
- **Complexity**: 6
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Accepted answers include Stage2/normalized evidence record IDs and resolvable hashes.
  - Audit artifact stores per-answer evidence-set digest and mismatch reasons.
- **Validation**:
  - Integration test: run representative queries and assert citation chain targets normalized records only.

### Task 3.4: Popup/Query Runtime Contract Pass
- **Location**: `tools/run_popup_regression_strict.sh`, `tools/verify_query_upstream_runtime_contract.py`, `artifacts/query_acceptance/`
- **Description**: Keep popup strict passing with bounded latency and no timeout-degraded responses when upstream healthy.
- **Complexity**: 6
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Popup strict 10/10 accepted under healthy service window.
- **Validation**:
  - Strict popup regression artifact with `accepted_count=10`, `failed_count=0`.

## Sprint 4: Overnight Reliability and Memory Stability
**Goal**: Prove stable long-run background operation under resource and integrity constraints.  
**Demo/Validation**:
- Memory soak gate passes with bounded RSS delta/tail span and bounded cache sizes.
- Restart/replay preserves marker/doc integrity.

### Task 4.1: Memory Leak Regression Gate
- **Location**: `autocapture_nx/kernel/query.py`, `tools/gate_memory_soak.py`, `tests/test_query_fast_cache_eviction.py`
- **Description**: Enforce bounded cache memory (TTL sweep, entry size cap, total bytes cap) and include in soak gating.
- **Complexity**: 5
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - No unbounded growth from query fast-cache under high-cardinality traffic.
- **Validation**:
  - Dedicated memory soak artifact + cache bound unit tests.

### Task 4.2: Crash/Restart Replay Integrity
- **Location**: `tools/repair_queryability_offline.py`, `tools/migrations/`, `tests/`
- **Description**: Verify idempotent replays (no duplicate or conflicting markers) after interruption.
- **Complexity**: 7
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Re-run of repair/backfill produces stable counts/hashes.
- **Validation**:
  - State-recovery simulation tests with forced interruption.

### Task 4.3: Policy/Sandbox Fuzz for Background Pipeline
- **Location**: `tests/`, `autocapture_nx/plugin_system/`, `plugins/`
- **Description**: Fuzz malformed inputs through Stage1/Stage2 path and ensure fail-open or fail-closed behavior matches contract without crash.
- **Complexity**: 6
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Zero safety-critical crashes; deterministic blocked reasons.
- **Validation**:
  - Policy/fuzz suite reports and artifact summary.

## Sprint 5: Release Proof and Operator Handoff
**Goal**: Ship one deterministic proof bundle and one daily-ops runbook for continuous golden background operation.  
**Demo/Validation**:
- Release gate reads full proof bundle and passes/fails deterministically.
- Operator can run one-line daily commands to verify health and backlog.

### Task 5.1: Unified Proof Bundle
- **Location**: `tools/release_gate.py`, `artifacts/release/`, `docs/reports/`
- **Description**: Aggregate Stage1, Stage2, query strictness, popup strictness, memory soak, and backlog/lag metrics.
- **Complexity**: 5
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - Bundle includes pass/fail and reason taxonomy for each gate.
  - Bundle includes popup service contract verification (`8787`, `8788`) with proof that citations in accepted responses resolve to normalized records.
- **Validation**:
  - Release gate strict run over bundle.

### Task 5.2: Golden Background Runbook
- **Location**: `docs/runbooks/`, `README.md`
- **Description**: Add short one-line operator workflows for:
  - starting/stopping idle background drain
  - checking Stage1/Stage2 backlog metrics
  - running strict health gates
- **Complexity**: 3
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Commands are shell-linted, practical, and reproducible.
- **Validation**:
  - Dry-run checklist executed end-to-end.

## Testing Strategy
- Unit:
  - Stage1 marker contract checks
  - Stage2 projection + completion semantics
  - query fast-cache leak bounds
- Integration:
  - Stage1 -> Stage2 -> retrieval continuity
  - Stage2 doc -> citation match test (`query` answer claims must resolve to normalized Stage2 IDs)
  - popup strict runtime behavior
  - idempotent backfill/repair
- Regression gates:
  - Original 40 strict
  - Temporal 40 strict
  - Projection alignment + queryability + memory soak
  - Resource budget gate for idle drain (`CPU<=50%`, `RAM<=50%`)
- Soak:
  - Overnight background drain with retention-risk + lag trend checks

## Potential Risks & Gotchas
- DB writer instability can mask pipeline correctness.
  - Mitigation: explicit `metadata_db_guard` fail-safe and deterministic blocked reasons.
- Stage1 marker coverage may improve while retention coverage remains low due to strict contract failures.
  - Mitigation: reason-coded contract audit + targeted repair worker by reason bucket.
- Stage2 docs may exist without completion markers if projection writes bypass marker path.
  - Mitigation: enforce completion marker writes in all Stage2 entry points and test parity.
- Strict golden pass can drift if case manifests or scoring policy diverge.
  - Mitigation: single canonical strict manifest hash + deterministic scorer tests.

## Rollback Plan
- Keep changes behind explicit config flags for:
  - Stage2 projection backfill path
  - strict retention gating behavior
  - cache byte-limit enforcement
- If regression appears:
  - revert to last passing release gate artifact commit
  - keep audit/metrics paths enabled so failure reason remains visible
  - replay repair/backfill after fix using idempotent tooling
