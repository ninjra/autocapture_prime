# Plan: Capture Deprecation + Non-8000 Default Plugin Stack + Golden Query Integration

**Generated**: 2026-02-21  
**Estimated Complexity**: High

## Overview
Implement a processing-only default posture where Hypervisor is the sole capture owner, then default-enable and verify the full plugin stack that does not require `127.0.0.1:8000`. Ensure those plugin outputs are persisted, indexed, and retrievable so they materially contribute to query result sets and strict golden evaluation.

4-pillar optimization goals:
- Performance: bounded concurrency and cheap-first processing, no accidental VLM work.
- Accuracy: deterministic IDs, deterministic plugin execution order, strict correctness gates.
- Security: capture codepaths hard-deprecated in this repo, fail-closed policy boundaries.
- Citeability: every queryable contribution must carry lineage + citations to normalized records.

## Scope
In scope:
- Deprecate in-repo capture execution surfaces (Hypervisor-owned capture only).
- Default-enable every plugin path that is non-`8000`-dependent and production-safe.
- Verify query path uses those derived outputs (no dead plugins, no orphan outputs).
- Run strict golden gauntlet in non-`8000` mode with full metrics.

Out of scope:
- Any dependency on VLM service at `:8000`.
- Re-implementing capture in this repo.

## Assumptions
- Hypervisor continues writing Stage1 inputs (media + metadata + UIA contract records) into shared DataRoot.
- `metadata.db` is reachable often enough for repeated batch validation windows.
- Strict golden answers are evaluated against normalized/derived records only in this phase.

## Skill-to-Sprint Map (and Why)
- Sprint 1 (`plan-harder`, `planner`, `config-matrix-validator`):
  - Why: convert requirements into an enforceable non-`8000` default contract and gate matrix.
- Sprint 2 (`policygate-penetration-suite`, `evidence-trace-auditor`):
  - Why: hard-block capture re-entry and keep deprecation evidence auditable.
- Sprint 3 (`resource-budget-enforcer`, `deterministic-tests-marshal`, `python-testing-patterns`):
  - Why: expand default-on plugins safely under idle budgets while proving deterministic reruns.
- Sprint 4 (`golden-answer-harness`, `evidence-trace-auditor`):
  - Why: verify added plugin outputs are actually retrievable and cited in query answers.
- Sprint 5 (`golden-answer-harness`, `perf-regression-gate`):
  - Why: enforce strict golden correctness targets and prevent latency/perf regressions.
- Sprint 6 (`state-recovery-simulator`, `perf-regression-gate`):
  - Why: prove long-run stability and restart safety under the expanded stack.
- Cross-cutting (`shell-lint-ps-wsl`):
  - Why: normalize shell commands and avoid PS/WSL syntax drift during execution.

## Safety Boundary Contract (Fail-Closed vs Fail-Open)
- Must remain fail-closed:
  - Capture ownership boundary (this repo cannot perform capture in processing-only mode).
  - PolicyGate/security boundaries for plugin capability access.
  - Golden strict gate result acceptance (`40/40`, `0 skipped`, `0 failed`).
- Must be fail-open:
  - Non-critical data enrichment plugin parse/load errors in Stage1/Stage2 processing.
  - Missing optional sidecar artifacts that should not crash pipeline runtime.
- Required validation:
  - Security regression tests confirm fail-closed boundaries still block capture re-entry.
  - Processing regression tests confirm fail-open behavior logs warnings and continues.

## Sprint 1: Freeze Non-8000 Plugin Contract
**Goal**: Produce an authoritative plugin classification and enforceable default profile contract.  
**Demo/Validation**:
- Contract doc and machine-readable matrix committed.
- Every builtin plugin classified as one of: `capture_deprecated`, `default_non8000`, `optional_requires_8000`.

### Task 1.1: Build Plugin Capability Matrix
- **Location**: `docs/contracts/plugin-stack-non8000-contract.md`, `artifacts/config/plugin_matrix_non8000.json`
- **Description**: Enumerate all builtin plugins, required capabilities/endpoints, and default target state.
- **Complexity**: 5/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - No plugin remains unclassified.
  - Matrix explicitly marks capture plugins as deprecated.
- **Validation**:
  - Add deterministic matrix generation test in `tests/test_plugin_matrix_non8000.py`.

### Task 1.2: Add Contract Gate
- **Location**: `tools/gate_config_matrix.py`, `tools/gate_phase*.py`, `tests/test_gate_config_matrix.py`
- **Description**: Extend matrix gate to assert non-`8000` defaults and capture deprecation invariants.
- **Complexity**: 4/10
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Gate fails if capture plugins are enabled by default.
  - Gate fails if a `requires_8000` plugin is default-on in non-`8000` profile.
- **Validation**:
  - Unit tests for pass/fail fixtures.

### Task 1.3: Update Implementation Matrices
- **Location**: `docs/reports/implementation_matrix.md`, `docs/reports/autocapture_prime_4pillars_optimization_matrix.md`
- **Description**: Map each contract item to code path + test + gate.
- **Complexity**: 3/10
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - No unmapped contract rows.
- **Validation**:
  - Matrix lint/check script in existing docs gate flow.

## Sprint 2: Hard-Deprecate Capture Surfaces in Repo Runtime
**Goal**: Ensure this repo cannot become capture owner again.  
**Demo/Validation**:
- Capture plugins remain disabled and explicitly marked deprecated in doctor/UI/config surfaces.
- No query/processing path can implicitly trigger capture.

### Task 2.1: Deprecation Guardrails in Runtime + Doctor
- **Location**: `autocapture_nx/kernel/doctor.py`, `autocapture_nx/kernel/loader.py`, `tests/test_capture_deprecation_enforced.py`
- **Description**: Add hard checks that flag capture plugin activation as invalid in processing-only mode.
- **Complexity**: 6/10
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Doctor reports fail/degraded if capture plugins are toggled on.
- **Validation**:
  - Doctor fixture tests for enabled/disabled capture plugin states.

### Task 2.2: Remove Capture from Operator Surfaces
- **Location**: `autocapture/ux/plugin_options.py`, `autocapture/web/ui/*`, `tests/test_tray_menu_policy.py`
- **Description**: Remove/de-emphasize capture toggles and surfaces; keep processing-only controls.
- **Complexity**: 5/10
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - UI/UX no longer presents capture as an active repo-owned function.
- **Validation**:
  - UI and policy tests asserting no capture action exposure.

### Task 2.3: Policy Pen Tests for Capture Re-entry
- **Location**: `tests/test_capture_policygate_block.py`, `tools/security/capture_reentry_probe.py`
- **Description**: Add negative tests for alternate codepaths attempting capture invocation.
- **Complexity**: 5/10
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - All re-entry probes blocked with audit reason.
- **Validation**:
  - Pen suite report with zero bypasses.

## Sprint 3: Default-Enable Full Non-8000 Plugin Stack
**Goal**: Turn on all non-`8000` plugins by default and keep runtime stable.  
**Demo/Validation**:
- Default config boots with the non-`8000` stack.
- No plugin crashes from missing `:8000`.

### Task 3.1: Apply Default Config Deltas
- **Location**: `config/default.json`, `contracts/config_schema.json`, `tests/test_default_plugin_profile_no8000.py`
- **Description**: Flip default `plugins.enabled` values for all `default_non8000` plugins to true; enforce `requires_8000` plugins false.
- **Complexity**: 7/10
- **Dependencies**: Sprint 1, Sprint 2
- **Acceptance Criteria**:
  - Profile is deterministic and schema-valid.
  - Capture plugins remain false.
- **Validation**:
  - Config schema tests + profile snapshot tests.

### Task 3.2: Fail-Open Hardening (UIA Context Path)
- **Location**: `plugins/builtin/processing_sst_uia_context/plugin.py`, `tests/test_sst_uia_context_plugin.py`
- **Description**: Harden UIA metadata/fallback parse paths to warn-and-continue on malformed snapshots.
- **Complexity**: 4/10
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Malformed UIA payload does not crash pipeline stage.
- **Validation**:
  - Targeted UIA fail-open tests pass.

### Task 3.3: Fail-Open Hardening (SST Pipeline Stage Hooks)
- **Location**: `autocapture_nx/processing/sst/pipeline.py`, `tests/test_sst_stage_hooks.py`, `tests/test_sst_pipeline.py`
- **Description**: Ensure stage-hook provider faults are isolated and do not abort full batch execution.
- **Complexity**: 5/10
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Individual hook failures produce warnings + diagnostics, not process termination.
- **Validation**:
  - Hook-failure integration tests pass with continued pipeline progression.

### Task 3.4: Budget and Determinism Verification
- **Location**: `tests/test_resource_budget_enforcement.py`, `tests/test_q40_determinism.py`, `tools/gate_q40_determinism.py`
- **Description**: Run repeated profile boots and workload slices to verify idle budget + deterministic outputs.
- **Complexity**: 5/10
- **Dependencies**: Task 3.3
- **Acceptance Criteria**:
  - Stable outputs across reruns.
  - Budget gates remain green.
- **Validation**:
  - Determinism marshal repeat runs and budget gate outputs.

## Sprint 4: Query Contribution Wiring Proof
**Goal**: Prove enabled non-`8000` plugins actually contribute to query resultsets.  
**Demo/Validation**:
- Query provider attribution shows contributions from expanded plugin set.
- Citation chains resolve to normalized/derived records.

### Task 4.1: Provider Attribution Gate
- **Location**: `tools/generate_qh_plugin_validation_report.py`, `tests/test_generate_qh_plugin_validation_report.py`
- **Description**: Require non-zero contribution from required plugin families and expose missing contributors.
- **Complexity**: 5/10
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Report clearly identifies providers that are loaded but non-contributing.
- **Validation**:
  - Gate tests with synthetic pass/fail manifests.

### Task 4.2: Retrieval Coverage Expansion Audit
- **Location**: `plugins/builtin/retrieval_basic/plugin.py`, `autocapture_nx/kernel/query.py`, `tests/test_query_retrieval_coverage_non8000.py`
- **Description**: Ensure retrieval includes all relevant derived record families from non-`8000` plugin outputs.
- **Complexity**: 6/10
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Query hits include newly enabled plugin artifacts where relevant.
- **Validation**:
  - Integration tests over synthetic record packs.

### Task 4.3: Citation Integrity for New Contributors
- **Location**: `autocapture/pillars/citable.py`, `tests/test_citation_chain_non8000_plugins.py`
- **Description**: Validate lineage and citation fields for each required contributor family.
- **Complexity**: 5/10
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - No uncited claim from non-`8000` contributor outputs.
- **Validation**:
  - Evidence trace tests pass for contribution scenarios.

## Sprint 5: Strict Golden (Non-8000) + Full Gates After Each Sprint
**Goal**: Reach strict golden behavior without `:8000` and keep regression barriers enforced continuously.  
**Demo/Validation**:
- Strict golden reports persisted per run.
- Full test/gate suite executed after each sprint milestone.

### Task 5.1: Golden Harness Profile for Non-8000 Mode
- **Location**: `tools/query_eval_suite.py`, `tools/q40.sh`, `docs/reports/golden_pipeline_non8000_latest.json`
- **Description**: Add explicit non-`8000` profile path and strict output schema checks (`evaluated`, `skipped`, `failed`).
- **Complexity**: 6/10
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - Report generation is deterministic and reproducible.
- **Validation**:
  - Repeated harness runs produce stable metrics.

### Task 5.2: Strict Golden Result Gate
- **Location**: `tools/gate_q40_strict.py`, `tests/test_gate_q40_strict.py`, `tools/release_gate.py`
- **Description**: Add explicit gate that parses harness report and fails unless:
  - `evaluated == 40`
  - `skipped == 0`
  - `failed == 0`
- **Complexity**: 5/10
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Release gate fails on any strict metric drift.
- **Validation**:
  - Deterministic fixture tests for pass/fail strict reports.

### Task 5.3: Full Gate Chain Per Sprint
- **Location**: `tools/run_all_tests.py`, `tools/release_gate.py`, `docs/runbooks/release_gate_ops.md`
- **Description**: Define and enforce per-sprint gate chain (unit/integration/golden/config/perf/security).
- **Complexity**: 4/10
- **Dependencies**: Task 5.2
- **Acceptance Criteria**:
  - No sprint marked complete unless full gate chain passes.
- **Validation**:
  - Gate log artifacts saved with timestamp and commit hash.

### Task 5.4: Strict Completion Target
- **Location**: `docs/reports/golden_pipeline_core_remediation_2026-02-*.md`, `docs/reports/q40_questions_expected_vs_pipeline_*.md`
- **Description**: Drive closure of remaining mismatches to strict target:
  - `evaluated=40`
  - `skipped=0`
  - `failed=0`
- **Complexity**: 8/10
- **Dependencies**: Task 5.3
- **Acceptance Criteria**:
  - Latest strict report shows exact target values.
- **Validation**:
  - Independent rerun confirms same strict metrics.
  - `tools/gate_q40_strict.py` passes using that rerun artifact.

## Sprint 6: Soak + Operational Confidence
**Goal**: Ensure overnight stability with full non-`8000` stack active.  
**Demo/Validation**:
- Soak artifacts show stable throughput and no crash loops.
- Query latency and correctness remain within expected budgets.

### Task 6.1: Overnight Soak (No-8000 Profile)
- **Location**: `tools/wsl/start_soak.sh`, `tools/wsl/soak_verify.sh`, `docs/reports/non8000_soak_latest.json`
- **Description**: Run long soak with live ingestion and active plugin stack, capture failure modes and lag.
- **Complexity**: 5/10
- **Dependencies**: Sprint 5
- **Acceptance Criteria**:
  - No fatal pipeline crashes.
  - Backlog trend remains bounded.
- **Validation**:
  - Soak verify artifacts and health snapshots.

### Task 6.2: Regression Lock-In
- **Location**: `tools/gate_phase*.py`, `docs/plans/README.md`
- **Description**: Add explicit checks so future changes cannot silently re-enable capture or disable non-`8000` contributors.
- **Complexity**: 4/10
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Regression gates fail on contract drift.
- **Validation**:
  - Negative fixtures demonstrate gate blocking behavior.

## Testing Strategy
- Unit: plugin classification, config profile, fallback semantics, citation integrity.
- Integration: Stage1->derived->query contribution with synthetic and live-compatible fixtures.
- Golden: strict `40q` harness in non-`8000` mode, repeated for determinism.
- Soak: overnight profile with resource and throughput telemetry.

## Potential Risks & Gotchas
- Hidden implicit `:8000` dependency in a plugin marked non-`8000`.
  - Mitigation: contract matrix + plugin bootstrap probes + fail-open tests.
- Security fail-closed boundaries could weaken while adding fail-open processing behavior.
  - Mitigation: explicit boundary contract + regression tests for capture re-entry blocking.
- Enabling additional defaults increases CPU/RAM during idle windows.
  - Mitigation: governor/scheduler budgets + resource-budget tests + staged rollout.
- Retrieval still ignoring newly derived record types.
  - Mitigation: provider attribution gate + retrieval coverage integration tests.
- Metadata writer contention can mask progress during validation windows.
  - Mitigation: repeatable synthetic packs + stable-window rerun policy for live DB checks.

## Rollback Plan
- Revert to previous plugin-enabled snapshot in `config/default.json`.
- Keep capture deprecation guardrails intact.
- Disable newly enabled plugin subset behind profile switch if a specific plugin is unstable.
- Re-run config/golden gates to confirm rollback safety before redeploy.
