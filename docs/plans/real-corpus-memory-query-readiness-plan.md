# Plan: Real-Corpus Memory Query Readiness (Strict, Cited, No Shortcuts)

Generated: 2026-02-22
Estimated Complexity: High

## Overview
Shift readiness from synthetic-only correctness to real-corpus memory correctness:
- Stage1 proves per-frame normalized completeness before any reap-eligibility marker.
- Stage2+ operates only on normalized artifacts (raw-off outside Stage1).
- Query path is read-only and instant (schedule_extract=false always no compute).
- Strict gates use real captured corpus and real question sets as the release signal.

## Scope and Boundaries
In scope:
- Real-corpus strict correctness gates.
- Per-frame plugin completion and lineage proofs.
- Retrieval/query mapping against normalized typed records.
- Deterministic pass/fail reporting and mismatch triage.

Out of scope:
- New external data providers unrelated to captured corpus.
- Any query-time extraction or VLM fallback.

## Explicit Assumption Corrections (No Silent Assumptions)
1. Synthetic 40/40 is regression-only; it is not production readiness.
2. Stage1 complete is storage/reap readiness, not full question-answer readiness.
3. Plugin execution count alone does not prove evidence adequacy; field-level checks are required.
4. Indeterminate is correct only when evidence is absent; it is never a pass where an expected answer exists.
5. Real-corpus strict gates must be the final ship gate.

## Prerequisites
- Stable writable metadata DB view (or read replica) for deterministic evaluations.
- Existing Stage1 marker and UIA linkage paths available.
- Query harness can target specified run IDs/time windows.
- PromptOps/metrics artifacts writable under artifacts/ and docs/reports/.
- Real-corpus strict set locked at docs/contracts/real_corpus_expected_answers_v1.json.

## Skill Allocation by Section
- Sprint 0 (truth contract): plan-harder, config-matrix-validator.
  Why: lock exact success semantics and prevent metric ambiguity.
- Sprint 1 (evidence/lineage): evidence-trace-auditor, policygate-penetration-suite.
  Why: verify each answer has verifiable chain and raw-off is enforced.
- Sprint 2 (retrieval/queryability): golden-answer-harness, ccpm-debugging.
  Why: find real-corpus failures and root-cause retrieval/schema gaps.
- Sprint 3 (determinism/perf): deterministic-tests-marshal, perf-regression-gate, resource-budget-enforcer.
  Why: ensure strict gates are stable and query remains instant under load.
- Sprint 4 (soak/ops): audit-log-integrity-checker, observability-slo-broker.
  Why: prove overnight reliability and operational visibility.

## Sprint 0: Replace False Green Signals
Goal: Make real-corpus strict correctness the only release signal.
Demo/Validation:
- One report with synthetic plus real-corpus sections, where only real-corpus decides readiness.
- strict_semantics: evaluated exact count, skipped=0, failed=0 for real-corpus set.

### Task 0.0: Freeze Real-Corpus Strict Question Set (Blocking Source of Truth)
- Location: docs/contracts/real_corpus_expected_answers_v1.json, tests/test_real_corpus_expected_answers_contract.py
- Description:
  - lock question IDs and exact expected answers,
  - lock expected citation constraints,
  - add allow_indeterminate flags only where explicitly permitted,
  - include version metadata and content hash.
- Complexity: 5/10
- Dependencies: None
- Acceptance Criteria:
  - release gates load this file as the single source of truth,
  - no strict run may proceed without a valid locked corpus file.
- Validation:
  - schema and uniqueness tests.

### Task 0.1: Define Readiness Contract and Gate Priority
- Location: docs/contracts/real_corpus_query_readiness_contract.md
- Description:
  - Tier A blocking: real-corpus strict exact answers plus citation match.
  - Tier B blocking: Stage1 completeness plus retention marker validity.
  - Tier C non-blocking: synthetic regression confidence.
- Complexity: 4/10
- Dependencies: Task 0.0
- Acceptance Criteria:
  - synthetic pass cannot override a real-corpus strict fail.
- Validation:
  - contract lint and checklist script.

### Task 0.2: Add Unified Readiness Report Generator
- Location: tools/run_real_corpus_readiness.py, tests/test_run_real_corpus_readiness.py
- Description:
  - emit strict summary counters (evaluated, passed, failed, skipped),
  - emit mismatch inventory by question id and type,
  - emit citation integrity counts,
  - emit plugin completion coverage.
- Complexity: 6/10
- Dependencies: Task 0.1
- Acceptance Criteria:
  - deterministic machine-readable JSON report.
- Validation:
  - snapshot tests for schema and strict counters.

### Task 0.3: Wire Gate to Release Path
- Location: tools/release_gate.py, tools/gate_phase*.py, tests/test_release_gate_real_corpus_priority.py
- Description:
  - fail release if real-corpus strict fails, regardless of synthetic status.
- Complexity: 5/10
- Dependencies: Task 0.2
- Acceptance Criteria:
  - local and CI exit non-zero on any real-corpus strict miss.
- Validation:
  - precedence logic unit tests.

### Task 0.4: Standardize Artifact Paths and Naming
- Location: docs/runbooks/release_gate_ops.md, tools/run_real_corpus_readiness.py
- Description:
  - canonical outputs:
    - artifacts/real_corpus_gauntlet/<ts>/strict_matrix.json
    - artifacts/real_corpus_gauntlet/<ts>/query_results.json
    - artifacts/real_corpus_gauntlet/<ts>/metrics.json
    - docs/reports/real_corpus_strict_latest.md
- Complexity: 3/10
- Dependencies: Task 0.2
- Acceptance Criteria:
  - runbooks and gate logs reference the same artifact paths.
- Validation:
  - path consistency tests.

## Sprint 1: Per-Frame Completeness and Lineage Proof
Goal: Prove each frame marked reap-eligible is fully normalized for downstream memory use.
Demo/Validation:
- For sampled and full scans, each frame has complete chain:
  - evidence.capture.frame
  - obs.uia.* (when uia_ref exists)
  - derived.ingest.stage1.complete
  - retention.eligible (only when valid)

### Task 1.1: Expand Stage1 Completeness Auditor to Plugin Matrix
- Location: tools/soak/stage1_completeness_audit.py, tests/test_stage1_completeness_audit_tool.py
- Description:
  - add per-plugin required and observed fields, not just record presence,
  - validate bbox numerics, linkage fields, deterministic ids, timestamp coherence.
- Complexity: 7/10
- Dependencies: Sprint 0
- Acceptance Criteria:
  - auditor reports missing fields by plugin and frame id.
- Validation:
  - fixture tests with targeted missing-field failures.

### Task 1.2: Retention Marker Hard Gate on Completeness
- Location: autocapture/storage/stage1.py, autocapture_nx/ux/facade.py, tests/test_storage_retention.py, tests/test_trace_facade.py
- Description:
  - retention.eligible only emitted after full contract pass,
  - include reason codes when blocked.
- Complexity: 6/10
- Dependencies: Task 1.1
- Acceptance Criteria:
  - zero false-positive retention markers.
- Validation:
  - strict tests on incomplete and complete chains.

### Task 1.3: Real-Corpus Lineage Sampler Artifacts
- Location: tools/validate_stage1_lineage.py, docs/reports/real_corpus_lineage_latest.md
- Description:
  - export deterministic lineage examples and issue buckets for operator review.
- Complexity: 4/10
- Dependencies: Task 1.1
- Acceptance Criteria:
  - at least 3 end-to-end lineage exemplars and full issue histogram.
- Validation:
  - tool tests plus artifact generation check.

## Sprint 2: Queryability from Normalized Corpus (No Raw, No On-Demand Compute)
Goal: Make real memory questions answerable from normalized records only.
Demo/Validation:
- query runner returns exact answer plus citations for expected-answer items,
- schedule_extract=false never triggers processing.

### Task 2.1: Build Queryability Coverage Matrix by Question Type
- Location: tools/query_eval_suite.py, tools/query_effectiveness_report.py, docs/reports/queryability_coverage_matrix.md
- Description:
  - map each question type to required normalized signals and retrieval paths.
- Complexity: 6/10
- Dependencies: Sprint 1
- Acceptance Criteria:
  - every strict question has an explicit required-signal checklist.
- Validation:
  - report test ensures no unmapped strict question.

### Task 2.2: Fix Retrieval and Ranking Gaps for Missing Strict Answers
- Location: autocapture/query/*, autocapture_nx/kernel/query.py, tests/test_query_*
- Description:
  - for each failing strict question, identify missing record/field/retrieval rule,
  - implement smallest deterministic fix,
  - add regression test with exact expectation.
- Complexity: 8/10
- Dependencies: Task 2.1
- Acceptance Criteria:
  - fail bucket shrinks monotonically to zero for strict expected-answer set.
- Validation:
  - per-failure regression tests.

### Task 2.3: Enforce Query Contract (Read-Only, Instant)
- Location: autocapture/web/routes/query.py, autocapture_nx/ux/facade.py, tests/test_schedule_extract_from_query.py, tests/test_query_arbitration.py
- Description:
  - assert no extraction scheduling,
  - assert no raw media access,
  - return deterministic not-available-yet when corpus lacks evidence.
- Complexity: 5/10
- Dependencies: Task 2.2
- Acceptance Criteria:
  - query_extractor_launch_total == 0 during strict runs,
  - query_schedule_extract_requests_total == 0 on user query route,
  - query_raw_media_reads_total == 0,
  - query p95 latency <= 1500 ms on warm cache for strict suite.
- Validation:
  - contract tests and instrumentation threshold assertions.

## Sprint 3: Determinism, Throughput, and Budget Discipline
Goal: Ensure correctness remains stable under repeated runs and nightly batch load.
Demo/Validation:
- repeated real-corpus strict runs produce identical strict outcome and mismatch signatures,
- Stage1 and Stage2+ respect configured budgets.

### Task 3.1: Determinism Gate for Real-Corpus Strict Set
- Location: tools/gate_real_corpus_determinism.py, tests/test_gate_real_corpus_determinism.py
- Description:
  - run strict suite N times and compare signatures and counters.
- Complexity: 6/10
- Dependencies: Sprint 2
- Acceptance Criteria:
  - zero drift on strict counters and failed-id lists.
- Validation:
  - determinism gate tests.

### Task 3.2: Query Perf and Batch Throughput Regression Gates
- Location: tools/gate_promptops_perf.py, tools/bench_batch_knobs_synthetic.py, tests/test_bench_batch_knobs_synthetic.py
- Description:
  - track p50 and p95 query latency,
  - track throughput records per second,
  - track projected lag hours and retention risk trend.
- Complexity: 7/10
- Dependencies: Task 3.1
- Acceptance Criteria:
  - query p95 regression <= 10 percent vs locked baseline,
  - throughput regression <= 10 percent vs locked baseline,
  - projected_lag_hours < 144 (below 6-day retention horizon).
- Validation:
  - perf gate local and CI checks.

### Task 3.3: Idle Budget Enforcement Under Soak
- Location: tools/run_non_vlm_readiness.py, tools/soak/*, tests/test_concurrency_budget_enforced.py
- Description:
  - validate Stage1 and Stage2 loop stays inside CPU and RAM budget while processing backlog.
- Complexity: 6/10
- Dependencies: Task 3.2
- Acceptance Criteria:
  - no sustained budget violations,
  - logs show bounded queue behavior.
- Validation:
  - soak report plus budget test suite.

## Sprint 4: Operational Closure and Proof Bundle
Goal: Produce unambiguous proof that the system is a reliable memory over real captured data.
Demo/Validation:
- one proof bundle path with strict status, lineage, metrics, and risk posture.

### Task 4.1: Real-Corpus Strict Gauntlet Bundle
- Location: artifacts/real_corpus_gauntlet/<timestamp>/, docs/reports/real_corpus_strict_latest.md
- Description:
  - publish strict matrix with failures resolved to zero for expected-answer set.
- Complexity: 5/10
- Dependencies: Sprint 3
- Acceptance Criteria:
  - evaluated equals expected_total_from_contract,
  - skipped equals 0,
  - failed equals 0,
  - all measured on real_corpus_expected_answers_v1.
- Validation:
  - gate summary and signed artifact hashes.

### Task 4.2: Citation Integrity and Audit Chain Verification
- Location: tools/gate_ledger.py, tools/gate_canon.py, tests/test_ledger_anchor_golden.py
- Description:
  - verify every strict answer has valid citation references and ledger integrity.
- Complexity: 4/10
- Dependencies: Task 4.1
- Acceptance Criteria:
  - zero uncited strict answers unless explicitly expected indeterminate.
- Validation:
  - evidence audit report plus ledger gate pass.

### Task 4.3: Runbook and Operator Dashboard Refresh
- Location: docs/runbooks/release_gate_ops.md, docs/runbooks/promptops_golden_ops.md, docs/reports/non_vlm_readiness_latest.json
- Description:
  - update runbooks to match real-corpus-first release policy and on-call triage flow.
- Complexity: 3/10
- Dependencies: Task 4.2
- Acceptance Criteria:
  - operator can run full readiness with one command and interpret failures by category.
- Validation:
  - dry-run operator checklist.

## Testing Strategy
- Unit tests for each new gate, parser, and mapping rule.
- Integration tests for Stage1 completeness, retention gating, and query contract.
- Determinism tests across repeated runs.
- Real-corpus strict gauntlet as blocking release criterion.
- Synthetic Q40 retained as regression-only non-release metric.

## Metrics and Exit Criteria
- Strict real-corpus: failed=0, skipped=0, evaluated=expected_total_from_contract.
- Stage1 marker integrity: zero retention.eligible where completeness=false.
- Citation integrity: zero uncited strict answers.
- Performance: query p95 <= 1500 ms and <=10 percent baseline regression; projected lag < retention horizon.
- Stability: determinism signatures match across N runs.

## Potential Risks and Gotchas
- DB write contention can produce non-deterministic snapshots.
  Mitigation: use stable read view or replica for gates.
- Questions requiring facts absent from captured corpus.
  Mitigation: classify as expected-indeterminate only when explicitly marked.
- Plugin present but weak payload failures.
  Mitigation: field-level quality assertions, not record-count-only.
- Regressions masked by synthetic fixtures.
  Mitigation: real-corpus-first gate precedence.

## Rollback Plan
- Keep new behavior behind gate/config toggles where practical.
- Keep prior gate scripts available for comparison during transition.
- If strict gate blocks operations unexpectedly, switch to read-only diagnostics mode, patch failures, then re-enable blocking mode.

## One-Round Clarifying Questions
1. Confirm generic/no-expected questions stay non-blocking informational metrics (recommended: yes).
2. Confirm nightly determinism repeats for blocking release gate (recommended: N=5).
