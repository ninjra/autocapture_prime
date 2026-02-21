# Plan: Core Hardening Recommendations

**Generated**: 2026-02-18  
**Estimated Complexity**: High

## Overview
Implement six hardening/refactor recommendations across archive import safety, plugin reload semantics, validator subprocess controls, capture spool durability, research runner robustness, and retrieval fusion determinism.  
Approach: sequence by blast radius and risk containment, with each sprint producing a demoable and testable increment.

## Skills Selection (Implementation)
Available skills reviewed from `AGENTS.md` (project + global pools), including: `plan-harder`, `python-testing-patterns`, `testing`, `security-best-practices`, `security-threat-model`, `logging-observability`, `python-observability`, `deterministic-tests-marshal`, `perf-regression-gate`, `resource-budget-enforcer`, `policygate-penetration-suite`, `audit-log-integrity-checker`, `evidence-trace-auditor`, `golden-answer-harness`, `config-matrix-validator`, `state-recovery-simulator`, `shell-lint-ps-wsl`, and supporting skills.

Chosen skills for this plan:
- `plan-harder`: enforce phased, committable execution plan.
- `security-best-practices`: safe extraction and unsafe member rejection policy.
- `security-threat-model`: trust-boundary analysis for archive import and plugin reload paths.
- `python-testing-patterns`: deterministic unit/integration test additions per recommendation.
- `testing`: cross-sprint validation strategy and gate alignment.
- `logging-observability` + `python-observability`: structured error/timeout reporting and diagnostics coverage.
- `deterministic-tests-marshal`: flake checks for timeout/reload/idempotency tests.
- `perf-regression-gate`: overhead checks for fsync and safe extraction loops.
- `resource-budget-enforcer`: confirm validator timeouts and extraction changes don’t break budget expectations.
- `policygate-penetration-suite`: hostile archive payload probing (zip-slip cases).
- `audit-log-integrity-checker`: verify audit append-only integrity for failure events.
- `config-matrix-validator`: validate newly introduced config flags/defaults.
- `state-recovery-simulator`: crash/restart behavior around spool durability.
- `shell-lint-ps-wsl`: command hygiene during implementation and validation scripts.

## Prerequisites
- Working `.venv` and baseline tests runnable.
- Lock refresh scripts available (`tools/hypervisor/scripts/update_contract_lock.py`, plugin lock updater).
- Existing release gates operational.
- No changes to capture/ingestion ownership boundary (Windows sidecar remains external).

## Sprint 0: Baseline, Threat Boundaries, and Safety Flags
**Goal**: Establish measurable baseline and explicit trust assumptions before code changes.
**Skills**: `security-threat-model`, `config-matrix-validator`, `testing`, `shell-lint-ps-wsl`.  
**Demo/Validation**:
- Baseline artifact set generated (tests/gates currently passing set + known failures).
- Trust boundary note recorded for archive source assumptions.

### Task 0.1: Baseline Snapshot
- **Location**: `artifacts/` + runbook references
- **Description**: Capture current pass/fail baseline for impacted tests/gates before refactors.
- **Complexity**: 2/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - Baseline report exists and is linked from sprint notes.
- **Validation**:
  - Re-runnable command list for baseline reproduction.

### Task 0.2: Config Flag Staging
- **Location**: `config/default.json`, `contracts/config_schema.json`
- **Description**: Add/confirm all new safety/rollback flags before behavior changes.
- **Complexity**: 3/10
- **Dependencies**: Task 0.1
- **Acceptance Criteria**:
  - All new toggles are schema-validated and documented.
- **Validation**:
  - Config schema tests and config matrix gate.

### Task 0.3: Lock Refresh Order Guard
- **Location**: `tools/hypervisor/scripts/update_contract_lock.py`
- **Description**: Ensure contract lock refresh also refreshes plugin lock hashes to prevent drift.
- **Complexity**: 2/10
- **Dependencies**: Task 0.2
- **Acceptance Criteria**:
  - No contract/plugin lock hash mismatch after schema/contract updates.
- **Validation**:
  - Devtools/plugin lock tests and phase-0 gate.

## Sprint 1: Archive Import Safety (Zip-Slip Hardening)
**Goal**: Enforce fail-closed archive extraction with safe member validation.  
**Skills**: `security-best-practices`, `security-threat-model`, `python-testing-patterns`, `policygate-penetration-suite`.  
**Demo/Validation**:
- Run archive verification/import tests; malicious archives rejected.
- Confirm safe archives still import and match hashes.

### Task 1.1: Add Safe Member Predicate and Extractor
- **Location**: `autocapture/storage/archive.py`
- **Description**: Add `_is_safe_member(...)` and `_safe_extractall(...)` with traversal/absolute/drive-prefix rejection and canonical path containment checks.
- **Complexity**: 5/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - Unsafe entries (`../`, absolute, drive-prefixed) raise deterministic error.
  - Extraction uses member-by-member routine only.
- **Validation**:
  - Unit tests for safe/unsafe member classification and extraction behavior.

### Task 1.2: Refactor Importer.import_archive
- **Location**: `autocapture/storage/archive.py`
- **Description**: Replace `extractall(...)` with `_safe_extractall(...)`.
- **Complexity**: 3/10
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - No direct `extractall` call remains in this module.
  - Error surfaced as fail-closed.
- **Validation**:
  - Existing import tests + new malicious zip tests.

### Task 1.3: Align verify_archive With Safe Name Rules
- **Location**: `autocapture/storage/archive.py`
- **Description**: Ensure verification rejects unsafe names before hash validation.
- **Complexity**: 4/10
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - verify step and import step enforce same naming policy.
- **Validation**:
  - Verification-only tests for unsafe names.

## Sprint 2: Plugin Reload Semantics (Remove exec Reload Path)
**Goal**: Replace custom exec-based reload with `importlib`-based deterministic reload behavior.
**Skills**: `security-best-practices`, `python-testing-patterns`, `testing`, `logging-observability`.
**Demo/Validation**:
- Plugin refresh reload path works and rebinding is deterministic.
- Failure reports include actionable context.

### Task 2.1: Refactor _load_factory Reload Strategy
- **Location**: `autocapture/plugins/manager.py`
- **Description**: Replace compile+exec flow with `importlib.import_module` + `importlib.reload` under `force_reload=True`.
- **Complexity**: 6/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - No `exec(...)` in reload path.
  - Factory remains callable and refresh behavior preserved.
- **Validation**:
  - Unit tests for reload rebind behavior.

### Task 2.2: Improve Factory Load Error Context
- **Location**: `autocapture/plugins/manager.py`
- **Description**: Include plugin id, extension name, manifest path, and factory string in raised errors.
- **Complexity**: 4/10
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Broken factory path produces contextualized error.
- **Validation**:
  - New tests asserting error payload contents.

## Sprint 3: Codex Validator Process Controls (Timeouts + Environment)
**Goal**: Bound subprocess validator runtime and produce structured timeout failures.
**Skills**: `python-testing-patterns`, `testing`, `logging-observability`, `resource-budget-enforcer`.
**Demo/Validation**:
- Hung validator command terminates with deterministic timeout report.
- Normal validators continue to pass.

### Task 3.1: Add Timeout Support in _run_command
- **Location**: `autocapture/codex/validators.py`
- **Description**: Extend runner with `timeout_s`, timeout normalization, and bounded stdout/stderr handling.
- **Complexity**: 5/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - Timeout yields explicit non-ok report with timeout reason.
- **Validation**:
  - Synthetic sleep/hang test.

### Task 3.2: Wire Timeout Config Through Validators
- **Location**: `autocapture/codex/validators.py` and config schema/defaults if needed
- **Description**: Per-validator timeout override + conservative default.
- **Complexity**: 5/10
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - CLI validators and unit-test validator use bounded runtime.
- **Validation**:
  - Unit tests with per-validator timeout values.

### Task 3.3: Optional Env Allowlist Mode
- **Location**: `autocapture/codex/validators.py`, config schema/defaults
- **Description**: Add optional env pass-through policy to reduce leakage.
- **Complexity**: 6/10
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Default behavior remains compatible; strict mode available.
- **Validation**:
  - Tests for both default and allowlist modes.

## Sprint 4: Capture Spool Idempotency + Durability
**Goal**: Make segment append idempotent and durability-aware; surface spool failures in pipeline.
**Skills**: `python-testing-patterns`, `state-recovery-simulator`, `perf-regression-gate`, `audit-log-integrity-checker`.
**Demo/Validation**:
- Duplicate identical append succeeds.
- Duplicate with different payload fails hard.
- Capture pipeline handles append outcomes deterministically.

### Task 4.1: Refactor CaptureSpool.append Semantics
- **Location**: `autocapture/capture/spool.py`
- **Description**: Add collision handling (`same payload => success`, `different => hard error`) and optional fsync control.
- **Complexity**: 7/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - Idempotent behavior is explicit and tested.
  - Corrupt existing file path raises deterministic error.
- **Validation**:
  - Unit tests for duplicate id same/different payload.

### Task 4.2: Update CapturePipeline.capture_bytes Error Handling
- **Location**: `autocapture/capture/pipelines.py`
- **Description**: Consume append result/exception; fail closed on mismatch conditions.
- **Complexity**: 4/10
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Pipeline does not ignore spool write outcomes.
- **Validation**:
  - Pipeline tests around spool collisions and retries.

## Sprint 5: Research Runner Robustness + Diagnostics
**Goal**: Surface plugin load failures and harden threshold parsing.
**Skills**: `python-observability`, `logging-observability`, `python-testing-patterns`, `config-matrix-validator`.
**Demo/Validation**:
- Invalid `threshold_pct` never crashes; deterministic fallback applied.
- Plugin initialization failure visible in runner output (and optionally fail-closed).

### Task 5.1: Preserve Plugin Load Error Context
- **Location**: `autocapture/research/runner.py`
- **Description**: Persist `_last_plugin_error` from `_ensure_plugins` and expose in run outputs.
- **Complexity**: 5/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - Silent plugin failure removal; diagnostics present in output payload.
- **Validation**:
  - Unit test with mocked plugin registry exception.

### Task 5.2: Harden Threshold Parsing
- **Location**: `autocapture/research/runner.py`
- **Description**: Add robust conversion/clamping for `threshold` and `threshold_pct`.
- **Complexity**: 3/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - Invalid values fallback safely.
  - Output always includes resolved threshold.
- **Validation**:
  - Parametric tests for malformed/edge values.

### Task 5.3: Add Optional Fail-Closed Mode on Plugin Error
- **Location**: `autocapture/research/runner.py`, `config/default.json`, `contracts/config_schema.json`
- **Description**: Introduce `research.fail_closed_on_plugin_error` (default false) with explicit behavior.
- **Complexity**: 4/10
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Behavior selectable and deterministic across modes.
- **Validation**:
  - Tests covering both mode branches.

## Sprint 6: Retrieval Fusion Type Safety + Release Integration
**Goal**: Ensure RRF fusion is deterministic under mixed id types and integrate all changes into release gates/docs.
**Skills**: `python-testing-patterns`, `deterministic-tests-marshal`, `testing`, `plan-harder`.
**Demo/Validation**:
- Mixed `doc_id` types no longer crash.
- Full targeted gate set passes with updated docs/matrix entries.

### Task 6.1: Normalize doc_id in rrf_fusion
- **Location**: `autocapture/retrieval/fusion.py`
- **Description**: Normalize `doc_id` to string for dict key + deterministic tie-break sort.
- **Complexity**: 2/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - No mixed-type sort/type errors.
- **Validation**:
  - New test: mixed int/str ids deterministic output.

### Task 6.2: Add/Update Docs and Gate Hooks
- **Location**: `docs/`, `tools/`, `tests/` as needed
- **Description**: Update implementation matrix and release notes for these six recommendations; ensure tests are wired into existing gate phases.
- **Complexity**: 4/10
- **Dependencies**: Tasks from Sprints 1-6
- **Acceptance Criteria**:
  - Matrix reflects implemented/superseded state clearly.
  - No orphan behavior outside gates.
- **Validation**:
  - Gate run outputs and matrix consistency checks.

## Testing Strategy
- Unit tests per recommendation (new + regression).
- Determinism runs for timeout/idempotency/reload/fusion ordering.
- Security negative tests (zip-slip and unsafe archive entries).
- Integration checks across capture, retrieval, research, and plugin manager flows.
- Targeted release gate sweep:
  - `gate_phase0` through relevant phase gates impacted by touched modules.
  - If a full release gate stalls due unrelated long-running phase jobs, run phase-by-phase bounded checks and record first blocker.

## Potential Risks & Gotchas
- Archive policy false positives can reject legacy but harmless archives.
  - Mitigation: clear error reasons + optional trusted-mode override.
- Reload strategy changes can expose module-level side effects.
  - Mitigation: reload tests and staged rollout flag (`plugins.reload_strategy`).
- Timeout defaults may be too low for slower environments.
  - Mitigation: configurable timeout with safe baseline.
- fsync overhead could impact capture throughput.
  - Mitigation: config toggle + perf gate benchmark.
- Plugin lock drift if contract lock is refreshed out-of-order.
  - Mitigation: keep lock updater chaining (contract -> plugin lock refresh).

## Rollback Plan
- Keep each sprint committable and isolated.
- For each changed subsystem, preserve temporary compatibility flags:
  - `storage.archive.safe_extract` (default true)
  - `plugins.reload_strategy` (`importlib` default; legacy temporary fallback if required)
  - validator timeout/env strictness flags
  - `capture.spool.fsync`
  - `research.fail_closed_on_plugin_error`
- If regressions occur, revert offending sprint commit only and re-run impacted gate subset.

## Success Criteria
- All six recommendations implemented with tests.
- No silent failures in plugin/research/validator paths.
- Deterministic retrieval and spool behavior under edge cases.
- Release gates pass for impacted phases with no non-pass markers.
- Implementation matrix updated with per-recommendation status, test references, and rollback switch mapping.
