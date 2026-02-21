# Plan: Golden Pipeline Core Remediation

**Generated**: 2026-02-18  
**Estimated Complexity**: High

## Overview
This plan closes the remaining failure modes blocking golden-pipeline readiness:
- false-green matrix states (`ok=true` with all cases skipped),
- unstable VLM dependency handling,
- incomplete promptops optimization loops,
- insufficient plugin-path attribution visibility,
- inability to guarantee processing throughput before six-day retention limits.

The goal state is deterministic and auditable: every Q/H case is either `pass` with citations and plugin-path evidence, or `fail` with actionable diagnostics. No skipped-as-pass outcomes.

## Skills
### Skills Used To Plan
- `plan-harder`: enforces phased sprint planning with atomic, testable tasks.
- `ccpm-debugging`: root-cause framing to avoid tactical symptom patches.
- `config-matrix-validator`: validates endpoint/config assumptions as explicit contract rows.

### Skills To Use During Implementation
- `golden-answer-harness`: run and score Q/H golden suites.
- `deterministic-tests-marshal`: repeated-run drift detection and deterministic gates.
- `evidence-trace-auditor`: enforce citation-backed answer integrity.
- `perf-regression-gate`: latency/throughput SLO checks.
- `resource-budget-enforcer`: idle/active budget enforcement verification.
- `logging-best-practices` + `python-observability`: structured metrics/traces for Python workers.
- `state-recovery-simulator`: verify graceful recovery for VLM/gateway crashes.
- `policygate-penetration-suite`: confirm fail-closed behavior on unsafe/plugin inputs.
- `python-testing-patterns`: deterministic unit/integration coverage for all behavioral changes.

## Prerequisites
- Local services reachable in same namespace:
  - `127.0.0.1:8000` VLM
  - `127.0.0.1:8001` embeddings
  - `127.0.0.1:8011` grounding
  - `127.0.0.1:34221` orchestrator/gateway
  - `127.0.0.1:8787` popup API only
- Data roots:
  - `/mnt/d/autocapture/media`
  - `/mnt/d/autocapture/metadata.db`
  - sidecar journal/ledger/activity signal contract files

## Sprint 0: Foundational Code-Hardening Prerequisites
**Goal**: close high-leverage correctness/security issues that can destabilize golden gates.  
**Demo/Validation**:
- all hardening unit tests pass,
- no unsafe archive extraction path remains,
- no custom `exec`-reload path remains in plugin manager.

### Task 0.1: Safe archive extraction (zip-slip resistant)
- **Location**: `autocapture/storage/archive.py`, new tests in `tests/test_archive_safe_extract.py`
- **Description**: replace blind `extractall` with member-by-member safe extraction and shared filename safety checks in verify + import paths.
- **Complexity**: 5
- **Dependencies**: none
- **Acceptance Criteria**:
  - traversal/absolute/unsafe members are rejected fail-closed.
- **Validation**:
  - traversal + absolute-path fixtures fail; normal archive fixture succeeds.

### Task 0.2: Replace exec-based plugin reload
- **Location**: `autocapture/plugins/manager.py`, tests in `tests/test_plugin_manager_reload.py`
- **Description**: swap manual `compile/exec` reload path for `importlib.reload`-based flow with rich context errors.
- **Complexity**: 4
- **Dependencies**: Task 0.1
- **Acceptance Criteria**:
  - reload works and file contains no custom `exec` reload path.
- **Validation**:
  - plugin reload regression tests.

### Task 0.3: Add subprocess timeout contracts to validators
- **Location**: `autocapture/codex/validators.py`, tests in `tests/test_codex_validators_timeout.py`
- **Description**: enforce bounded subprocess timeouts and deterministic timeout reporting.
- **Complexity**: 4
- **Dependencies**: Task 0.2
- **Acceptance Criteria**:
  - hung validator returns structured timeout outcome.
- **Validation**:
  - synthetic sleep-hang test.

### Task 0.4: Capture spool durability/idempotency semantics
- **Location**: `autocapture/capture/spool.py`, `autocapture/capture/pipelines.py`, tests
- **Description**: make append idempotent for identical payloads, collision-fail for mismatched payloads, and surface write failures upstream.
- **Complexity**: 5
- **Dependencies**: Task 0.3
- **Acceptance Criteria**:
  - duplicate identical writes pass; conflicting writes fail with explicit error.
- **Validation**:
  - spool collision/idempotency unit tests.

### Task 0.5: Research runner error/threshold robustness
- **Location**: `autocapture/research/runner.py`, tests
- **Description**: persist plugin-load errors, avoid silent degradation, and harden threshold parsing/clamping.
- **Complexity**: 4
- **Dependencies**: Task 0.4
- **Acceptance Criteria**:
  - invalid thresholds do not crash; plugin load errors are visible.
- **Validation**:
  - malformed-config and plugin-failure tests.

### Task 0.6: RRF fusion type safety
- **Location**: `autocapture/retrieval/fusion.py`, tests
- **Description**: normalize doc IDs to deterministic string keys and keep stable ordering.
- **Complexity**: 2
- **Dependencies**: Task 0.5
- **Acceptance Criteria**:
  - mixed-type doc IDs do not raise and remain deterministically sorted.
- **Validation**:
  - mixed-ID fixture test.

## Sprint 1: Truthful Gates And Matrix Semantics
**Goal**: remove false-green status and make skip handling explicit and non-shippable in strict mode.  
**Demo/Validation**:
- run Q40 matrix and verify non-zero evaluated requirement in strict mode.
- assert release gate fails when `matrix_evaluated == 0` or `matrix_skipped > 0` in strict profile.

### Task 1.1: Harden matrix evaluator semantics
- **Location**: `tools/eval_q40_matrix.py`
- **Description**: add strict mode contract:
  - `ok=false` if `matrix_evaluated == 0`,
  - `ok=false` if strict and any skipped cases exist,
  - explicit `failure_reasons[]` in output.
- **Complexity**: 4
- **Dependencies**: none
- **Acceptance Criteria**:
  - impossible for all-skipped run to emit `ok=true`.
  - output includes machine-readable reasons.
- **Validation**:
  - unit tests for all-skipped/all-failed/mixed states.

### Task 1.2: Propagate strict gate into golden cycle
- **Location**: `tools/run_golden_qh_cycle.sh`, `tools/q40.sh`, `tools/release_gate.py`
- **Description**: enforce evaluator strict mode in all golden/release wrappers and surface fail-fast messages.
- **Complexity**: 4
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - wrappers exit non-zero on strict matrix violations.
- **Validation**:
  - integration test with synthetic skipped artifact.

### Task 1.3: Add deterministic tests for gate invariants
- **Location**: `tests/test_eval_q40_matrix.py` (new), `tests/test_release_gate.py` (extend)
- **Description**: codify strict/relaxed behavior and regression snapshots.
- **Complexity**: 3
- **Dependencies**: Task 1.1, Task 1.2
- **Acceptance Criteria**:
  - deterministic pass/fail on fixed fixtures.
- **Validation**:
  - pytest targeted suite + rerun drift check.

## Sprint 2: PromptOps Path Enforcement And Attribution
**Goal**: ensure all query-time LLM/VLM prompt transformations and review metrics flow through promptops, with clear plugin contributions per answer.  
**Demo/Validation**:
- run query and return:
  - answer,
  - confidence,
  - promptops rewrite/review metadata,
  - per-plugin contribution table.

### Task 2.1: Enforce promptops interception for query path
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture/promptops/service.py`, `plugins/builtin/vlm_vllm_localhost/plugin.py`
- **Description**: make promptops path mandatory for eligible query/model calls under golden profile; fail closed when bypassed.
- **Complexity**: 6
- **Dependencies**: Sprint 1 complete
- **Acceptance Criteria**:
  - query artifacts include promptops metadata for every model call or explicit `not_applicable`.
- **Validation**:
  - unit tests on prompt rewrite + policy gates.

### Task 2.2: Add plugin-path contribution ledger per question
- **Location**: `tools/run_advanced10_queries.py`, `tools/question_validation_plugin_trace.py`, `artifacts/advanced10/*`
- **Description**: persist full plugin execution path with `used_in_final_answer`, contribution weight, and confidence deltas.
- **Complexity**: 5
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - each row in Q/H matrix includes contribution trace.
- **Validation**:
  - trace schema tests + fixture report assertions.

### Task 2.3: Close loop on feedback-backed optimization
- **Location**: `tools/promptops_optimize_once.py`, `tools/promptops_refresh_examples.py`, `tools/promptops_metrics_report.py`
- **Description**: when feedback labels answer incorrect, automatically generate review tasks and template improvements; record before/after deltas.
- **Complexity**: 6
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - optimizer artifacts show applied improvements and measured uplift.
- **Validation**:
  - promptops gate + metrics report tests.

## Sprint 3: VLM Batch Extraction Fidelity (No Query-Time Screenshot Dependency)
**Goal**: convert screenshot+HID into durable structured evidence so future answers rely on extracted metadata only.  
**Demo/Validation**:
- ingest a screenshot, remove direct image access for query step, still answer Q/H cases from stored derived records.

### Task 3.1: Two-pass image processing (thumbnail ROI + hi-res extraction)
- **Location**: `autocapture_nx/processing/*`, `plugins/builtin/processing.sst.ui_vlm/*` (or equivalent), `tools/run_single_image_golden.sh`
- **Description**: implement staged extraction:
  - pass 1: candidate ROI generation,
  - pass 2: hi-res ROI extraction with structured JSON outputs,
  - merge + de-dup into canonical UI state records.
- **Complexity**: 8
- **Dependencies**: Sprint 2 complete
- **Acceptance Criteria**:
  - derived UI state JSON complete enough for Q/H queries without raw image.
- **Validation**:
  - schema validation + golden fixture tests.

### Task 3.2: Crash-safe VLM interaction and bounded retries
- **Location**: `autocapture_nx/inference/vllm_endpoint.py`, `autocapture_nx/runtime/http_localhost.py`
- **Description**: add robust failure taxonomy (`timeout`, `connection_refused`, `model_unavailable`) and recovery-safe retry policy.
- **Complexity**: 5
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - failures do not crash pipeline; status artifacts show deterministic reason codes.
- **Validation**:
  - recovery simulation tests.

### Task 3.3: Strict metadata-only query gate
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/cli.py`, `tools/run_advanced10_queries.py`
- **Description**: enforce default query behavior from stored metadata/derived evidence only for golden mode.
- **Complexity**: 4
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - query-time image path disabled under golden profile.
- **Validation**:
  - metadata-only regression tests.

## Sprint 4: Throughput, Backlog, And Six-Day SLA
**Goal**: prove processing completes within retention window and remains within active/idle resource policy.  
**Demo/Validation**:
- backlog simulator shows processing ETA under six-day horizon.
- idle-mode batch processing honors CPU/RAM budget while maximizing GPU.

### Task 4.1: Add backlog throughput estimator and SLA gate
- **Location**: `tools/gate_golden_pipeline.py` (new or extend), `autocapture/runtime/scheduler.py`, `docs/runbooks/golden_pipeline_ops.md`
- **Description**: compute ingestion/processing rates and fail gate if projected lag exceeds retention horizon.
- **Complexity**: 6
- **Dependencies**: Sprint 3 complete
- **Acceptance Criteria**:
  - artifact outputs `eta_hours`, `lag_hours`, `retention_risk`.
- **Validation**:
  - synthetic load tests with fixed fixtures.

### Task 4.2: Enforce active/idle mode processor gating
- **Location**: scheduler/governor modules + tests
- **Description**: ensure only capture+kernel run when active; heavy processing shifts to idle windows.
- **Complexity**: 5
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - deterministic mode transitions logged with process class list.
- **Validation**:
  - budget enforcer tests + observability checks.

### Task 4.3: Expand Python observability
- **Location**: core Python workers, `tools/*` runners, `artifacts/observability/*`
- **Description**: add structured spans/events for each pipeline stage (queue wait, model latency, retries, parse quality, store write).
- **Complexity**: 5
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - no major Python worker runs as black box; every step has traceable metrics.
- **Validation**:
  - observability schema tests + sample trace report.

## Sprint 5: 40/40 Golden Closure And Soak Readiness
**Goal**: reach deterministic 40/40 pass, with confidence + rationale + plugin path printed for each case, then gate for soak.  
**Demo/Validation**:
- one command emits:
  - 40-case results,
  - confidence per case,
  - plugin path per case,
  - fail reasons for any miss,
  - soak-readiness verdict.

### Task 5.1: Q/H correctness hardening loop
- **Location**: query/arbitration + extraction modules, eval tools
- **Description**: iterate on generic reasoning/extraction classes (not question-specific shortcuts) until all cases pass.
- **Complexity**: 9
- **Dependencies**: Sprints 1-4 complete
- **Acceptance Criteria**:
  - `matrix_passed=40`, `matrix_failed=0`, `matrix_skipped=0`.
- **Validation**:
  - deterministic 3-run drift gate.

### Task 5.2: Confidence calibration and citation integrity
- **Location**: answer formatting and evidence modules
- **Description**: calibrate confidence tiers, reject uncited high-confidence claims, require explicit indeterminate state when uncitable.
- **Complexity**: 6
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - confidence aligns with evidence coverage.
- **Validation**:
  - evidence trace auditor + contract tests.

### Task 5.3: Soak start gate and runbook finalization
- **Location**: `tools/wsl/start_soak.sh`, `tools/wsl/soak_verify.sh`, docs runbooks/reports
- **Description**: block soak unless 40/40 + SLA + policy gates are green; generate operator runbook artifact.
- **Complexity**: 4
- **Dependencies**: Task 5.2
- **Acceptance Criteria**:
  - soak command refuses to start when gates fail.
- **Validation**:
  - simulated gate fail + gate pass scenarios.

## Testing Strategy
- Unit: evaluator semantics, promptops policy, citation integrity, scheduler transitions.
- Integration: single-image ingest to metadata-only query flow.
- Determinism: repeated-run signature checks and confidence drift thresholds.
- Resilience: VLM outage/restart recovery, orchestrator handoff, no-crash guarantees.
- Performance: p50/p95 query latency and pipeline throughput under synthetic load.

## Potential Risks & Gotchas
- VLM instability can hide correctness regressions by producing skips.
  - Mitigation: strict no-skip gate in golden profile.
- Overfitting to current screenshot/test set.
  - Mitigation: class-based extraction tests + synthetic perturbations.
- High-fidelity extraction can increase latency.
  - Mitigation: two-pass ROI pipeline + perf budget gate.
- Observability overhead can increase CPU.
  - Mitigation: sampled tracing + bounded payload sizes.

## Rollback Plan
- Keep strict gate code paths feature-flagged for emergency rollback (`AUTOCAPTURE_GOLDEN_STRICT=0`) but default to strict in golden profile.
- Preserve previous evaluation artifacts for A/B diffs.
- Roll back individual sprint changes by module if regressions violate performance/security constraints.

## Exit Criteria (Release-Ready)
- Q/H matrix: `40/40 pass`, `0 skipped`, `0 failed`.
- PromptOps:
  - interception enabled in golden flow,
  - metrics and review artifacts generated each cycle.
- Metadata-only query path produces correct answers with citations.
- Throughput gate projects completion inside six-day retention window.
- Soak gate allows start and verifies stable operation under expected load.
