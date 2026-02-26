# Plan: Remaining Golden Pipeline Closure

**Generated**: 2026-02-26
**Estimated Complexity**: High

## Overview
Close the remaining gaps so the pipeline continuously answers arbitrary natural-language questions from normalized corpus data with strict grounding and deterministic failure behavior, while Stage1 source fixes are in flight.

Approach:
1. Keep Stage1/Stage2/query contracts green on existing corpus.
2. Make projection/index freshness automatic so retrieval never lags writes.
3. Enforce strict correctness gates (`40 + temporal 40`) with exact-answer and citation proof.
4. Harden runtime reliability and budget behavior for overnight soak.

## Skill Use Matrix
- Sprint 1:
  - `config-matrix-validator` to lock plugin/service/config preconditions and remove hidden disablement.
  - `evidence-trace-auditor` to define and verify citation-grounded answer requirements.
- Sprint 2:
  - `golden-answer-harness` to run strict scenario gauntlets and enforce exactness.
  - `deterministic-tests-marshal` to eliminate flake in strict gates.
- Sprint 3:
  - `observability-slo-broker` to define and gate on backlog/lag/risk SLOs.
  - `perf-regression-gate` to pin query latency and throughput expectations.
- Sprint 4:
  - `resource-budget-enforcer` to validate idle/active budget behavior.
  - `state-recovery-simulator` to validate restart/recovery and replay safety.
  - `policygate-penetration-suite` to verify fail-closed behavior under malformed inputs.
- All sprints:
  - `shell-lint-ps-wsl` for command linting and safe operator runbooks.

## Prerequisites
- Stable writable data root: `/mnt/d/autocapture`
- Working DBs: `metadata.db`, `derived/stage1_derived.db`, `lexical.db`, `vector.db`
- Query services reachable when running online gates (`8787`, `8788`, model endpoint)
- Strict no-raw-fallback policy remains enforced for query path
- Synthetic fixture lane available for offline validation when live source/services are unstable

## Sprint 1: Contract and Freshness Baseline
**Goal**: Make Stage1/Stage2/queryability status continuously true on normalized data and remove stale projection/index blockers.
**Demo/Validation**:
- `artifacts/queryability/gate_queryability_live.json` reports `ok=true`
- `metadata_projection` counts match `metadata` for Stage1/Stage2 record types
- Stage2 backlog remains `0` during idle windows

### Task 1.1: Stage Contract Snapshot
- **Location**: `tools/query_pipeline_triage.py`, `artifacts/queryability/`
- **Description**: Produce current contract snapshot and freeze it as baseline artifact.
- **Complexity**: 3
- **Dependencies**: None
- **Acceptance Criteria**:
  - Baseline artifact includes `frames_total`, `frames_queryable`, blocked counts, and release status.
- **Validation**:
  - Run triage tool and verify deterministic JSON schema.

### Task 1.2: Projection Sync Enforcement
- **Location**: `plugins/builtin/storage_sqlcipher/plugin.py`, `tools/`
- **Description**: Add/verify projection reconciliation step so `metadata_projection` cannot drift from `metadata` for query-critical types.
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Automatic projection catch-up path exists and is idempotent.
  - Counts for `evidence.capture.frame`, `derived.ingest.stage1.complete`, `retention.eligible`, `derived.ingest.stage2.complete`, `derived.sst.*` stay aligned.
- **Validation**:
  - Deterministic check script + unit test for projection backfill/reconcile path.

### Task 1.3: Index Freshness Guard
- **Location**: `autocapture_nx/processing/idle.py`, `plugins/builtin/retrieval_basic/plugin.py`, `tools/`
- **Description**: Ensure lexical/vector indexes are refreshed against newly projected Stage2 docs and expose stale-index counters.
- **Complexity**: 6
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - No “records exist but retrieval empty” due to index lag.
  - Freshness lag metric emitted.
- **Validation**:
  - Integration test inserts derived docs and verifies retrieval hit availability within bounded time.

### Task 1.4: Synthetic Replay Continuity Lane
- **Location**: `tools/synthetic_uia_contract_pack.py`, `tools/run_synthetic_gauntlet.py`, `docs/test sample/`
- **Description**: Keep full validation runnable without live Stage1 source by maintaining synthetic normalized fixtures and replay scripts.
- **Complexity**: 5
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Offline run can execute Stage2/query gates and produce deterministic artifacts.
  - Live-source fixes can supersede synthetic path without changing gate contracts.
- **Validation**:
  - Synthetic run outputs strict gate artifacts with deterministic hashes.

## Sprint 2: Strict Answer Correctness Closure
**Goal**: Pass strict answer gates on full corpus without special-casing.
**Demo/Validation**:
- `evaluated=80`, `skipped=0`, `failed=0` for original + temporal sets
- All accepted answers have non-empty citations and grounded evidence records

### Task 2.1: Casepack Canonicalization
- **Location**: `docs/query_eval_cases*.json`, `tools/build_query_stress_pack.py`
- **Description**: Normalize all question packs, expected answer match rules, and exactness policy.
- **Complexity**: 4
- **Dependencies**: Sprint 1, Task 1.4
- **Acceptance Criteria**:
  - A single canonical merged manifest for strict run exists.
  - Manifest supports both live and synthetic replay datasets with identical scoring rules.
- **Validation**:
  - Deterministic manifest hash generated in artifact.

### Task 2.2: Strict Runner Hard-Fail Rules
- **Location**: `tools/query_eval_suite.py`, `tools/run_synthetic_gauntlet.py`
- **Description**: Enforce exact-match and evidence-match rules; block partials except generic/no-expected cases.
- **Complexity**: 7
- **Dependencies**: Task 2.1, Task 1.4
- **Acceptance Criteria**:
  - Any partial/mismatch is counted failed with explicit reason taxonomy.
- **Validation**:
  - Unit tests for scoring policy; regression fixture with known mismatch cases.

### Task 2.3: Citation Chain Verification
- **Location**: `tools/gate_temporal40_semantic.py`, `tools/gate_screen_schema.py`, `autocapture_nx/ux/facade.py`
- **Description**: Validate each accepted answer has valid citation chain into normalized records; reject uncitable answers.
- **Complexity**: 7
- **Dependencies**: Task 2.2, Task 1.4
- **Acceptance Criteria**:
  - Accepted answers include citations and resolvable record IDs.
- **Validation**:
  - Gate output includes `top_failure_reasons` and citation integrity stats.

## Sprint 3: Query Runtime Stability and Throughput
**Goal**: Keep popup/query path fast, deterministic, and non-degrading under normal load.
**Demo/Validation**:
- Popup strict regression passes `10/10`
- No timeout-induced degraded responses when upstream healthy
- p95 latency within configured budget

### Task 3.1: Timeout/Budget Guardrails
- **Location**: `plugins/builtin/retrieval_basic/plugin.py`, `autocapture_nx/ux/facade.py`
- **Description**: Ensure bounded fallback scans and immediate deterministic error payloads for missing capability/boot-failure scenarios.
- **Complexity**: 6
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - No long blocking fallback path in popup query route.
- **Validation**:
  - Existing popup strict script + targeted unit tests for budget-exceeded branches.

### Task 3.2: PromptOps Contract Enforcement
- **Location**: `promptops/`, `autocapture_nx/ux/facade.py`, `tools/gate_promptops_policy.py`
- **Description**: Ensure pre-query and post-query system context injection is deterministic and versioned.
- **Complexity**: 5
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Prompt pipeline records active prompt policy IDs in artifacts.
- **Validation**:
  - Gate confirms policy present and refresh behavior configured.

### Task 3.3: Query SLO Gate
- **Location**: `tools/run_popup_regression_strict.sh`, `artifacts/query_acceptance/`
- **Description**: Add strict SLO check output (`p50`, `p95`, failure class histogram) as required release proof.
- **Complexity**: 4
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Artifact contains sample count, acceptance counts, and latency distribution.
  - Artifact path is fixed: `artifacts/query_acceptance/popup_slo_latest.json`.
- **Validation**:
  - Gate fails closed when SLO violated.

## Sprint 4: Reliability, Budgets, and Safety
**Goal**: Ensure pipeline remains safe and stable during long idle/overnight operation.
**Demo/Validation**:
- Soak run completes with no memory growth trend breach
- Idle budgets honored (`CPU<=50%`, `RAM<=50%`) while Stage2+ progresses
- Recovery from restart preserves correctness

### Task 4.1: Resource Budget Conformance Tests
- **Location**: `tools/wsl/run_soak.sh`, `tools/wsl/soak_verify.sh`, `tools/`
- **Description**: Add budget assertions for active/idle transitions and Stage2 throughput impact.
- **Complexity**: 6
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Budget violations are explicit gate failures.
- **Validation**:
  - Soak verify emits budget pass/fail and utilization percentiles.

### Task 4.2: Crash/Restart Replay Safety
- **Location**: `tools/repair_queryability_offline.py`, `tools/migrations/`, `tests/`
- **Description**: Validate idempotent replay and marker/doc integrity after forced interruption.
- **Complexity**: 7
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Re-running repair/backfill does not duplicate or corrupt required records.
- **Validation**:
  - Integration test with interrupted run and replay.

### Task 4.3: PolicyGate Fuzz Pass
- **Location**: `tests/`, `autocapture_nx/plugin_system/`, `plugins/`
- **Description**: Fuzz malformed plugin/external inputs and verify fail-open/fail-closed behavior matches contract.
- **Complexity**: 7
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - No runtime crashes from malformed input corpus.
- **Validation**:
  - Fuzz suite reports zero safety-critical failures.

## Sprint 5: Release Proof and Operator Handoff
**Goal**: Produce deterministic proof package that system is ready for arbitrary corpus queries.
**Demo/Validation**:
- Single release bundle includes all required gate artifacts and summary
- Operator runbook executes with short one-line commands

### Task 5.1: Unified Proof Bundle
- **Location**: `artifacts/release/`, `tools/release_gate.py`, `docs/reports/`
- **Description**: Aggregate Stage1/Stage2/query/popup/golden metrics into one machine-readable bundle.
- **Complexity**: 5
- **Dependencies**: Sprint 4, Task 3.3
- **Acceptance Criteria**:
  - Bundle includes strict matrices, latency stats, coverage ratios, and failure taxonomy.
  - Bundle includes `artifacts/query_acceptance/popup_slo_latest.json` and fails if missing or non-passing.
- **Validation**:
  - Release gate consumes bundle and returns deterministic pass/fail.

### Task 5.2: Operator Runbook Finalization
- **Location**: `docs/runbooks/`, `README.md`
- **Description**: Publish short-command runbook for daily operations and incident triage.
- **Complexity**: 3
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Commands are one-line, practical, and shell-specific.
- **Validation**:
  - Dry-run checklist executed end-to-end.

### Task 5.3: Post-Stage1-Fix Live Rebaseline
- **Location**: `tools/release_gate.py`, `artifacts/release/`, `artifacts/queryability/`
- **Description**: After Stage1 source fix lands, rerun full live-source closure gates and publish final rebaseline artifact set.
- **Complexity**: 4
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Live-source run reproduces strict pass conditions achieved on synthetic lane.
  - Rebaseline artifact includes before/after deltas for backlog, queryability ratio, and strict failure counts.
- **Validation**:
  - Deterministic rebaseline JSON and markdown report generated.

## Testing Strategy
- Unit tests:
  - Projection reconciliation
  - Query fallback budget paths
  - PromptOps policy injection markers
- Integration tests:
  - Stage1→Stage2 lineage and queryability
  - Popup query strict acceptance
  - Replay/idempotency after interrupted processing
- Regression gates:
  - Original 40 strict
  - Temporal 40 strict
  - Additional grounded temporal set strict
- Soak:
  - Overnight run with memory, latency, throughput, and budget checks

## Potential Risks & Gotchas
- Projection drift can silently hide fresh records from retrieval.
  - Mitigation: mandatory reconcile step + freshness metric gate.
- Markers may exist but fail strict payload semantics.
  - Mitigation: revalidation pass before queryability gating.
- Upstream service instability may mask local correctness.
  - Mitigation: split local/offline gates from service-online gates.
- Stage1 source instability can block pipeline progress if live-only assumptions leak in.
  - Mitigation: enforce synthetic replay lane parity with live contracts.
- Strict answer gates can pass with brittle heuristics if not citation-checked.
  - Mitigation: citation chain verification as acceptance requirement.
- Long-running gates can hang under DB churn.
  - Mitigation: bounded timeouts + explicit stale/unstable DB failure reasons.

## Rollback Plan
- Keep all migration/backfill operations idempotent and additive.
- If a new gate path regresses runtime:
  - Disable new gate in config flag.
  - Restore prior gate scripts from last green commit.
- If projection reconcile introduces errors:
  - Rebuild `metadata_projection` from `metadata` using one-shot rebuild command.
  - Re-run queryability and strict gates before resuming normal operation.
