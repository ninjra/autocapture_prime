# Plan: Stage2 Query-Ready Raw-Off Normalized Layer

**Generated**: 2026-02-20  
**Estimated Complexity**: High

## Overview
Implement a hard split:
- Stage1 ingest is the only path allowed to read raw media.
- Stage2+ query/reasoning/indexing operates strictly on normalized artifacts.
- Retention eligibility is emitted only when reap-safe completeness is proven for each frame.

## Progress Snapshot (2026-02-20)
- Completed: Sprint 0 Task 0.1 (`mark_stage1_and_retention` fail-closed for frames; legacy markers quarantined until validated).
- Completed: Sprint 0 Task 0.2 (`query.py` raw-off hard-stop now covers screen pipeline and `_load_evidence_image_bytes`).
- Completed: Sprint 3 Task 3.4 migration scaffolding (`tools/migrations/revalidate_stage1_markers.py`) + tests + live run report at `docs/reports/stage1_marker_revalidation_latest.json`.
- Completed: Stage1 UIA delta for handoff path (`autocapture_nx/ingest/handoff_ingest.py`) now emits deterministic `obs.uia.focus/context/operable` and blocks frame retention markering when UIA linkage is missing.
- Completed: Historical UIA backfill tool (`tools/migrations/backfill_uia_obs_docs.py`) + tests; latest attempt report at `docs/reports/stage1_uia_backfill_attempt_latest.json`.
- Blocker: local projection DB appears to be rewritten by an external writer, so historical backfill must run in the authoritative runtime writer path.
- Remaining high-impact gap: contract-complete Stage1 still needs explicit normalized-coverage auditor from Sprint 1/Task 1.2 to prove no missing artifact classes.

This plan optimizes the 4 pillars:
- Performance: bounded parallel Stage1 + cheap-first normalization; no query-time extraction.
- Accuracy: mandatory completeness contract per frame and strict lineage.
- Security: fail-closed raw-off policy outside Stage1 + sandbox/capability enforcement.
- Citeability: every query claim must resolve to normalized records with deterministic IDs and hashes.

## Prerequisites
- Hypervisor sidecar contract is stable for `evidence.uia.snapshot` and frame `uia_ref`.
- Existing Stage1 markers and UIA ingestion plugin are present.
- Local test environment has `metadata.db` fixture generation and golden harness runnable.
- Branch policy allows staged rollout with feature flags.

## Skill Allocation (Now + Execution)
- Sprint 1: `plan-harder`, `config-matrix-validator`, `evidence-trace-auditor`
  - Why: freeze exact reap-safe contract and measurable acceptance matrix.
- Sprint 0: `ccpm-debugging`, `policygate-penetration-suite`, `shell-lint-ps-wsl`
  - Why: immediate guardrails to prevent unsafe retention/query behavior while full implementation lands.
- Sprint 2: `policygate-penetration-suite`, `shell-lint-ps-wsl`, `security-threat-model`
  - Why: enforce raw-off behavior with explicit trust boundaries.
- Sprint 3: `python-testing-patterns`, `deterministic-tests-marshal`, `resource-budget-enforcer`
  - Why: implement Stage1 completeness logic and prove deterministic behavior under budget.
- Sprint 4: `golden-answer-harness`, `evidence-trace-auditor`, `perf-regression-gate`
  - Why: prove Stage2 queryability, citations, and no latency regressions.
- Sprint 5: `state-recovery-simulator`, `observability-slo-broker`, `audit-log-integrity-checker`
  - Why: guarantee soak safety, lag visibility, and replay integrity.

## Sprint 1: Freeze Reap-Safe Contract
**Goal**: Define exactly what “Stage1 complete and reap-safe” means per frame.  
**Demo/Validation**:
- Contract doc + schema committed.
- Coverage report generated from live/synthetic metadata.
- Clear pass/fail table for every required artifact class.

### Task 1.1: Define Reap-Safe Stage1 Artifact Contract
- **Location**: `docs/contracts/stage1-reap-safe-contract.md`, `contracts/stage1_reap_safe.schema.json`
- **Description**: Specify mandatory per-frame normalized artifacts and linkage fields:
  - core frame normalized record
  - UIA normalized records (`obs.uia.focus/context/operable`)
  - HID/input normalized record linkage
  - OCR/text normalized record(s)
  - deterministic IDs and content hashes
  - lineage pointers to source frame/UIA/input record IDs
- **Complexity**: 5/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - Contract includes required/optional sections and cardinality.
  - Contract includes deterministic ID formulae.
  - Contract includes strict fail reasons for non-complete frames.
- **Validation**:
  - JSON schema validation test with valid/invalid examples.

### Task 1.2: Build Contract Coverage Auditor
- **Location**: `tools/stage1_contract_audit.py`, `tests/test_stage1_contract_audit.py`
- **Description**: Add a deterministic auditor that outputs:
  - total frames
  - contract-complete frames
  - missing-fields breakdown
  - marker mismatch breakdown (`retention.eligible` present while incomplete)
- **Complexity**: 6/10
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Auditor runs on production DB and synthetic DB.
  - Outputs machine-readable JSON and human summary.
- **Validation**:
  - Unit tests for each missing-field category.
  - Snapshot test for summary payload shape.

### Task 1.3: Update 4-Pillar Implementation Matrix
- **Location**: `docs/reports/implementation_matrix_stage1_stage2_raw_off.md`
- **Description**: Add matrix rows tying each contract requirement to module + tests + gate.
- **Complexity**: 3/10
- **Dependencies**: Task 1.1, Task 1.2
- **Acceptance Criteria**:
  - Every contract field maps to executable verification.
- **Validation**:
- Lint/check script confirms no unmapped requirement rows.

## Sprint 0: Immediate Guardrails
**Goal**: Prevent unsafe behavior immediately before full contract rollout.  
**Demo/Validation**:
- New retention markers are blocked unless strict completeness check passes.
- Query path is explicitly raw-off enforced (no raw media reads).
- Guardrail telemetry appears in runtime snapshots.

### Task 0.1: Retention Marker Safety Switch
- **Location**: `autocapture/storage/stage1.py`, `autocapture_nx/processing/idle.py`, `autocapture_nx/ingest/handoff_ingest.py`
- **Description**:
  - Add temporary fail-closed switch: if completeness cannot be proven, do not emit `retention.eligible`.
  - Persist explicit reason code for blocked marker.
- **Complexity**: 5/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - No new unsafe retention markers can be emitted.
- **Validation**:
  - Unit test confirms blocked marker path.

### Task 0.2: Raw-Off Query Hard Stop
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**:
  - Hard-disable any query-time branch that touches `storage.media`.
  - Return deterministic “not available yet” when normalized sources are missing.
- **Complexity**: 4/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - Query code has zero raw media access path in raw-off mode.
- **Validation**:
  - Query tests assert media store is never called.

### Task 0.3: Guardrail Telemetry
- **Location**: `autocapture_nx/runtime/batch.py`, `autocapture/runtime/conductor.py`
- **Description**:
  - Emit counters for blocked retention markers and blocked raw query attempts.
- **Complexity**: 3/10
- **Dependencies**: Task 0.1, Task 0.2
- **Acceptance Criteria**:
  - Counters visible in loop snapshots.
- **Validation**:
  - Telemetry payload schema tests.

## Sprint 2: Enforce Raw-Off Runtime Boundaries
**Goal**: Ensure only Stage1 ingestor can touch raw media; all query paths are normalized-only.  
**Demo/Validation**:
- Query paths fail-closed if they attempt raw access.
- Stage1 ingest still reads raw and continues functioning.
- Pen tests show non-Stage1 components cannot access `storage.media`.

### Task 2.1: Add Raw-Off Policy Config and Runtime Guard
- **Location**: `config/default.json`, `contracts/config_schema.json`, `autocapture_nx/kernel/loader.py`
- **Description**: Add and enforce policy:
  - `runtime.raw_off.enabled=true`
  - `runtime.raw_off.allowed_raw_consumers=["stage1.ingest","stage1.idle"]`
  - capability guard denies `storage.media` outside allowlist.
- **Complexity**: 7/10
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Any non-allowlisted component requesting media is denied with audit log event.
  - Stage1 allowlisted paths continue functioning.
- **Validation**:
  - Unit tests for allow/deny matrix.
  - Audit log assertions for denied attempts.

### Task 2.2: Remove/Disable Query-Time Raw Pipelines
- **Location**: `autocapture_nx/kernel/query.py`, related query config sections
- **Description**:
  - Hard-disable screen pipeline custom claims that decode frame bytes.
  - Keep `schedule_extract=false` instant response path.
  - Ensure no query code path calls `extract_on_demand` or media decode under raw-off.
- **Complexity**: 6/10
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Query path executes with no `storage.media` usage.
  - Returns deterministic “not available yet” when normalized data missing.
- **Validation**:
  - Unit tests with mocked media store asserting zero calls.
  - Integration test for `schedule_extract=false` no-work behavior.

### Task 2.3: PolicyGate + Sandbox Penetration Checks
- **Location**: `tests/test_raw_off_policygate.py`, `tools/security/raw_off_probe.py`
- **Description**: Add negative tests/fuzz probes for bypass attempts (plugin direct get, fallback helpers, alternate query branch).
- **Complexity**: 5/10
- **Dependencies**: Task 2.1, Task 2.2
- **Acceptance Criteria**:
  - No bypass path can read raw media outside Stage1.
- **Validation**:
  - Pen suite run reports 0 policy bypasses.

## Sprint 3: Stage1 Completeness Gate Before Retention
**Goal**: Retention marker only when frame is fully reap-safe per contract.  
**Demo/Validation**:
- Frames missing required normalized artifacts do not receive `retention.eligible`.
- Fully normalized frames receive markers deterministically.
- Backfill converges historical backlog.

### Task 3.1: Implement Stage1 Completeness Evaluator
- **Location**: `autocapture/storage/stage1.py`, `autocapture_nx/processing/idle.py`, `autocapture_nx/ingest/handoff_ingest.py`
- **Description**:
  - Add `is_reap_safe_complete(record_id, metadata)` using Sprint 1 schema rules.
  - Make `mark_stage1_and_retention` gate retention on completeness result.
  - Persist reason codes for incomplete frames.
- **Complexity**: 8/10
- **Dependencies**: Sprint 1, Sprint 2
- **Acceptance Criteria**:
  - Marker writing is impossible for incomplete frames.
  - Complete frames always produce both stage1 and retention markers idempotently.
- **Validation**:
  - Unit tests for each completeness failure mode.
  - Marker consistency tests (no false-positive retention).

### Task 3.2: Add Stage1 Backfill/Repair Worker
- **Location**: `autocapture_nx/processing/idle.py`, `autocapture_nx/runtime/batch.py`
- **Description**:
  - Add bounded backfill worker to generate missing normalized artifacts for historical frames.
  - Re-evaluate completeness and write markers only when contract passes.
  - Respect idle CPU/RAM budgets.
- **Complexity**: 7/10
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Backfill progress metrics increase monotonically.
  - Worker remains within budget caps.
- **Validation**:
  - Budget tests and deterministic progress tests.

### Task 3.3: Strengthen UIA/HID/OCR Normalized Outputs
- **Location**: `plugins/builtin/processing_sst_uia_context/plugin.py`, `autocapture_nx/processing/sst/persist.py`, Stage1 normalization writers
- **Description**:
  - Ensure required UIA docs and bbox validity.
  - Ensure HID summary linkage and OCR text normalization are stored in contract-defined records.
  - Ensure deterministic IDs and stable reruns.
- **Complexity**: 7/10
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Contract auditor reports required normalized artifact presence.
  - Deterministic ID stability across reruns.
- **Validation**:
  - UIA bbox and ID stability tests.
  - OCR/HID linkage tests.

### Task 3.4: Historical Marker Revalidation Migration
- **Location**: `tools/migrations/revalidate_stage1_markers.py`, `tests/test_stage1_marker_revalidation_migration.py`, `docs/reports/stage1_marker_revalidation_latest.json`
- **Description**:
  - Re-audit all historical `retention.eligible` and `derived.ingest.stage1.complete` records against the new completeness contract.
  - Emit compensating status records for any legacy marker that no longer passes contract (no destructive deletion).
  - Produce migration report with before/after counts and reason distribution.
- **Complexity**: 7/10
- **Dependencies**: Task 3.1, Task 3.2, Task 3.3
- **Acceptance Criteria**:
  - Legacy marker state is reconciled to contract truth.
  - No frame remains marked eligible without passing completeness.
- **Validation**:
  - Migration integration test with mixed-validity fixtures.
  - Auditor comparison snapshot before/after migration.

## Sprint 4: Stage2 Query-Ready from Normalized Layer Only
**Goal**: Make query correctness depend exclusively on normalized records and indexes.  
**Demo/Validation**:
- Query succeeds against normalized-only corpus.
- Raw media physically absent does not break Stage2 answering.
- Citations resolve to normalized artifacts + lineage.

### Task 4.1: Expand Retrieval Coverage to Reap-Safe Normalized Types
- **Location**: `plugins/builtin/retrieval_basic/plugin.py`, `autocapture_nx/kernel/query.py`
- **Description**:
  - Include normalized record families in candidate retrieval/scoring.
  - Maintain deterministic ranking with citation-ready trace fields.
- **Complexity**: 6/10
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Retrieval returns relevant normalized hits without raw fallback.
- **Validation**:
  - Retrieval fixture tests with normalized-only stores.
  - Citation lineage fixture asserts presence of normalized `record_id`, `record_hash`, `source_record_id`, and lineage refs for each claim.

### Task 4.2: Raw-Off Replay Harness (Always-On in CI and Soak)
- **Location**: `tools/replay/run_raw_off_replay.sh`, `tests/test_raw_off_replay.py`
- **Description**:
  - Replay queries with raw media hidden/unmounted.
  - Assert no raw reads and stable answer behavior.
  - Fail build if any query path touches raw.
- **Complexity**: 7/10
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Raw-off replay gate runs by default in validation pipeline.
- **Validation**:
  - Gate returns non-zero on any media access attempt.

### Task 4.3: Golden Strict Query Gate on Normalized-Only Mode
- **Location**: `tools/run_40q_strict_raw_off.sh`, `docs/reports/golden_40q_raw_off_latest.json`
- **Description**:
  - Run 40-question strict gauntlet with raw-off enforced.
  - Require `evaluated=40, skipped=0, failed=0`.
- **Complexity**: 8/10
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Gate passes in strict mode with normalized-only sources.
- **Validation**:
  - Persisted report artifact with deterministic fields and run hash.
  - Gate fails if any claim lacks deterministic normalized citation lineage fields.

## Sprint 5: Soak, Metrics, and Operational Safety
**Goal**: Sustain overnight throughput and guarantee 6-day retention safety margins.  
**Demo/Validation**:
- Soak dashboard reports lag/risk metrics in real time.
- Backlog clears faster than retention horizon.
- Recovery/restart keeps integrity.

### Task 5.1: Add Stage1/Stage2 Lag and Risk Metrics
- **Location**: `autocapture_nx/runtime/batch.py`, `autocapture/runtime/conductor.py`, `docs/ops/stage_lag_runbook.md`
- **Description**:
  - Publish `pending_records`, `completed_records`, `throughput_records_per_s`, `projected_lag_hours`, `retention_risk`.
  - Add separate counters for contract-complete vs marker-complete.
- **Complexity**: 5/10
- **Dependencies**: Sprint 3, Sprint 4
- **Acceptance Criteria**:
  - Metrics are emitted every loop and persisted in soak artifacts.
- **Validation**:
  - Telemetry unit tests and soak artifact schema checks.

### Task 5.1b: Retention Horizon Enforcement Tests
- **Location**: `tests/test_retention_risk_enforcement.py`, `tools/soak/verify_retention_horizon.sh`
- **Description**:
  - Simulate backlog growth to force `projected_lag_hours` beyond the 6-day horizon.
  - Verify alarms/throttles/priority escalation trigger and recovery path lowers lag back below threshold.
- **Complexity**: 6/10
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Risk state transitions are deterministic and visible in artifacts.
  - Healthy soak is declared only when projected lag remains inside retention horizon.
- **Validation**:
  - Deterministic simulation tests for threshold crossing and recovery.
  - Soak verification script enforces max-lag SLO.

### Task 5.2: Crash/Restart Integrity and Replay Safety
- **Location**: `tests/test_stage1_restart_integrity.py`, `tools/soak/soak_verify_stage1_stage2.sh`
- **Description**:
  - Crash-fuzz Stage1/Stage2 loop, restart, verify no contract regressions and no duplicate/corrupt markers.
- **Complexity**: 6/10
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Restart recovers with idempotent state and no marker corruption.
- **Validation**:
  - Recovery simulation suite + integrity checks.

### Task 5.3: Final Acceptance Package
- **Location**: `docs/reports/stage1_stage2_raw_off_acceptance_latest.md`
- **Description**: Produce final artifact bundle:
  - DB counts by required record types
  - 3 lineage examples frame -> normalized -> query citation
  - raw-off replay pass evidence
  - strict golden 40/40 pass evidence
- **Complexity**: 4/10
- **Dependencies**: All prior sprints
- **Acceptance Criteria**:
  - Package is sufficient for sign-off without manual reconstruction.
- **Validation**:
  - Review checklist complete with file pointers and hashes.

## Testing Strategy
- Unit tests:
  - completeness evaluator
  - raw-off capability guard
  - query no-raw invariants
  - deterministic ID/bbox validation
- Integration tests:
  - frame ingest -> normalized artifact generation -> marker gating
  - retrieval/query against normalized-only corpus
- End-to-end gates:
  - raw-off replay gate always-on
  - strict golden 40/40 gate
  - soak lag/risk envelope gate
- Determinism:
  - repeated-run equality checks for IDs, markers, and acceptance reports.

## Potential Risks & Gotchas
- Risk: Existing historical markers may have been written before completeness gate.
  - Mitigation: mandatory migration task revalidates legacy markers and emits compensating records.
- Risk: Query quality drop when raw fallback is removed.
  - Mitigation: expand normalized artifact richness before hard cutover; keep explicit “not available yet”.
- Risk: Budget overruns while backfilling.
  - Mitigation: adaptive worker pool + hard CPU/RAM ceiling checks + SLA-based throttling.
- Risk: Citation drift across reruns.
  - Mitigation: deterministic IDs and stable ordering in retrieval/rerank.
- Risk: Plugin bypass to media capability.
  - Mitigation: centralized capability allowlist + penetration tests + audit hooks.

## Rollback Plan
- Feature-flag rollback:
  - toggle `runtime.raw_off.enabled=false` only in emergency.
  - keep query-time extraction disabled unless incident-approved.
- Marker rollback:
  - preserve append-only audit; write compensating records rather than delete.
- Deployment rollback:
  - revert to previous tag + run contract auditor to detect partial migration impact.
- Data safety:
  - do not purge existing normalized artifacts during rollback.
