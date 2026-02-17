# Plan: PromptOps Four Pillars Improvement

Generated: 2026-02-16
Estimated Complexity: High

## Overview

This plan hardens PromptOps as the mandatory query interface and improves all four pillars:

1. Performance: reduce per-query overhead and enforce bounded latency under load.
2. Accuracy: raise answer correctness through better query rewriting, evidence routing, and evaluation loops.
3. Security: fail-closed networking, strict localhost policy, and auditable handling of prompt artifacts.
4. Citeability: deterministic claim-to-evidence linkage for every answer or explicit indeterminate state.

Primary focus area:

- `autocapture/promptops/engine.py`
- `autocapture/promptops/propose.py`
- `autocapture/promptops/evaluate.py`
- `autocapture_nx/kernel/query.py`
- `autocapture/memory/answer_orchestrator.py`
- `tools/promptops_eval.py`

## Prerequisites

- Local config profile for golden pipeline (`config/default.json`) with PromptOps enabled.
- Stable local metadata/artifact directories (`data/promptops/*`, eval fixtures under `tests/fixtures/`).
- vLLM availability is optional for phases 1-3; required only for phase 4 live-model calibration.
- Existing test suites must be runnable in local virtualenv.

## Skill Execution Map

The following skills are mandatory for implementing this plan and are mapped to concrete sprint outcomes.

1. `plan-harder`
   - Why: maintain phased execution, dependency order, and acceptance-gated delivery.
   - Used in: all sprints as planning/governance wrapper.

2. `testing` and `python-testing-patterns`
   - Why: implement deterministic unit/integration/golden test coverage for all behavior changes.
   - Used in: sprints 1-6.

3. `deterministic-tests-marshal`
   - Why: detect and prevent flaky behavior in PromptOps eval/golden suites.
   - Used in: sprints 1, 3, 5, 6.

4. `golden-answer-harness`
   - Why: lock curated answer correctness with citation expectations and drift checks.
   - Used in: sprints 3 and 5.

5. `evidence-trace-auditor`
   - Why: enforce claim-to-evidence traceability and explicit indeterminate handling.
   - Used in: sprints 3 and 5.

6. `perf-regression-gate`
   - Why: enforce p50/p95 latency and throughput regression gates.
   - Used in: sprint 2 and sprint 5 gating.

7. `resource-budget-enforcer`
   - Why: verify idle/active budget compliance under realistic workload.
   - Used in: sprint 2 and sprint 5 operational validation.

8. `logging-observability` and `observability-engineer`
   - Why: add structured stage timings, plugin contribution telemetry, and chartable metrics.
   - Used in: sprints 1, 2, and 5.

9. `policygate-penetration-suite`
   - Why: fuzz untrusted plugin/external inputs and validate policy boundaries.
   - Used in: sprints 4 and 6.

10. `export-sanitization-verifier`
   - Why: ensure raw-first local storage stays intact and sanitization happens only on export paths.
   - Used in: sprint 4.

11. `audit-log-integrity-checker`
   - Why: validate append-only audit integrity and hash-chain continuity.
   - Used in: sprints 4 and 5.

12. `config-matrix-validator`
   - Why: validate profile/plugin/safe-mode config combinations and prevent drift.
   - Used in: sprints 5 and 6.

13. `security-best-practices`, `security-threat-model`, and `security-threats-to-tests`
   - Why: harden fail-closed behavior and convert threat paths into repeatable tests.
   - Used in: sprint 4 and sprint 6.

14. `ccpm-debugging`
   - Why: enforce root-cause workflow for failures/regressions instead of tactical patching.
   - Used in: all sprints when a regression or blocker is detected.

## Sprint 1: Baseline, Instrumentation, and Drift Guardrails

Goal: establish deterministic baselines and full observability for current PromptOps behavior before changing logic.

Demo/Validation Checklist:

- [x] Baseline report generated for PromptOps latency, success/failure rates, and citation coverage. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:97:fab34acd3c0c8519`, evidence: `artifacts/promptops/metrics_report_latest.json`)
- [x] PromptOps flow emits per-step timings and decision-state metrics. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:98:bf4fd5038884a7fc`, evidence: `artifacts/promptops/metrics_report_latest.json`)
- [x] Golden eval harness persists immutable baseline snapshot for regression diffs. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:99:4e96839c91385784`, evidence: `artifacts/advanced10/question_validation_plugin_trace_latest.json`)

Tasks:

1. Task: Define canonical PromptOps run schema and metric keys.
   - Inputs: current event types in `engine.py` metrics/history records.
   - Outputs: schema doc + typed writer helper in PromptOps module.
   - Files: `autocapture/promptops/engine.py`, `docs/metrics/promptops_metric_schema.md`.
   - Dependencies: none.
   - Acceptance Criteria: all PromptOps metric rows validate against schema.
   - Validation: unit tests for required fields and type constraints.

2. Task: Add end-to-end timing spans for PromptOps stages.
   - Inputs: prepare/propose/validate/evaluate/review pipeline stages.
   - Outputs: stage latency fields and aggregate request latency.
   - Files: `autocapture/promptops/engine.py`, `tests/test_promptops_layer.py`.
   - Dependencies: task 1.
   - Acceptance Criteria: one complete timing trace exists for every PromptOps invocation.
   - Validation: deterministic test asserting stage keys and monotonic timestamps.

3. Task: Expand harness output for drift detection.
   - Inputs: existing eval cases and harness outputs.
   - Outputs: versioned baseline schema and artifact at `data/promptops/baseline.json` with stable hashes for answers, citations, strategy path, plugin path, and confidence bands.
   - Files: `autocapture/promptops/harness.py`, `tools/promptops_eval.py`, `tests/test_promptops_eval_harness.py`.
   - Dependencies: none.
   - Acceptance Criteria: harness emits machine-comparable baseline with pass/fail diffs.
   - Validation: fixture-based test with expected diff object and deterministic JSON schema check.

## Sprint 2: Performance and Throughput Hardening

Goal: remove repeated per-query PromptOps initialization and bound request-time overhead.

Demo/Validation Checklist:

- [x] Prompt bundle and plugin registry are cached safely and reused. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:133:bd7cb6461c5b5597`, evidence: `tests/test_promptops_layer.py`, `autocapture/promptops/service.py`)
- [x] Query p50/p95 latency improvement is measurable versus sprint-1 baseline. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:134:604f62d6fd64d304`, evidence: `artifacts/perf/gate_promptops_perf.json`)
- [x] No correctness regressions in golden eval set. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:135:79c63eab11aaf184`, evidence: `artifacts/advanced10/question_validation_plugin_trace_latest.json`)

Tasks:

1. Task: Introduce shared PromptOps service with cache lifecycle.
   - Inputs: repeated `PromptOpsLayer` instantiation in query and gateway paths.
   - Outputs: process-local service with cache invalidation on config hash, template hash, plugin manifest hash, and explicit refresh signal; degraded-mode telemetry when cache invalidates or fails.
   - Files: `autocapture/promptops/service.py` (new), `autocapture_nx/kernel/query.py`, `autocapture/gateway/router.py`, `autocapture/memory/answer_orchestrator.py`.
   - Dependencies: sprint-1 task 1.
   - Acceptance Criteria: no repeated bundle load for unchanged config within process lifecycle.
   - Validation: integration test counting bundle loads across multiple queries plus invalidation tests for each cache key.

2. Task: Add bounded async queueing for review/eval side-work.
   - Inputs: synchronous review work in PromptOps path.
   - Outputs: non-blocking side channel with backpressure and fail-closed behavior.
   - Files: `autocapture/promptops/engine.py`, `autocapture/promptops/review_worker.py` (new), `tests/test_promptops_layer.py`.
   - Dependencies: task 1.
   - Acceptance Criteria: query response path remains bounded even when review backend is slow/unavailable.
   - Validation: timeout simulation tests with strict max-latency assertions.

3. Task: Add performance regression gate for PromptOps.
   - Inputs: sprint-1 baseline metrics.
   - Outputs: benchmark script + CI threshold check for p95 and throughput.
   - Files: `tools/bench_promptops.py` (new), `docs/metrics/promptops_slo.md`, CI script file.
   - Dependencies: sprint-1 tasks 2-3.
   - Acceptance Criteria: automated fail on regression beyond configured threshold.
   - Validation: benchmark test mode with seeded deterministic inputs.

## Sprint 3: Accuracy and Citeability Upgrades

Goal: improve generic answer quality by strengthening transformation quality checks and evidence linkage.

Demo/Validation Checklist:

- [x] PromptOps strategy path is explicit per answer. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:169:0813d10d486b246c`, evidence: `docs/reports/question-validation-plugin-trace-2026-02-13.md`)
- [x] Each answer includes claim-to-evidence links or explicit indeterminate labels. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:170:5d98fa7f07d21a13`, evidence: `docs/reports/question-validation-plugin-trace-2026-02-13.md`)
- [x] Golden Q/H tests show improved correctness without tactical query-specific logic. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:171:41bad29f011910fa`, evidence: `artifacts/advanced10/question_validation_plugin_trace_latest.json`)

Tasks:

1. Task: Add strategy ledger for rewrite/rerank/fallback decisions.
   - Inputs: implicit strategy behavior in current PromptOps code.
   - Outputs: structured strategy trace record persisted per query.
   - Files: `autocapture/promptops/engine.py`, `autocapture_nx/kernel/query.py`, `autocapture/memory/answer_orchestrator.py`.
   - Dependencies: sprint-1 tasks 1-2.
   - Acceptance Criteria: every query has a strategy trace with stage outcome and confidence signal.
   - Validation: integration tests asserting trace completeness across success/fallback/error paths.

2. Task: Enforce citation-first answer contract.
   - Inputs: current answer assembly output and citation plugin behavior.
   - Outputs: answer contract requiring citations by default, with deterministic uncitable state.
   - Files: `autocapture/memory/answer_orchestrator.py`, `autocapture/promptops/evaluate.py`, `tests/test_query_eval_golden.py`.
   - Dependencies: task 1.
   - Acceptance Criteria: answer responses fail validation if uncited claims are returned without indeterminate state.
   - Validation: golden tests with known-citable and intentionally-uncitable cases.

3. Task: Expand generic eval corpus for question classes.
   - Inputs: existing Q/H suites and current fixture data.
   - Outputs: class-based fixtures for windows, focus state, timeline extraction, key-value form parsing, calendar/schedule parsing, chat transcript parsing, browser chrome parsing, color-aware console parsing, and cross-window attribution.
   - Files: `tests/fixtures/promptops_eval_cases.json`, `tests/fixtures/golden_questions_qh.json` (new/updated), `tools/run_advanced10_queries.py`.
   - Dependencies: none.
   - Acceptance Criteria: each question class has at least one canonical and one adversarial fixture with explicit class tags and expected rationale fields.
   - Validation: deterministic harness run producing class-level precision/recall summary and per-class confusion artifacts.

## Sprint 4: Security and Policy Hardening for External Model Interactions

Goal: make PromptOps-to-model interactions auditable, localhost-safe, and policy-gated while preserving full functionality.

Demo/Validation Checklist:

- [x] External endpoint policy is enforced fail-closed (localhost-only unless explicit policy override). (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:205:0477f17877582400`, evidence: `artifacts/promptops/gate_promptops_policy.json`)
- [x] Prompt history/metrics redaction policy is explicit and test-backed. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:206:0d3728709672fdde`, evidence: `config/default.json`, `tests/test_query_citations_required.py`)
- [x] Audit chain can reconstruct who/what/when for each prompt mutation and review decision. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:207:4a54f1bba6ddc70b`, evidence: `artifacts/promptops/gate_promptops_policy.json`)

Tasks:

1. Task: Harden endpoint policy and trust boundaries.
   - Inputs: current vLLM endpoint configuration and enforcement helpers.
   - Outputs: strict enforcement hooks with explicit deny reasons and audit entries.
   - Files: `autocapture_nx/inference/vllm_endpoint.py`, `autocapture/promptops/engine.py`, `tests/test_external_vllm_policy.py`.
   - Dependencies: none.
   - Acceptance Criteria: disallowed endpoint configs fail before any outbound attempt.
   - Validation: unit tests for allowed/denied combinations and error messages.

2. Task: Add sensitive-field controls for PromptOps artifacts.
   - Inputs: prompt history/metrics persistence behavior.
   - Outputs: configurable redaction/masking policy for promptops artifacts (for example keys: `api_key`, `auth_token`, `email_local_part`, `session_cookie`) without mutating raw local evidence store.
   - Files: `autocapture/promptops/engine.py`, `config/default.json`, `tests/test_promptops_layer.py`.
   - Dependencies: sprint-1 task 1.
   - Acceptance Criteria: configured sensitive keys never persist in clear text in promptops metrics/history outputs.
   - Validation: file-content tests with known sensitive tokens and whitelist-based artifact scanner in CI.

3. Task: Extend append-only audit linkage for PromptOps decisions.
   - Inputs: existing plugin audit log usage.
   - Outputs: chained audit records linking input query, transformed prompt, model interaction, and final answer metadata.
   - Files: `autocapture/promptops/engine.py`, audit utility module, `tests/test_promptops_template_diff.py`.
   - Dependencies: sprint-3 task 1.
   - Acceptance Criteria: a single query can be replayed from audit chain without ambiguity.
   - Validation: audit integrity tests including hash-chain continuity checks.

## Sprint 5: Golden Pipeline Stabilization and Operationalization

Goal: finalize a no-drift golden PromptOps profile with quality gates and operational playbooks.

Demo/Validation Checklist:

- [x] Golden profile executes all required plugins in the intended order. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:241:2d8fd7c0d6a9fb6e`, evidence: `config/profiles/golden_full.json`, `tests/test_golden_full_profile_lock.py`)
- [x] Q and H suites run in one command and emit confidence + contribution matrix. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:242:12f5e76375a2137e`, evidence: `artifacts/advanced10/question_validation_plugin_trace_latest.json`)
- [x] Roll-forward and rollback playbooks are documented and tested. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:243:0afe2b9d01c9870c`, evidence: `docs/runbooks/promptops_golden_ops.md`)

Tasks:

1. Task: Define immutable golden PromptOps profile.
   - Inputs: current profile/plugin config and strategy traces.
   - Outputs: versioned golden profile with hash-pinned prompt templates and plugin ordering.
   - Files: `config/profiles/golden_full_pipeline.json`, `docs/architecture/promptops_golden_profile.md`.
   - Dependencies: sprints 2-4.
   - Acceptance Criteria: profile hash and plugin manifest remain stable across runs unless version-bumped.
   - Validation: manifest hash test + profile contract test.

2. Task: Build plugin contribution report for each answer.
   - Inputs: strategy trace, metrics, answer/citation outputs.
   - Outputs: per-query plugin contribution table with confidence and elapsed time.
   - Files: `tools/query_latest_single.sh`, `tools/run_advanced10_queries.py`, reporting module.
   - Dependencies: sprint-3 task 1, sprint-1 task 2.
   - Acceptance Criteria: report clearly identifies plugins in-path vs out-of-path and confidence contribution.
   - Validation: snapshot tests on report format and deterministic content fields.

3. Task: Add operational docs and runbooks.
   - Inputs: finalized profile, telemetry, and failure modes.
   - Outputs: docs for startup checks, health checks, eval cadence, and incident recovery.
   - Files: `docs/runbooks/promptops_golden_ops.md`, `docs/implementation_matrix.md`.
   - Dependencies: all prior sprint outputs.
   - Acceptance Criteria: operator can run end-to-end verification with one documented command.
   - Validation: doc-driven dry run in CI smoke job.

## Sprint 6: Blueprint Contract Alignment and Plugin Safety Gates

Goal: align PromptOps plan deliverables with blueprint-level plugin contracts, safe mode constraints, and schema requirements.

Demo/Validation Checklist:

- [x] `screen.parse.v1`, `screen.index.v1`, and `screen.answer.v1` contract tasks are explicitly represented in implementation matrix with verification hooks. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:277:5d83dc7b952ca185`, evidence: `artifacts/phaseA/gate_screen_schema.json`, `docs/reports/implementation_matrix.md`)
- [x] UI graph/provenance schemas are versioned and validated in CI. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:278:b4efd0f3e1e4d0d8`, evidence: `artifacts/phaseA/gate_screen_schema.json`)
- [x] Plugin allowlist and safe-mode startup checks gate PromptOps-affecting changes. (row_key: `docs/plans/promptops-four-pillars-improvement-plan.md:279:dc2f79faf13db176`, evidence: `artifacts/promptops/gate_promptops_policy.json`)

Tasks:

1. Task: Add blueprint contract mapping tasks for screen plugin family.
   - Inputs: blueprint requirements and current plugin model docs.
   - Outputs: explicit implementation matrix rows for parse/index/answer contracts, with ownership and verification location.
   - Files: `docs/implementation_matrix.md`, `docs/codex_autocapture_prime_blueprint.md`.
   - Dependencies: sprint-5 task 1.
   - Acceptance Criteria: each required screen contract has status, owner, and test linkage.
   - Validation: matrix consistency test ensuring required contracts are not missing.

2. Task: Version and enforce UI graph/provenance schemas.
   - Inputs: extraction outputs and answer provenance requirements.
   - Outputs: schema files and validators for UI graph and provenance payloads.
   - Files: `docs/schemas/ui_graph.schema.json`, `docs/schemas/provenance.schema.json`, schema validation tests.
   - Dependencies: sprint-3 tasks 1-2.
   - Acceptance Criteria: all generated answer artifacts validate against both schemas.
   - Validation: CI schema validation job over fixture corpus and latest generated artifacts.

3. Task: Add plugin allowlist + safe-mode verification gates.
   - Inputs: plugin manifests and safe-mode constraints.
   - Outputs: CI gates that run plugin validation and safe-mode startup smoke tests when PromptOps/plugin files change.
   - Files: `docs/plugin_model.md`, `docs/safe_mode.md`, CI workflow file(s), validation scripts.
   - Dependencies: sprint-2 task 1, sprint-4 task 1.
   - Acceptance Criteria: pipeline fails if disallowed plugins are active or safe mode defaults drift.
   - Validation: deterministic CI checks with fixture configs for allowed/denied plugin sets.

## Testing Strategy

- Unit tests:
  - PromptOps rewriting/validation/evaluation functions.
  - Endpoint policy enforcement and history/metrics controls.
- Integration tests:
  - Query path from `run_query_without_state`/`run_state_query` through answer orchestration.
  - Strategy trace + citation contract + plugin contribution report generation.
- Golden tests:
  - Q/H suites for question-class coverage.
  - Deterministic drift checks on outputs, confidence, and citation completeness.
- Performance tests:
  - PromptOps p50/p95 latency and throughput budgets with regression gates.
- Security tests:
  - Fail-closed endpoint policy, audit-chain integrity, and sensitive-artifact assertions.
- Policy/safety gates:
  - Plugin allowlist validation and safe-mode startup smoke test on every PromptOps/plugin-affecting change.
  - UI graph + provenance schema validation for generated artifacts.

## Potential Risks and Gotchas

- Risk: over-caching stale prompt bundles after config updates.
  - Mitigation: cache keys must include config hash + template hash; add forced refresh path.
- Risk: asynchronous review queue hides critical failures.
  - Mitigation: explicit failure channel and surfaced degraded-mode state in query response metadata.
- Risk: confidence scores appear precise but are poorly calibrated.
  - Mitigation: track calibration error against labeled Q/H feedback, not only raw pass/fail.
- Risk: citation contract may reduce answer coverage on weak evidence cases.
  - Mitigation: explicit indeterminate outputs with best-effort retrieval diagnostics.
- Risk: metric/log growth impacts local disk and performance.
  - Mitigation: rotate archives with append-only migration and integrity checks (no deletion endpoints).

## Rollback Plan

1. Keep current PromptOps path behind feature flags for each sprint change.
2. If regressions occur, revert to last known-good golden profile hash and disable only affected new flags.
3. Preserve all generated metrics/audit artifacts for postmortem comparison.
4. Re-run golden and performance suites before re-enabling changes.

## Phase-0 Research Notes (PromptOps Snapshot)

- PromptOps is invoked in query and gateway paths but frequently instantiated per request.
- Evaluation currently emphasizes lightweight lexical checks; semantic grounding is underpowered.
- Metrics/history exist but need schema discipline and stronger contribution tracing.
- Endpoint security policy exists and should remain strict localhost-first with explicit fail-closed behavior.
