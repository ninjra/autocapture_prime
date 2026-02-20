# Plan: Autocapture Prime Merge Work Order Lockstep Implementation

**Generated**: 2026-02-20  
**Estimated Complexity**: High

## Overview
This plan converts `docs/AUTOCAPTURE_PRIME_MERGE_WORK_ORDER.md` into an execution sequence for `autocapture_prime`, synchronized with the sister Hypervisor execution document. The target is a single canonical NX pipeline, ultralight Stage 1 handoff ingest, offline-only Stage 2+, strict read-only instant query, and strict golden correctness (`40/40 evaluated`, `0 skipped`, `0 failed`).

## Prerequisites
- Hypervisor sister doc execution owner and checkpoint cadence are defined.
- Test fixtures available for handoff dirs (`metadata.db` + `media/`) and UIA sidecar contract.
- Local runbook paths exist for golden, soak, and gate scripts.
- Baseline capture of live metrics exists before rollout (frames, UIA linkage, stage1 markers, retention markers).
- Contract version handshake is pre-agreed (`contract_version`, `schema_hash`).

## Scope Clarifications
- In scope: planning and sequencing for repo-side implementation, validation, and rollout.
- In scope: lockstep interfaces with Hypervisor (handoff ingest + reap marker contract + activity signals).
- Out of scope: implementing Hypervisor repo changes directly.

## Security And Runtime Semantics (Explicit)
- Fail-open: optional-field parse drift and non-critical enrichment failures (pipeline continues with warnings).
- Fail-closed: PolicyGate, sandbox boundary checks, localhost-only binding, and foreground gating controls.
- Query path is enforced read-only at both behavior and storage layers.

## Skills By Section
- **Section A: Contract & Surface Unification**
  - `plan-harder`: decomposes merge work into atomic, committable tasks.
  - `config-matrix-validator`: verifies CLI/config compatibility across legacy + NX + Hypervisor.
- **Section B: Stage 1 Handoff Ingest**
  - `deterministic-tests-marshal`: enforces idempotent/restartable ingest behavior.
  - `perf-regression-gate`: protects throughput under nightly batch windows.
  - `resource-budget-enforcer`: validates active/idle CPU-RAM limits.
- **Section C: Stage 2+/Query Invariants**
  - `evidence-trace-auditor`: ensures answer citeability and evidence-chain completeness.
  - `policygate-penetration-suite`: validates fail-open behavior on corrupt/untrusted input.
- **Section D: UIA/DirectShell Contract Hardening**
  - `config-matrix-validator`: confirms metadata-first/fallback/hash settings are enforced.
  - `python-testing-patterns`: covers deterministic IDs/bbox/linkage tests.
- **Section E: Golden + Soak + Release Gates**
  - `golden-answer-harness`: runs strict Q40 gauntlet semantics.
  - `deterministic-tests-marshal`: verifies non-flaky pass criteria before release.

## Sprint 1: Canonical Surface + Contract Freeze
**Goal**: Establish one canonical runtime surface and freeze lockstep contract with Hypervisor.
**Skills**: `plan-harder`, `config-matrix-validator`
**Demo/Validation**:
- `autocapture-prime` behaves as compatibility shim to `autocapture`.
- Contract document tables resolve all field-level ambiguities.
- Config matrix validated for legacy wrapper, NX CLI, and Hypervisor caller.

### Task 1.1: Canonical CLI Mapping
- **Location**: `autocapture_prime/cli.py`, `autocapture_nx/cli.py`, `pyproject.toml`, `README.md`
- **Description**: Define exact forwarding/deprecation behavior and normalize command parity.
- **Complexity**: 5/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - `autocapture-prime` invokes NX command path without behavior drift.
  - Docs designate NX as canonical.
- **Validation**:
  - CLI parity tests for key subcommands and flags.

### Task 1.2: Lockstep Contract Matrix (Repo ↔ Hypervisor)
- **Location**: `docs/handoff-stage1-contract.md` (new), `docs/autocapture_prime_UNDER_HYPERVISOR.md`, `docs/windows-hypervisor-popup-query-contract.md`
- **Description**: Publish normalized schemas for handoff dir, `reap_eligible.json`, activity signal, UIA linkage, and required configs.
- **Complexity**: 6/10
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Every contract field has owner, source, sink, and validation rule.
  - Versioned compatibility matrix exists (`repo_version ↔ hypervisor_version ↔ contract_version ↔ schema_hash`).
  - Unknown/optional fields have fail-open semantics specified.
- **Validation**:
  - Contract lint checklist and config matrix pass.
  - CI check fails if repo contract schema hash diverges from Hypervisor sister-doc schema hash.

### Task 1.3: Release Gate Definitions
- **Location**: `docs/plans/README.md`, `docs/release-gates.md` (new)
- **Description**: Define hard gates for Stage1 ingest correctness, Stage2 query invariants, and strict Q40 semantics.
- **Complexity**: 4/10
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Explicit pass/fail rules exist for all four pillars.
  - Non-negotiables are represented as hard gates:
    - localhost-only bind, fail-closed
    - no local deletion endpoints/actions
    - raw-first local storage; sanitization only on explicit export
    - citation-required answers by default
    - append-only audit logging for privileged behavior
- **Validation**:
  - Dry-run checklist over current baseline.

## Sprint 2: Stage 1 Ultralight Handoff Ingest
**Goal**: Implement deterministic, idempotent, restartable ingest and retention-ready marking without heavy compute.
**Skills**: `deterministic-tests-marshal`, `perf-regression-gate`, `resource-budget-enforcer`
**Demo/Validation**:
- Ingest one handoff dir and one spool drain run, then re-run both idempotently.
- Marker file only appears on success and supports Hypervisor reaper.
- Stage 1 path imports no OCR/VLM/embedding modules.

### Task 2.0: Foreground Gating Precondition
- **Location**: `autocapture_nx/processing/idle.py`, `autocapture_nx/runtime/batch.py`, `config/default.json`
- **Description**: Enforce active-state rule first: while user is active, only capture+kernel work proceeds; all batch/background ingest and Stage2+ processing are paused.
- **Complexity**: 7/10
- **Dependencies**: Sprint 1 complete
- **Acceptance Criteria**:
  - No Stage1/Stage2 background processing executes in active state.
- **Validation**:
  - Active/idle transition tests and resource-budget assertions.

### Task 2.1: Handoff Ingest Core
- **Location**: `autocapture_nx/ingest/handoff_ingest.py` (new), `autocapture_nx/ingest/__init__.py`
- **Description**: Implement metadata copy (`INSERT OR IGNORE`) + media import (`hardlink` first, copy fallback) with file-lock and transaction semantics.
- **Complexity**: 8/10
- **Dependencies**: Task 2.0
- **Acceptance Criteria**:
  - Restart-safe ingest with deterministic outcomes.
  - Partial copy protection via temp file + atomic rename.
- **Validation**:
  - Unit tests for idempotency, partial failure recovery, and cross-device hardlink fallback.

### Task 2.2: Handoff CLI Group
- **Location**: `autocapture_nx/cli.py` or `autocapture_nx/cli_handoff.py` (new)
- **Description**: Add `handoff ingest` and `handoff drain` with strict/no-strict and mode flags.
- **Complexity**: 6/10
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Usable one-line operator commands for single and batch ingest.
- **Validation**:
  - CLI tests plus smoke run against synthetic handoff fixture.

### Task 2.3: Reap Eligibility Marker v1
- **Location**: `autocapture_nx/ingest/handoff_ingest.py`, `docs/handoff-stage1-contract.md`
- **Description**: Emit atomic `reap_eligible.json` only after all required ingest checks pass.
- **Complexity**: 5/10
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Marker schema matches contract exactly.
  - Marker write sequence is atomic (`tmp write -> fsync file -> rename -> fsync dir`).
  - No marker written on failed ingest.
- **Validation**:
  - Marker schema tests and negative-path ingest tests.
  - Crash/restart simulation around marker-write boundary.

### Task 2.4: Stage 1 Throughput + Budget Guardrails
- **Location**: `autocapture_nx/runtime/batch.py`, `autocapture_nx/processing/idle.py`, `config/default.json`, `contracts/config_schema.json`
- **Description**: Add bounded worker pool and budget-aware scheduling modes (active-safe and idle-max).
- **Complexity**: 7/10
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Active mode respects CPU/RAM caps; idle mode drains backlog aggressively.
  - Throughput gate uses calibrated p95/p99 processing rates, not mean only.
- **Validation**:
  - Budget/load tests and throughput regression benchmarks.
  - Calibration test against recorded production-like traces.

### Task 2.5: Stage 1 Ultralight Import Guard
- **Location**: `tests/test_stage1_import_guard.py` (new), Stage1 module import paths
- **Description**: Add import-graph/runtime guard that fails if Stage1 execution path imports OCR/VLM/embedding code.
- **Complexity**: 5/10
- **Dependencies**: Tasks 2.1-2.2
- **Acceptance Criteria**:
  - Stage1 path cannot import heavy modules in CI.
- **Validation**:
  - Import inspection gate and runtime monkeypatch guard tests.

## Sprint 3: Stage 2+ Offline Processing + Query Read-Only Invariants
**Goal**: Ensure heavy processing only runs offline while query remains instant and read-only over precomputed artifacts.
**Skills**: `evidence-trace-auditor`, `policygate-penetration-suite`, `resource-budget-enforcer`
**Demo/Validation**:
- User-active signal blocks Stage2+ heavy work.
- Query path performs no decode/extract/VLM scheduling.
- Missing artifacts return structured “not available yet” without side effects.

### Task 3.1: Foreground Gating Enforcement
- **Location**: `autocapture_nx/processing/idle.py`, `autocapture_nx/runtime/batch.py`
- **Description**: Enforce fail-closed active-state behavior with explicit telemetry.
- **Complexity**: 7/10
- **Dependencies**: Sprint 2 complete
- **Acceptance Criteria**:
  - No heavy plugins/VLM calls while active.
- **Validation**:
  - Unit/integration tests with synthetic activity signal transitions.

### Task 3.2: Query-Time No-Processing Policy
- **Location**: query handlers in `autocapture_nx/*` and CLI query command paths
- **Description**: Disable `schedule_extract` and any `allow_decode_extract` behavior in interactive mode.
- **Complexity**: 6/10
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Queries read precomputed artifacts only.
  - Query produces no metadata writes.
  - Query opens DB in read-only/query-only mode and write attempts fail.
- **Validation**:
  - Regression tests: no VLM calls, no derived writes during query.
  - Negative tests that intentionally attempt writes during query and assert failure.

### Task 3.3: Citeability Hardening
- **Location**: derived artifact writers/indexers in `autocapture_nx/processing/*`
- **Description**: Enforce source record IDs + bboxes + model/prompt fingerprint on derived outputs.
- **Complexity**: 7/10
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - All answerable claims map to evidence chain; otherwise explicit indeterminate.
- **Validation**:
  - Evidence-trace audit suite pass.

## Sprint 4: UIA/DirectShell Ingestion Delta Closure
**Goal**: Finalize mandatory metadata-first UIA linkage, fallback integrity gate, deterministic IDs, and frame-linkage payload invariants.
**Skills**: `config-matrix-validator`, `python-testing-patterns`, `policygate-penetration-suite`
**Demo/Validation**:
- Frame with `uia_ref` emits `obs.uia.focus/context/operable` docs with valid bboxes.
- Metadata lookup always wins over latest snapshot fallback.
- Fallback hash mismatch emits no UIA docs and never crashes pipeline.

### Task 4.1: Metadata-First + Fallback Hash Gate Enforcement
- **Location**: `autocapture_nx/plugins/builtin/processing/sst/uia_context.py` (or equivalent), `config/default.json`
- **Description**: Resolve by `uia_ref.record_id` from metadata first; fallback only on lookup miss; require `.sha256` validation when fallback used.
- **Complexity**: 7/10
- **Dependencies**: Sprint 2 complete
- **Acceptance Criteria**:
  - Contract behavior matches Hypervisor runtime payload expectations exactly.
- **Validation**:
  - Unit tests for metadata-first priority and hash-mismatch rejection.

### Task 4.2: Deterministic IDs + Linkage Fields
- **Location**: same UIA plugin module + SST provider wiring
- **Description**: Ensure doc IDs derive from `uia_ref.record_id + section + index`; include required linkage fields (`uia_record_id`, `uia_content_hash`, `hwnd`, `window_title`, `window_pid`).
- **Complexity**: 6/10
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Stable IDs across reruns and complete linkage payload on emitted docs.
- **Validation**:
  - Deterministic rerun tests and bbox numeric validity tests.

### Task 4.3: Integration + Fail-Open Stability
- **Location**: `tests/*uia*`, pipeline integration tests
- **Description**: Add integration coverage for contract-compliant frame + sidecar inputs and corrupted input cases.
- **Complexity**: 6/10
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - UIA load/parse errors only warn and continue.
- **Validation**:
  - Integration test suite pass with intentionally malformed snapshots.

## Sprint 5: Golden Q40 Strict Closure + Overnight Soak + Rollout
**Goal**: Achieve strict correctness gate and operational readiness under nightly batch conditions.
**Skills**: `golden-answer-harness`, `deterministic-tests-marshal`, `perf-regression-gate`, `resource-budget-enforcer`
**Demo/Validation**:
- Strict golden mode reports exactly `40/40 evaluated`, `0 skipped`, `0 failed`.
- Overnight soak completes without crash loops and with retention-safe burn-down trajectory.
- Runbook + dashboards prove 6-day media retention safety.

### Task 5.1: Golden Strictness Harness Normalization
- **Location**: `tools/run_*golden*`, `tools/soak/*`, golden report builders under `autocapture_nx/evals/*`
- **Description**: Enforce strict evaluator semantics and expose partial/uncertain mismatches as failures.
- **Complexity**: 8/10
- **Dependencies**: Sprints 3 and 4 complete
- **Acceptance Criteria**:
  - Partial matches never marked pass for advanced-set expected answers.
- **Validation**:
  - Repeated deterministic strict runs (minimum 3) with identical pass/fail outputs.

### Task 5.2: Throughput + SLA Admission Gate
- **Location**: `autocapture_nx/runtime/batch.py`, soak verification scripts
- **Description**: Add admission check that projected processing rate clears 6-day retention window with safety margin.
- **Complexity**: 7/10
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Gate blocks rollout if projected backlog burn-down violates SLA under calibrated p95/p99 throughput.
- **Validation**:
  - SLA estimator tests with synthetic burst workloads.

### Task 5.3: Lockstep Release Checklist
- **Location**: `docs/runbooks/stage1-stage2-lockstep-release.md` (new), `docs/plans/README.md`
- **Description**: Publish final repo↔hypervisor coordinated release checklist and rollback triggers.
- **Complexity**: 5/10
- **Dependencies**: Task 5.2
- **Acceptance Criteria**:
  - Operator can execute go-live and backout from one checklist.
- **Validation**:
  - Tabletop dry run with latest baseline metrics.

## Testing Strategy
- Run full unit + integration suite after every sprint.
- Run strict golden smoke subset at every sprint exit; run full strict Q40 at Sprint 5 entry/exit.
- Run policy/security/fail-open tests on any ingest or plugin boundary changes.
- Run deterministic reruns for Stage 1 idempotency and golden strictness.
- Run throughput and resource-budget gates on batch scheduler changes.
- Run strict golden gauntlet at Sprint 5 entry and exit with archived reports.
- Pin determinism controls in gates: seed, clock/timezone/locale, serialization order, and flake-rate threshold.

## Hard Gates (Must Pass)
- Stage 1 ingestion path imports no OCR/VLM/embedding code.
- Query path performs no write/scheduling/decode/extract operations.
- UIA metadata-first contract and fallback hash integrity are enforced.
- Strict golden semantics: `40/40 evaluated`, `0 skipped`, `0 failed`.
- SLA gate indicates backlog can be processed before 6-day retention reap boundary.
- Localhost-only bind is enforced and fails closed.
- No local deletion endpoints/actions are exposed.
- Raw-first storage remains intact; sanitization occurs only on explicit export paths.
- Citation-required answer policy is enforced by default.
- Any new privileged behavior emits append-only audit records.

## Potential Risks & Gotchas
- Schema drift between `metadata` vs legacy `records` tables may break ingest assumptions.
  - Mitigation: include compatibility migration shim and schema validation preflight.
- Marker contract drift with Hypervisor can create false-reap or never-reap states.
  - Mitigation: versioned marker schema and parser conformance tests in both repos.
- Deterministic ID regressions from serialization order changes.
  - Mitigation: canonical JSON encoding and stable field ordering in ID derivation.
- False pass risk in golden scoring from partial/evidence-mismatch handling.
  - Mitigation: strict matcher mode that fails any expected-answer mismatch.

## Rollback Plan
- Keep `autocapture-prime` compatibility path until Sprint 5 exit criteria pass.
- Feature-flag new handoff ingest and UIA strict behavior per config.
- If regressions appear:
  - disable new ingest path,
  - revert to last known stable batch/query config,
  - preserve metadata/media artifacts for replay and forensic validation.

## Exit Criteria
- All sprint demos validated.
- Full gate suite green.
- Hypervisor sister-doc checkpoint signoff recorded with matching `contract_version` and `schema_hash`.
- Release checklist completed with no unresolved blocker.
