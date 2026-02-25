# Plan: Any-Question Corpus Readiness

**Generated**: 2026-02-25  
**Estimated Complexity**: High

## Overview
Deliver a single golden pipeline that can answer any user question about on-computer activity **when evidence exists in normalized corpus**, and otherwise returns deterministic uncitable outcomes (`NOT_FOUND` / `NEEDS_CLARIFICATION`) with no fabrication.

This plan prioritizes the 4 pillars together:
- Performance: predictable latency and throughput under idle/active constraints.
- Accuracy: exactness checks and strict correctness gates.
- Security: fail-closed capability boundaries and no raw-query fallback.
- Citeability: every `OK` claim traceable to normalized evidence lineage.

## Scope and Definitions
- In scope:
  - Stage1/Stage2+ completion proof and query-readiness proof per frame/session.
  - Normalized-only query path (no raw media reads at query time).
  - Strict gauntlets: original Q40 + temporal Q40 + randomized corpus queries.
  - Determinism and SLO gating for promotion.
- Out of scope:
  - Questions requiring facts not present in captured corpus.
  - External world knowledge without captured evidence.

## Skills by Section (and Why)
- Planning structure: `plan-harder`, `planner`
  Why: enforce phased, demoable increments with explicit dependencies and rollback.
- Correctness gauntlets: `golden-answer-harness`, `config-matrix-validator`
  Why: strict counters (`evaluated/skipped/failed`) and regression protection.
- Evidence guarantees: `evidence-trace-auditor`, `source-quality-linter`
  Why: enforce traceable citations and prevent low-quality unsupported outputs.
- Determinism and flake control: `deterministic-tests-marshal`, `state-recovery-simulator`
  Why: eliminate one-off passes and verify crash/restart consistency.
- Performance and resource safety: `perf-regression-gate`, `resource-budget-enforcer`, `observability-slo-broker`
  Why: maintain query + ingest latency and idle budget compliance.
- Security and boundary hardening: `policygate-penetration-suite`, `security-best-practices`
  Why: keep plugin inputs untrusted, fail closed, localhost-only contracts.
- Test implementation: `python-testing-patterns`, `testing`
  Why: deterministic unit/integration/e2e gates across pipeline and query.
- Operational command safety: `shell-lint-ps-wsl`
  Why: reproducible command execution and cross-shell correctness.

## Prerequisites
- Canonical runtime:
  - `autocapture` CLI active and used for ingest/processing/query.
- Services:
  - Query upstream stack healthy on localhost (8787/8788 as applicable).
  - Model service availability treated as optional for non-vlm paths.
- Data:
  - Stable normalized data root and metadata stores.
- Guardrails:
  - `schedule_extract=false` honored in popup/query path.
  - Raw fallback disabled for query path.

## Hard Exit Criteria (Definition of Done)
- Q40 strict gate: `evaluated=40`, `skipped=0`, `failed=0` for **3 consecutive runs**.
- Temporal40 strict gate: same counters for **3 consecutive runs**.
- Random corpus gauntlet:
  - At least 200 randomized prompts across time windows with deterministic outcomes.
  - `OK` responses all citation-backed; uncitable responses are deterministic non-OK.
- Plugin completion ledger:
  - 100% of processed frames have explicit per-plugin completion state.
- Performance/SLO:
  - Query p95 and pipeline lag meet configured thresholds for 3 consecutive soak windows.
- No raw-query fallback:
  - Query contract counters show zero raw media reads and zero extract scheduling.
- Audit integrity:
  - Append-only audit log contains privileged-action entries for all new sensitive paths and passes integrity verification.

## Sprint 1: Baseline Truth and Observability
**Goal**: Make failure reasons explicit and measurable before behavior changes.  
**Skills**: `observability-slo-broker`, `python-observability`, `config-matrix-validator`  
**Demo/Validation**:
- One command emits readiness summary with strict counters and top failure classes.
- Dashboard artifact includes plugin, query, and retrieval bottlenecks.

### Task 1.1: Build canonical readiness snapshot
- **Location**: `tools/run_non_vlm_readiness.py`, `tools/release_gate.py`
- **Description**: Emit a single readiness JSON with:
  - strict status for original Q40/temporal40
  - plugin enablement status
  - query contract metrics
  - SLO indicators (pending lag, throughput, risk).
- **Complexity**: 4
- **Dependencies**: none
- **Acceptance Criteria**:
  - One deterministic JSON artifact per run.
  - Failure keys normalized (no ad hoc strings).
- **Validation**:
  - Extend `tests/test_run_non_vlm_readiness_tool.py`.

### Task 1.2: Add plugin execution coverage counters
- **Location**: `autocapture_nx/kernel/*`, `tools/gate_plugin_enablement.py`
- **Description**: Record per-plugin attempted/succeeded/failed/skipped counts by stage.
- **Complexity**: 5
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Every stage run includes plugin coverage vector.
- **Validation**:
  - Add/extend `tests/test_gate_plugin_enablement.py`.

## Sprint 2: Stage1 Completeness Ledger and Reap Safety
**Goal**: Stage1 is provably complete and safe to mark for reap without losing query utility.  
**Skills**: `evidence-trace-auditor`, `resource-budget-enforcer`, `python-testing-patterns`  
**Demo/Validation**:
- Stage1 completion + retention marker only written after mandatory extraction set is present.

### Task 2.1: Define mandatory Stage1 extraction contract
- **Location**: `docs/contracts/stage1_minimum_contract.md` (new), `autocapture_nx/kernel/*`
- **Description**: Enumerate required artifacts per frame:
  - capture frame record
  - UIA linkage records/docs where applicable
  - HID summaries
  - normalized SST text bases
  - lineage pointers.
- **Complexity**: 4
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Contract machine-checkable by gate tool.
- **Validation**:
  - Add `tools/gate_stage1_contract.py` + tests.

### Task 2.2: Enforce retention marker gating
- **Location**: Stage1 handoff/idle processing path modules
- **Description**: Write `retention.eligible` only if Stage1 contract passes for source frame.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Zero false-positive retention markers.
- **Validation**:
  - Integration test with synthetic partial/complete records.

### Task 2.3: Add append-only privileged action audit trail
- **Location**: kernel lifecycle + ingest/handoff pathways, `tools/gate_audit_log_integrity.py` (new)
- **Description**: Write deterministic audit entries for privileged actions:
  - service boot failures/recoveries
  - retention marker writes
  - configuration profile changes
  - query contract guard trips.
- **Complexity**: 5
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - New privileged paths emit append-only audit records.
  - Integrity checker reports no gaps/tamper signals.
- **Validation**:
  - Add integrity tests and gate output assertions.

## Sprint 3: Stage2+ Plugin Full-Stack Completion
**Goal**: All non-vlm plugins run by default and contribute deterministic outputs.  
**Skills**: `config-matrix-validator`, `policygate-penetration-suite`, `testing`  
**Demo/Validation**:
- Plugin matrix report shows enabled/runnable/defaulted for all approved plugins.

### Task 3.1: Build canonical plugin allowlist and default profile
- **Location**: `config/default.json`, `config/profiles/*.json`, `docs/reports/*`
- **Description**: Consolidate one golden plugin stack for Stage2+ with explicit allowlist.
- **Complexity**: 5
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - No hidden disabled plugin in default stack (except explicitly blocked by policy).
- **Validation**:
  - `tools/gate_plugin_enablement.py` strict pass.

### Task 3.2: Add deterministic plugin completion records
- **Location**: processing pipeline modules + metadata record writer
- **Description**: Persist per-record plugin results and failure reasons.
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Every frame has plugin completion lineage available for query diagnostics.
- **Validation**:
  - New tests for completion record shape and stability.

## Sprint 4: Query Pipeline Canonicalization (Normalized-Only)
**Goal**: Single query path, no raw fallback, deterministic fast failures.  
**Skills**: `ccpm-debugging`, `evidence-trace-auditor`, `security-best-practices`  
**Demo/Validation**:
- Query with `schedule_extract=false` never triggers extraction/compute.
- Missing capabilities return explicit structured errors immediately.

### Task 4.1: Enforce one golden query path
- **Location**: `autocapture_nx/ux/facade.py`, `autocapture_nx/kernel/query.py`
- **Description**: Remove alternate behavioral branches that bypass canonical path.
- **Complexity**: 6
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - All interactive query requests traverse one orchestrator path.
- **Validation**:
  - Route-map tests + capability-failure tests.

### Task 4.2: Hard-block raw fallback and extraction-on-query
- **Location**: query execution modules and retrieval adapters
- **Description**: Fail closed on unavailable normalized evidence; do not schedule jobs.
- **Complexity**: 5
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Query contract counters remain zero for raw media and schedule_extract requests.
- **Validation**:
  - Extend query contract tests and popup regression checks.

## Sprint 5: Answer Contract + Citation Integrity
**Goal**: Every `OK` answer is fully citation-backed and exactness-validated.  
**Skills**: `evidence-trace-auditor`, `source-quality-linter`, `golden-answer-harness`  
**Demo/Validation**:
- Random and curated answers include structured citation chains.

### Task 5.1: Normalize citation payload schema
- **Location**: query answer serialization modules
- **Description**: Standardize citation fields:
  - record_id, record_type, time window, snippet, lineage chain.
- **Complexity**: 5
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - No `OK` answer without at least one valid citation chain.
- **Validation**:
  - Citation schema tests + strict popup regression.

### Task 5.2: Add claim-to-evidence verifier
- **Location**: `tools/gate_claim_evidence_alignment.py` (new)
- **Description**: Verify expected claims map to cited evidence content deterministically.
- **Complexity**: 7
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Failures report exact claim mismatch reason and citation IDs.
- **Validation**:
  - New deterministic harness tests.

### Task 5.3: Enforce raw-first and export-only sanitization boundaries
- **Location**: storage/export and query output modules
- **Description**: Verify raw/local data remains unmasked in local stores and any sanitization happens only on explicit export paths.
- **Complexity**: 5
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - Query/runtime never mutates local raw/normalized stores for sanitization.
  - Export-only sanitization policy is test-enforced.
- **Validation**:
  - Add/extend tests using export sanitization verifier patterns.

## Sprint 6: Gauntlets and Determinism Hardening
**Goal**: Make strict success repeatable, not incidental.  
**Skills**: `deterministic-tests-marshal`, `golden-answer-harness`, `state-recovery-simulator`  
**Demo/Validation**:
- 3 consecutive strict green runs for both Q40 suites.

### Task 6.1: Stabilize flaky advanced/generic cases
- **Location**: `autocapture_nx/kernel/query.py`, related retrieval modules
- **Description**: Resolve non-deterministic case behavior (example: calendar row instability).
- **Complexity**: 8
- **Dependencies**: Sprint 5
- **Acceptance Criteria**:
  - Known flaky cases remain green across repeated runs.
- **Validation**:
  - Repro loop tests + strict gate repeats.

### Task 6.2: Add consecutive-pass gate tool
- **Location**: `tools/gate_consecutive_strict_runs.py` (new)
- **Description**: Require N consecutive strict passes before promotion.
- **Complexity**: 4
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Gate fails on any intermittent strict failure.
- **Validation**:
  - Tool tests + CI entrypoint.

## Sprint 7: Randomized “Ask Anything” Corpus Audit
**Goal**: Validate behavior against arbitrary natural-language prompts, not just curated sets.  
**Skills**: `golden-answer-harness`, `evidence-trace-auditor`, `python-testing-patterns`  
**Demo/Validation**:
- Random prompt pack can be regenerated and replayed deterministically.

### Task 7.1: Build random prompt generator over corpus slices
- **Location**: `tools/build_query_stress_pack.py`, `tools/run_synthetic_gauntlet.py`
- **Description**: Generate prompts across:
  - time windows
  - app/activity classes
  - state transitions
  - counts/aggregates/comparisons.
- **Complexity**: 6
- **Dependencies**: Sprint 6
- **Acceptance Criteria**:
  - Prompt distributions cover at least 10 intent families.
- **Validation**:
  - Distribution tests + deterministic seed replay.

### Task 7.2: Add assertion policy for random run outcomes
- **Location**: `tools/gate_random_query_quality.py` (new)
- **Description**: Enforce:
  - `OK` => citations required and quality aligned
  - non-OK => deterministic structured reason.
- **Complexity**: 6
- **Dependencies**: Task 7.1
- **Acceptance Criteria**:
  - Zero fabricated or uncited `OK` responses.
- **Validation**:
  - Random pack gate tests and artifacts.

## Sprint 8: Throughput, Soak, and Operational Readiness
**Goal**: Sustain overnight processing and interactive query performance in realistic conditions.  
**Skills**: `perf-regression-gate`, `resource-budget-enforcer`, `observability-engineer`  
**Demo/Validation**:
- Overnight soak report with SLO pass/fail and root-cause details.

### Task 8.1: Throughput budget and lag risk gate
- **Location**: soak + release gate tools
- **Description**: Enforce SLO thresholds:
  - pending records
  - throughput records/s
  - projected lag hours
  - retention risk false.
- **Complexity**: 5
- **Dependencies**: Sprint 2, Sprint 3
- **Acceptance Criteria**:
  - Stage1 clears incoming volume within retention window.
- **Validation**:
  - Soak run artifacts and SLO gate pass.

### Task 8.2: Popup/query upstream acceptance
- **Location**: `tools/run_popup_regression_strict.sh`, query service adapters
- **Description**: Ensure popup path remains healthy with strict acceptance and citations.
- **Complexity**: 5
- **Dependencies**: Sprint 4, Sprint 5
- **Acceptance Criteria**:
  - strict popup regression pass (target 10/10 accepted).
- **Validation**:
  - regression artifact + miss report + root cause summary JSON.

## Testing Strategy
- Unit tests: parser, planner, retrieval bounds, contract validators, citation schema.
- Integration tests: stage1->stage2 lineage, plugin completion ledger, query path behavior.
- End-to-end tests:
  - `tools/q40.sh` strict repeats
  - temporal40 strict repeats
  - popup strict regression
  - random corpus pack gate
- Determinism policy:
  - no merge/promotion on single-pass green
  - require consecutive stable green runs.

## Potential Risks & Gotchas
- Flaky strict passes due to borderline extraction cases.
  - Mitigation: consecutive-pass gate + targeted stabilization tasks.
- Silent plugin disablement or profile drift.
  - Mitigation: plugin matrix gate at release boundary.
- Query lock contention under soak.
  - Mitigation: lock-aware retries, bounded queueing, isolated query SLOs.
- Citation drift despite answer text stability.
  - Mitigation: claim-to-evidence alignment gate.
- Storage pressure from delayed Stage1 completion.
  - Mitigation: retention-marker gating tied to mandatory Stage1 contract.
- Service dependency volatility (8000/8788 paths).
  - Mitigation: fail-fast structured errors + non-vlm readiness mode.
- Privileged-path behavior changes without audit visibility.
  - Mitigation: append-only audit logging + integrity gate as promotion prerequisite.
- Accidental sanitization of local canonical data instead of export-only views.
  - Mitigation: explicit raw-first policy tests and export-path-only sanitizer enforcement.

## Rollback Plan
- Keep current `main` release gate as immediate fallback target.
- Feature-flag new query/citation enforcement paths:
  - disable by config if regression is found.
- Preserve previous strict artifacts and restore last known-good profile.
- Roll back sprint-by-sprint by reverting isolated commits per task group.

## Implementation Order Summary
1. Baseline truth/metrics.
2. Stage1 completion + reap safety.
3. Full plugin-stack completion proof.
4. Canonical normalized-only query path.
5. Citation and claim alignment.
6. Strict determinism hardening.
7. Randomized corpus audit.
8. Soak/SLO operational promotion.
