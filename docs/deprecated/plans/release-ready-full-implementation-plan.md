# Plan: Release-Ready Full Implementation

**Generated**: 2026-02-17  
**Estimated Complexity**: High

## Overview
This plan drives `autocapture_prime` to release-ready status by closing all remaining gaps across correctness, reliability, performance, security, and citeability. The delivery target is strict `20/20` Q/H accuracy (metadata-only answering path), reproducible and stable under soak preconditions, with hard gates for orchestration, policy, and evidence integrity.

The approach is blocker-first:
1. Stabilize runtime contracts (Hypervisor-owned VLM, PromptOps path correctness).
2. Harden extraction/index/reasoning quality so answers are generic and non-cheating.
3. Enforce deterministic quality gates and soak-readiness gates.
4. Ship with a locked matrix showing implemented, verified, and release-approved rows.

## Prerequisites
- Canonical VLM endpoint policy exists and is pinned for release profile execution.
  - Runtime supports canonical localhost VLM endpoints.
  - Release profile is pinned to `http://127.0.0.1:8000/v1` serving alias `internvl3_5_8b`.
- Endpoint/profile drift is gate-checked before any golden run.
- Sidecar contract writes required records under `/mnt/d/autocapture`.
- Python venv present at `.venv/`.
- Golden fixtures and eval cases:
  - `docs/query_eval_cases_advanced20.json`
  - `docs/query_eval_cases_hard10.json`
  - `docs/autocapture_prime_testquestions2.txt`
- Existing reports used as baseline:
  - `docs/reports/implementation_matrix.md`
  - `docs/reports/autocapture_prime_codex_implementation_matrix.md`
  - `docs/reports/question-validation-plugin-trace-2026-02-13.md`

## Skill Usage Map (By Section)
- **Sprint 1-2 (runtime + failures):** `ccpm-debugging`  
  Why: enforce root-cause fixes over tactical patches.
- **Sprint 3-5 (answer quality + eval correctness):** `golden-answer-harness`  
  Why: strict scenario scoring, anti-drift validation, reproducible pass/fail evidence.
- **Sprint 1-7 (all command execution):** `shell-lint-ps-wsl`  
  Why: command correctness and shell compatibility guardrails.
- **Sprint 2-7 (all test additions):** `python-testing-patterns`  
  Why: deterministic unit/integration tests for each behavior change.
- **Sprint 6 (budgets + governance):** `resource-budget-enforcer`  
  Why: enforce active/idle CPU/RAM constraints and backpressure behavior.
- **Sprint 5-7 (citations/provenance):** `evidence-trace-auditor`  
  Why: guarantee claim-to-evidence chain and indeterminate labeling.
- **Sprint 7 (release perf gate):** `perf-regression-gate`  
  Why: block shipping on latency/throughput regressions.

## Sprint 1: Runtime Contract Hardening
**Goal**: Make PromptOps + VLM orchestration deterministic and fail-closed.  
**Demo/Validation**:
- `tools/gq.sh` no longer fails due lifecycle conflicts or endpoint drift.
- Concurrent callers serialize VLM access without restart thrash.

### Task 1.1: Enforce Hypervisor-owned VLM Contract
- **Location**: `autocapture_nx/inference/vllm_endpoint.py`, `autocapture_nx/kernel/query.py`, `tools/run_advanced10_queries.py`
- **Description**: Lock endpoint/model checks to localhost 8000 contract, bounded retries, orchestrator handoff, clear structured errors.
- **Complexity**: 6
- **Dependencies**: none
- **Acceptance Criteria**:
  - No local start/stop lifecycle in `autocapture_prime`.
  - Preflight requires models + completion ping before query execution.
- **Validation**:
  - `tests/test_external_vllm_endpoint_policy.py`
  - new integration test for retry + orchestrator fallback.

### Task 1.2: PromptOps Query Integrity Guard
- **Location**: `autocapture/promptops/engine.py`, `tests/test_promptops_layer.py`
- **Description**: Ensure no cross-query contamination, immutable current query input path.
- **Complexity**: 4
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Prepared query never reuses stored stale text.
  - Trace records include source-of-prompt fields.
- **Validation**:
  - `tests/test_promptops_layer.py`
  - `tests/test_query_trace_fields.py`

### Task 1.3: VLM Request Gate + Timeout Policy
- **Location**: `autocapture_nx/inference/vllm_endpoint.py`, `config/default.json`
- **Description**: Central queue/gate (`max_inflight`) with bounded timeouts tuned for 8B model latency.
- **Complexity**: 5
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Concurrency stable under N parallel callers.
  - Timeout errors are explicit and actionable.
- **Validation**:
  - `tools/gate_concurrency.py`
  - new test `tests/test_vlm_inflight_gate.py`.

## Sprint 2: Ingest and Contract Determinism
**Goal**: Ensure persisted extracted state is complete, deterministic, and query-ready.  
**Demo/Validation**:
- Single-image and live-ingest runs produce expected schema records without screenshot reads at query time.

### Task 2.1: Sidecar Contract Validation as Hard Gate
- **Location**: `tools/sidecar_contract_validate.py`, `tools/run_golden_qh_cycle.sh`, `docs/windows-sidecar-capture-interface.md`
- **Description**: Make required contract rows (`activity`, `journal`, `ledger`, `metadata`, media pointer mode) hard preconditions.
- **Complexity**: 5
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Golden run fails early with machine-readable missing-contract diagnostics.
- **Validation**:
  - `tests/test_sidecar_contract_validate.py`
  - integration run with synthetic missing artifacts.

### Task 2.2: Chronicle Phase Coverage and Replay Determinism
- **Location**: `tools/gate_phase0.py` ... `tools/gate_phase8.py`, `tools/gate_chronicle_stack.py`, `tests/`
- **Description**: Verify each phase produces deterministic outputs and replay-safe IDs.
- **Complexity**: 7
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Phase gates pass and produce pinned snapshots.
- **Validation**:
  - phase gate suite + repeated run hash comparisons.

### Task 2.3: Persistence Policy Lock (No Loss, No Local Deletion)
- **Location**: storage plugins + policy gates, `tools/gate_ledger.py`
- **Description**: Ensure append-only behavior and no pruning/deletion paths.
- **Complexity**: 5
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Audit log proves immutable append sequence.
- **Validation**:
  - `audit-log-integrity-checker` workflow + ledger gate tests.

## Sprint 3: Extraction Fidelity (Generic, Not Question-Specific)
**Goal**: Raise extracted UI state quality for arbitrary natural-language querying.  
**Demo/Validation**:
- Structured outputs for windows/tables/timelines/forms/calendars/chats improve without per-question hacks.

### Task 3.1: Two-Pass VLM Pipeline Enforcement (Thumbnail → Hi-Res ROI)
- **Location**: `plugins/builtin/processing_sst_vlm_ui/plugin.py`, `plugins/builtin/vlm_vllm_localhost/plugin.py`, `autocapture_nx/kernel/query.py`
- **Description**: Enforce ROI proposal from low-res pass; crop/original high-res pass; merge to canonical UI state JSON.
- **Complexity**: 8
- **Dependencies**: Sprint 1-2
- **Acceptance Criteria**:
  - UI state includes robust window/entity geometry + topic facts.
- **Validation**:
  - `tests/test_ui_state_merge.py`
  - fixture-based quality checks.

### Task 3.2: OCR as Assistive Signal, Not Primary Answer Engine
- **Location**: OCR + VLM merge logic in processing/query path
- **Description**: Use OCR for supplemental text evidence and confidence boost; VLM remains structural primary.
- **Complexity**: 6
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Reduced OCR-noise dominance in final answers.
- **Validation**:
  - plugin-contribution trace tests and side-by-side artifact diffs.

### Task 3.3: Canonical Record Normalization
- **Location**: state/persistence layers (canonical record serializer)
- **Description**: Standardize extracted model output to canonical record schema with provenance hashes.
- **Complexity**: 7
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Every extracted record has `sample_id`, `model_id`, `prompt_hash`, `provenance`.
- **Validation**:
  - schema tests + `tools/gate_screen_schema.py`.

## Sprint 4: Indexing, Embeddings, and Retrieval Robustness
**Goal**: Answer from stored extracted state only, with reliable retrieval and ranking.  
**Demo/Validation**:
- Query path resolves from DB/index layers with reproducible evidence chain.

### Task 4.1: Embedding Endpoint Integration (Non-deterministic fallback removed)
- **Location**: embedder plugins, retrieval/reranker chain, config profiles
- **Description**: Require real embedding path when configured; no deterministic fake vectors for golden profile.
- **Complexity**: 7
- **Dependencies**: Sprint 1-3
- **Acceptance Criteria**:
  - Golden profile blocks when embeddings unavailable (unless explicit degraded profile).
- **Validation**:
  - `tests/test_golden_full_profile_lock.py`
  - new `tests/test_embedding_required_policy.py`.

### Task 4.2: Late-Interaction Index Path Bring-up
- **Location**: `plugins/builtin/colbert_indexer_hash/plugin.py`, `plugins/builtin/colbert_indexer_torch/plugin.py`, `plugins/builtin/reranker_colbert_hash/plugin.py`, `plugins/builtin/reranker_colbert_torch/plugin.py`, query planner
- **Description**: Implement/validate late interaction path and contribution metrics.
- **Complexity**: 8
- **Dependencies**: Task 4.1, Task 3.3
- **Acceptance Criteria**:
  - Retriever/reranker contribution visible in traces.
- **Validation**:
  - `tools/query_effectiveness_report.py`
  - new retrieval benchmark fixture tests.

### Task 4.3: Retrieval Strategy Router Hardening
- **Location**: `autocapture_nx/kernel/query.py`, PromptOps service
- **Description**: Topic-aware strategy routing with confidence/citation thresholds and fallback hierarchy.
- **Complexity**: 6
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - Stable strategy path and no uncited confident claims.
- **Validation**:
  - golden harness + reranker unit tests.

## Sprint 5: Q/H Correctness Closure (20/20)
**Goal**: Reach and hold strict `20/20` with reproducibility and confidence calibration.  
**Demo/Validation**:
- Three consecutive strict runs pass all Q/H cases with drift bounds.

### Task 5.1: Strict Evaluator Rules (No False Passes)
- **Location**: `tools/run_advanced10_queries.py`, `tools/query_eval_suite.py`, `tools/query_feedback.py`
- **Description**: Disable weak pass criteria; strict semantic + structured checks only.
- **Complexity**: 6
- **Dependencies**: Sprint 3-4
- **Acceptance Criteria**:
  - Incorrect answer never reports pass, even with positive user feedback text.
- **Validation**:
  - evaluator tests + adversarial grading fixtures.

### Task 5.2: Plugin Contribution and Confidence Matrix
- **Location**: `tools/generate_qh_plugin_validation_report.py`, `tools/render_advanced20_answers.py`, traces in `artifacts/advanced10/`
- **Description**: Emit per-question plugin path, confidence, evidence, and correctness attribution.
- **Complexity**: 5
- **Dependencies**: Task 5.1, Task 4.3
- **Acceptance Criteria**:
  - Every question row lists contributing plugins and confidence breakdown.
- **Validation**:
  - snapshot tests for trace schema + report output.

### Task 5.3: PromptOps Self-Optimization Loop
- **Location**: `autocapture/promptops/*`, prompt store artifacts, metrics pipeline
- **Description**: Record failures, rewrite templates, A/B evaluate, promote only improvements.
- **Complexity**: 7
- **Dependencies**: Task 5.2
- **Acceptance Criteria**:
  - Query rewrite effectiveness is measured and versioned.
- **Validation**:
  - `tools/promptops_eval.py`
  - `tools/promptops_metrics_report.py`
  - `tools/gate_promptops_perf.py`, `tools/gate_promptops_policy.py`.

### Task 5.4: Anti-Overfit Holdout and Paraphrase Gate
- **Location**: eval harness, fixtures, and gates in `tools/` + `tests/fixtures/`
- **Description**: Add blind holdout fixtures and paraphrase-variance checks; block release on unseen-set regressions.
- **Complexity**: 6
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Performance on holdout/paraphrase set stays within configured tolerance.
- **Validation**:
  - golden harness tests + dedicated holdout gate report.

## Sprint 6: Security, Policy, and Budget Gates
**Goal**: Enforce release non-negotiables in executable gates.  
**Demo/Validation**:
- Security/policy/perf gates block non-compliant builds.

### Task 6.1: Localhost-only + Export Sanitization Boundaries
- **Location**: network/policy modules, export paths, egress gateway
- **Description**: Ensure local raw data remains unmasked; masking only on explicit export.
- **Complexity**: 6
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - No local masking side effects; export sanitization test coverage complete.
- **Validation**:
  - `tools/gate_security.py`, `tools/gate_promptops_policy.py`, export tests.

### Task 6.2: Active/Idle Resource Governance
- **Location**: scheduler/governor modules, resource gates
- **Description**: Enforce active-mode processing pause and idle CPU/RAM budget constraints.
- **Complexity**: 7
- **Dependencies**: Sprint 1-2
- **Acceptance Criteria**:
  - Active mode runs only capture/kernel; background processing paused.
  - Idle budget assertions pass.
- **Validation**:
  - `tools/gate_slo_budget.py`
  - `tools/gate_perf.py`
  - `tests/test_governor_gating.py`
  - `tests/test_resource_budget_enforcement.py`
  - `tests/test_runtime_budgets.py`
  - budget-enforcer tests.

### Task 6.3: PolicyGate + Untrusted Plugin Input Hardening
- **Location**: plugin execution boundaries and policy gate checks
- **Description**: Fuzz plugin/external inputs to validate fail-closed behavior.
- **Complexity**: 6
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - No unsafe plugin input path bypasses policy checks.
- **Validation**:
  - policy penetration suite tests + security gate.

### Task 6.4: Tray Non-Negotiable Gate
- **Location**: tray policy/definitions + tests
- **Description**: Enforce that tray exposes no capture pause/deletion actions.
- **Complexity**: 4
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Any tray menu regression exposing forbidden actions blocks release.
- **Validation**:
  - `tests/test_tray_menu_policy.py`
  - `tests/test_windows_tray_definitions.py`.

### Task 6.5: No Deletion Surface Gate
- **Location**: CLI/API/route layers + policy gates
- **Description**: Assert no delete/prune endpoints; only archive/migrate semantics allowed.
- **Complexity**: 5
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Any delete or retention-prune surface fails gate.
- **Validation**:
  - route/CLI policy tests + security gate artifacts.

## Sprint 7: Release Packaging and Soak Admission
**Goal**: Build a deterministic release gate and soak admission checklist.  
**Demo/Validation**:
- One command yields complete release evidence bundle and go/no-go outcome.

### Task 7.1: Unified Release Gate Command
- **Location**: `tools/` gate runner scripts, `docs/runbooks/`
- **Description**: Create a single short command that runs required gates and emits report bundle.
- **Complexity**: 5
- **Dependencies**: Sprint 1-6
- **Acceptance Criteria**:
  - Produces reproducible machine-readable and human-readable release verdict.
  - Fail-closed verdict rule: any non-pass status (`warn`, `skip`, `fail`, `error`) in required checks blocks release.
- **Validation**:
  - CI/local run parity checks.
  - Required gate manifest includes:
    - `tools/gate_phase0.py` ... `tools/gate_phase8.py`
    - `tools/gate_security.py`
    - `tools/gate_perf.py`
    - `tools/gate_slo_budget.py`
    - `tools/gate_promptops_policy.py`
    - `tools/gate_promptops_perf.py`
    - `tools/gate_screen_schema.py`
    - `tools/gate_ledger.py`
    - `tools/gate_deps_lock.py`
    - `tools/gate_static.py`
    - `tools/gate_vuln.py`
    - `tools/gate_doctor.py`
    - `tools/gate_full_repo_miss_matrix.py`
    - `tools/gate_acceptance_coverage.py`
    - `tools/validate_blueprint_spec.py`
    - `tools/run_mod021_low_resource.sh`.

### Task 7.2: Implementation Matrix Finalization
- **Location**: `docs/reports/implementation_matrix.md`, `docs/reports/autocapture_prime_codex_implementation_matrix.md`
- **Description**: Update each row with implementation proof (module/test/artifact) and status.
- **Complexity**: 4
- **Dependencies**: all prior sprints
- **Acceptance Criteria**:
  - No ambiguous rows; all outstanding items either implemented or explicitly deferred with rationale.
- **Validation**:
  - `tools/gate_full_repo_miss_matrix.py`
  - repo-wide row check script.

### Task 7.3: Soak Admission Policy
- **Location**: soak scripts + runbook
- **Description**: Define minimum pass criteria to enter 24h soak with reliability SLOs and integrity constraints.
- **Complexity**: 3
- **Dependencies**: Task 7.2, Sprint 6 outputs
- **Acceptance Criteria**:
  - Soak can start only when admission bundle is green.
  - Requires 3x consecutive strict `20/20` and full release gate pass.
  - Requires 24h soak completion with:
    - zero crash-loop events,
    - zero ledger/proof-bundle integrity failures,
    - citation resolution success within target threshold,
    - sustained active/idle budget compliance.
- **Validation**:
  - dry-run admission and enforced deny on red gates.

## Testing Strategy
- Unit tests for each behavior change (policy, query prep, routing, evaluator strictness).
- Integration tests for end-to-end ingest→extract→index→query metadata-only flow.
- Reproducibility tests:
  - Repeat advanced20 runs with confidence drift tolerance.
  - Hash/stability checks on traces and outputs.
- Gate tests:
  - promptops policy/perf
  - security/vuln/static/deps
  - phase and matrix gates
  - performance and budget gates.

## Potential Risks & Gotchas
- VLM endpoint “looks up” in watcher state but is not actually reachable from this runtime.
  - **Mitigation**: hard preflight and socket-level checks, orchestrator retry bounded.
- Overfitting to current screenshot fixture.
  - **Mitigation**: enforce generic extraction classes and add adversarial fixture variants.
- False positive evaluator passes due weak checks.
  - **Mitigation**: strict schema-aware pass criteria only; no subjective override.
- Plugin contribution trace drift.
  - **Mitigation**: schema-validated trace artifacts and snapshot tests.
- Resource contention under active user sessions.
  - **Mitigation**: scheduler gates + budget enforcer.

## Rollback Plan
- Keep previous stable golden profile and evaluator in tagged backup config.
- For each sprint, gate changes behind config switches until validated.
- If regressions occur:
  - revert sprint-specific commits,
  - restore prior profile and gate scripts,
  - rerun strict advanced20 to confirm baseline restoration.

## Release Exit Criteria
- `20/20` on strict Q/H suite, repeated at least 3 consecutive runs with no confidence drift beyond tolerance.
- PromptOps mandatory in query path, with measurable rewrite/improvement metrics.
- `MOD-021` pass artifact present (`tools/run_mod021_low_resource.sh`).
- Coverage map and blueprint integrity are validated and green:
  - `tools/gate_acceptance_coverage.py`
  - `tools/validate_blueprint_spec.py`.
- All required gates green (fail-closed):
  - contract/phase/policy/security/perf/budget/matrix/coverage gates.
- Evidence bundle generated and archived:
  - answer correctness, plugin contribution, confidence, citations, gate outputs, and proof-bundle verification/replay results (`tests/test_proof_bundle_verify.py`, `tests/test_proof_bundle_replay.py`).
