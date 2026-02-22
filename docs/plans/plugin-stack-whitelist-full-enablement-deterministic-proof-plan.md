# Plan: Plugin Stack Whitelist Full Enablement Deterministic Proof

**Generated**: 2026-02-22  
**Estimated Complexity**: High

## Overview
Recover the plugin platform to a strict, deterministic state where every plugin in the canonical active inventory is:
- allowlisted
- lockfile/hash valid
- enabled
- loadable without errors
- functionally validated by tests and runtime probes

And where query results can be produced from normalized corpus data without fabrications, with explicit failure telemetry when dependencies are down.

Service dependency terms used in this plan:
- `service_7411`: local query/popup service dependency path
- `service_8000`: local VLM/OpenAI-compatible inference dependency path
- `service_down`: either dependency unhealthy/unreachable
- `service_up`: both dependencies healthy

Current known blockers from repo/runtime audit:
- `builtin.retrieval.basic` load failure (`artifact hash mismatch`)
- state-layer JEPA/retrieval plugins present but disabled/not allowlisted
- `metadata.db` direct read intermittently throws `OperationalError: disk I/O error`
- strict real-corpus snapshot failing with latency/citation failure cascade

## Prerequisites
- Access to `autocapture_prime` repo and `/mnt/d/autocapture` runtime dirs.
- Stable branch strategy (`main` protected; work on short-lived feature branch).
- Ability to run:
  - `.venv/bin/python -m autocapture_nx plugins list`
  - `.venv/bin/python -m autocapture_nx plugins load-report`
  - `.venv/bin/python -m pytest`
- Health probes for dependency tiering:
  - `service_7411` health probe
  - `service_8000` health probe
- Agreement on canonical active inventory rule:
  - Any plugin in canonical inventory failing `allowlisted/hash_ok/enabled/loadable/functional` is a hard failure.

## Skills By Section
- Sprint 0: `plan-harder`, `config-matrix-validator`
  - Why: define exact plugin inventory + enforcement matrix.
- Sprint 1: `audit-log-integrity-checker`, `evidence-trace-auditor`
  - Why: make plugin policy/approval/lock transitions auditable and citable.
- Sprint 2: `testing`, `deterministic-tests-marshal`
  - Why: deterministic load/enable/hash/allowlist tests with no flaky passes.
- Sprint 3: `golden-answer-harness`, `evidence-trace-auditor`
  - Why: prove query output quality is retrieval-backed and citation-valid.
- Sprint 4: `resource-budget-enforcer`, `python-observability`
  - Why: enforce runtime stability and expose stage/plugin/IO failure metrics.

## Sprint 0: Canonical Inventory + Enforcement Contract
**Goal**: Establish one authoritative plugin target set and hard pass/fail matrix before changing behavior.  
**Demo/Validation**:
- `artifacts/plugin_enablement/contract/plugin_inventory_contract.json` exists.
- Contract includes all active plugin IDs and per-plugin gates.
- Contract hash and source references are recorded.

### Task 0.1: Build canonical plugin inventory
- **Location**: `tools/plugin_inventory_contract.py`, `docs/contracts/plugin_inventory_contract.json` (new)
- **Description**: Compute canonical active inventory from:
  - `config/default.json` default pack + enabled map + allowlist
  - required plugin gates referenced in docs/contracts
  - explicit deprecation manifest for capture plugins
- **Complexity**: 6
- **Dependencies**: None
- **Acceptance Criteria**:
  - Inventory is deterministic and reproducible.
  - Every plugin labeled as one of: `active_required`, `active_optional_service_backed`, `deprecated_removed`.
- **Validation**:
  - Unit test with fixture configs and expected inventory output.

### Task 0.2: Define hard gate matrix
- **Location**: `docs/contracts/plugin_enablement_gate_v1.json` (new)
- **Description**: Define per-plugin required checks:
  - `allowlisted == true`
  - `hash_ok == true`
  - `enabled == true`
  - `load_failures == 0`
  - `capability_present == true` (if capability declared)
- **Complexity**: 4
- **Dependencies**: Task 0.1
- **Acceptance Criteria**:
  - Any failing check produces explicit machine-readable failure reason.
- **Validation**:
  - Schema + contract validation tests.

## Sprint 1: Policy/Lock/Allowlist Remediation
**Goal**: Make plugin policy state internally consistent and fail-closed with deterministic diffs.  
**Demo/Validation**:
- `plugins load-report` returns zero failed plugins for canonical inventory.
- Lock/allowlist deltas are archived with before/after evidence.

### Task 1.1: Fix plugin lock/hash drift
- **Location**: `config/plugin_locks.json`, `tools/hypervisor/scripts/update_plugin_locks.py`, `tests/test_plugin_locks_signature_verified.py`
- **Description**: Recompute lock entries and signatures, then verify no hash mismatches remain (including `builtin.retrieval.basic`).
- **Complexity**: 7
- **Dependencies**: Sprint 0
- **Acceptance Criteria**:
  - `artifact hash mismatch` errors are eliminated.
  - Signed lock verification passes.
- **Validation**:
  - Lock signature tests + load-report smoke.

### Task 1.2: Align allowlist/enabled/default pack
- **Location**: `config/default.json`, `contracts/config_schema.json`, `tests/test_plugin_loader.py`, `tests/test_inproc_allowlist_enforced.py`
- **Description**: Ensure every canonical plugin is both allowlisted and enabled in default runtime profile; remove stale references to non-existent plugins (or implement them).
- **Complexity**: 8
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - No canonical plugin has `allowlisted=false` or `enabled=false`.
  - No unknown plugin IDs in allowlist/enabled/default pack.
- **Validation**:
  - New config matrix gate test.

### Task 1.3: Resolve missing/phantom plugin IDs (e.g., Kona references)
- **Location**: `config/default.json`, `plugins/**/plugin.json`, `docs/contracts/plugin_inventory_contract.json`
- **Description**: For each referenced plugin ID that does not exist:
  - either implement manifest/runtime plugin
  - or remove from canonical inventory with explicit deprecation record
- **Complexity**: 6
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Canonical inventory has no unresolved plugin IDs.
- **Validation**:
  - Tooling check fails if any referenced ID is absent.

## Sprint 2: Functional Enablement of State/Retrieval/JEPA Stack
**Goal**: Bring state/retrieval/JEPA path to loaded+functional, not just configured.  
**Demo/Validation**:
- `plugins load-report` includes state/retrieval/JEPA plugins as loaded.
- Functional tests pass for retrieval/state query path.

### Task 2.1: Enable state-layer plugin chain end-to-end
- **Location**: `config/default.json`, `autocapture_nx/state_layer/*`, `plugins/builtin/state_*/plugin.py`, `tests/test_state_layer_*.py`
- **Description**: Enable and validate:
  - `builtin.state.jepa_like`
  - `builtin.state.retrieval`
  - vector backends used by state retrieval
  - optional JEPA training path with deterministic guardrails
- **Complexity**: 9
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - State query path returns retrieval hits when corpus contains relevant derived records.
  - No fallback to empty-capability path for missing `retrieval.strategy`.
- **Validation**:
  - Integration tests over fixture corpus + live snapshot replay.

### Task 2.2: Retrieval capability contract validation
- **Location**: `tools/gate_plugin_enablement.py` (new), `tests/test_gate_plugin_enablement.py`
- **Description**: Add gate that cross-checks `plugins list` + `plugins load-report` + capability map.
- **Complexity**: 7
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Gate fails on any missing capability for canonical plugin.
- **Validation**:
  - Deterministic fixture-based tests.

## Sprint 3: Query Correctness Proof (Service-Down and Service-Up Modes)
**Goal**: Prove query behavior is reliable and citable with explicit mode-aware expectations.  
**Demo/Validation**:
- Strict matrix and non-strict matrix both emit deterministic per-case reasons.
- No silent degraded pass-through.

### Task 3.1: Split strict contracts by dependency tier
- **Location**: `docs/contracts/real_corpus_expected_answers_v1.json`, `tools/run_real_corpus_readiness.py`, `tools/run_advanced10_queries.py`
- **Description**: Enforce two explicit sets:
  - `non_service_strict`: must pass with services down
  - `service_backed_strict`: must pass when 7411/8000 healthy
- **Complexity**: 8
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Failures are attributed to exact dependency tier (not generic no-evidence).
  - `service_down` runs emit explicit dependency failure labels and still emit full stage/plugin/IO metrics.
  - `service_up` runs evaluate answer correctness only after dependency-health checks pass.
- **Validation**:
  - Contract evaluation tests + reproducibility checks.

### Task 3.2: Eliminate timeout-as-answer behavior
- **Location**: `tools/run_advanced10_queries.py`, `autocapture_nx/kernel/query.py`, `tests/test_run_advanced10_expected_eval.py`
- **Description**: Ensure harness does not convert infrastructure timeout into misleading “query answer” row without explicit infrastructure-failure classification.
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Timeout rows are labeled infra-failure and excluded from correctness pass metrics.
- **Validation**:
  - Unit tests for timeout/degraded classification.

## Sprint 4: Runtime Failure Telemetry and Deterministic Evidence
**Goal**: Always know exactly where failures happen (plugin/stage/io/service), with machine-readable artifacts.  
**Demo/Validation**:
- Failure telemetry artifacts generated every run.
- Dashboard summary includes plugin + IO + query stage causes.

### Task 4.1: Add per-stage/per-plugin failure metrics pipeline
- **Location**: `tools/runtime_failure_snapshot.py` (new), `autocapture_nx/kernel/query.py`, `autocapture_nx/kernel/loader.py`
- **Description**: Persist counters and snapshots:
  - plugin load fail count by plugin ID
  - capability missing count by capability
  - query stage latency and fail reason
  - DB read/write error counters by path (`metadata.db`, `metadata.live.db`)
- **Complexity**: 8
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Each failed query has attributable root-cause dimensions.
  - Metrics coverage is complete in both `service_up` and `service_down` runs.
  - Metrics distinguish dependency failures from plugin failures from IO failures.
- **Validation**:
  - Integration test injecting plugin/hash/db failures.

### Task 4.2: Deterministic proof bundle for “all plugins working”
- **Location**: `artifacts/plugin_enablement/proof/<stamp>/`, `tools/gate_plugin_enablement.py`
- **Description**: Generate signed evidence bundle containing:
  - canonical inventory
  - plugin list/load-report snapshots
  - gate results
  - strict matrix summaries
  - DB I/O health snapshot
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - One command produces a deterministic pass/fail packet.
- **Validation**:
  - Replay check validates bundle integrity.

## Sprint 5: Golden Closure Gate (Hard Fail if Any Plugin Misses Qualification)
**Goal**: Enforce user’s pass condition exactly: any non-qualified plugin = failure.  
**Demo/Validation**:
- CI/local gate returns non-zero on first violation.
- Output is actionable with exact plugin IDs and missing qualifications.

### Task 5.1: Implement “all plugins qualified” hard gate
- **Location**: `tools/gate_all_plugins_qualified.py` (new), `tests/test_gate_all_plugins_qualified.py`
- **Description**: Hard gate over canonical inventory requiring:
  - `allowlisted`, `hash_ok`, `enabled`, `loaded`, `functional` all true
- **Functional Proof Definition**:
  - `functional` is true only when plugin-specific deterministic probe passes.
  - Probe catalog is explicit and versioned (one probe spec per plugin ID in canonical inventory).
  - Missing probe spec is an automatic gate failure.
- **Complexity**: 7
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - No ambiguous pass states.
  - Every canonical plugin has deterministic functional evidence attached to gate output.
- **Validation**:
  - Fixture matrix with one-failure-at-a-time cases.

### Task 5.2: Final deterministic acceptance report
- **Location**: `docs/reports/plugin_enablement_final.md` (new), `artifacts/plugin_enablement/final.json`
- **Description**: Emit final report with strict Y/N lines per plugin and per qualification.
- **Complexity**: 4
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Report is machine-readable + human-auditable.
- **Validation**:
  - Snapshot tests on report format and content.

## Testing Strategy
- Unit:
  - inventory derivation
  - gate logic
  - timeout/infra classification
- Integration:
  - plugin load-report + capabilities + query path with fixture corpus
  - service-down mode and service-up mode separately
- Determinism:
  - repeated runs must produce same pass/fail for same inputs
  - nondeterminism marshal run for flaky detection
- Golden:
  - strict matrix gates for non-service and service-backed tiers

## Deterministic Proof Requirements (Definition of Done)
- `plugins load-report` has zero failures for canonical inventory.
- `gate_all_plugins_qualified` passes with no exceptions.
- Strict non-service matrix passes 100% in service-down mode.
- Strict service-backed matrix passes 100% when services healthy.
- Failure telemetry artifact always present and root-cause complete.
- Any plugin outside `deprecated_removed` category that fails qualification blocks release.

## Potential Risks & Gotchas
- `metadata.db` I/O instability can masquerade as plugin/query failures.
  - Mitigation: dual-path DB health checks and fail classification.
- Hash lock updates can drift from signed lock expectations.
  - Mitigation: signed lock verification in same gate.
- Enabling JEPA/state retrieval may expose latent schema mismatches.
  - Mitigation: staged enablement and contract-first tests.
- Phantom plugin references (e.g., non-existent Kona IDs) can silently pass if not inventoried.
  - Mitigation: inventory contract forbids unresolved plugin IDs.

## Rollback Plan
- Revert config changes:
  - `config/default.json`
  - `config/plugin_locks.json`
  - any profile updates
- Restore prior lock snapshot from `config/plugin_locks.history/*`.
- Disable newly enabled plugins via one revert commit.
- Keep telemetry scripts; they are read-only diagnostic and safe to retain.
