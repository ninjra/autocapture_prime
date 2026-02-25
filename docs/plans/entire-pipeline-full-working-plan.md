# Plan: Entire Pipeline Full Working

**Generated**: 2026-02-25  
**Estimated Complexity**: High

## Overview
Make the full `autocapture_prime` golden pipeline production-ready so it can answer natural-language questions from normalized corpus data with strict correctness, deterministic behavior, and verifiable citations.

This plan optimizes jointly for the 4 pillars:
- Performance: sustained throughput and bounded query latency.
- Accuracy: strict answer exactness against contract cases.
- Security: fail-closed capability and policy boundaries.
- Citeability: claim-level evidence lineage in every `state=ok` answer.

Current measured baseline (from latest local artifacts):
- `popup_strict`: 10/10 accepted.
- `real_corpus_strict`: 20 evaluated, 17 failed.
- Metadata coverage gap: `derived.ingest.stage1.complete=8791` vs `derived.ingest.stage2.complete=661`.
- Extraction gap: `derived.text.ocr=3`, `derived.text.vlm=0`, `derived.sst.text.extra=1473`.

## Clarified Requirements and Assumptions
- Canonical path is one golden pipeline end-to-end; no alternate query behavior branches.
- Query path is normalized-only (no raw media reads at query time, no extraction on query).
- Raw data can be reaped after Stage1 only when Stage1 contract is truly complete.
- Hypervisor popup is UI ingress; this repo is source of knowledge and processing.
- Service outages must degrade deterministically, not silently pass.

## Skills Map (Used and Why)
- `plan-harder`, `planner`: phased, dependency-aware sprint plan with atomic tasks.
- `ccpm-debugging`: root-cause-first blocker loops (DB churn, extraction stalls, capability gaps).
- `config-matrix-validator`: plugin/config/default profile correctness gates.
- `deterministic-tests-marshal`: repeated-run stability and flake prevention.
- `golden-answer-harness`: strict Q40 + Temporal40 + popup regression enforcement.
- `evidence-trace-auditor`: citation lineage and claim-evidence alignment gates.
- `resource-budget-enforcer`: idle/active CPU/RAM behavior and throughput budget checks.
- `policygate-penetration-suite`, `security-best-practices`: untrusted plugin input hardening.
- `python-testing-patterns`, `testing`: deterministic unit/integration/e2e test coverage.
- `observability-slo-broker`, `python-observability`: metrics + SLO artifacts per run.
- `shell-lint-ps-wsl`: operator command hygiene and reproducibility.

## Prerequisites
- Canonical runtime paths configured:
  - `AUTOCAPTURE_DATA_DIR=/mnt/d/autocapture`
  - `AUTOCAPTURE_CONFIG_DIR=/mnt/d/autocapture/config_wsl`
- Localhost services reachable when required by a sprint.
- Synthetic corpus fixtures available for service-down validation.
- No raw-query fallback policy enforced.
- No local deletion policy preserved (retention signaling only).

## Sprint 1: Freeze Contracts and Baseline Truth
**Goal**: Lock acceptance contracts and produce one authoritative baseline artifact set.  
**Skills**: `plan-harder`, `config-matrix-validator`, `observability-slo-broker`  
**Demo/Validation**:
- One baseline bundle with strict counters, plugin matrix, and cause taxonomy.
- No ambiguous pass/fail labels.

### Task 1.1: Contract lock and canonical acceptance matrix
- **Location**: `docs/contracts/*.json`, `tools/release_gate.py`, `tools/gate_golden_pipeline_triplet.py`
- **Description**: Freeze strict contracts for popup/Q40/Temporal40/real-corpus and enforce one composite release gate.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Contract hashes recorded.
  - Composite gate fails closed on stale or missing artifacts.
- **Validation**:
  - `tests/test_release_gate.py`
  - `tests/test_gate_golden_pipeline_triplet.py`

### Task 1.2: Baseline metrics snapshot
- **Location**: `artifacts/release/*`, `artifacts/real_corpus_gauntlet/latest/*`, `artifacts/query_acceptance/*`
- **Description**: Produce baseline JSON snapshot containing strict counters, failure cause counts, stage coverage, and latency stats.
- **Complexity**: 3
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Snapshot includes stage1/stage2 coverage and failure by cause.
- **Validation**:
  - Deterministic rerun produces same schema and stable key set.

## Sprint 2: Stage1 Completeness and Reap-Safe Gate
**Goal**: Guarantee Stage1 completeness is real before retention eligibility.  
**Skills**: `evidence-trace-auditor`, `resource-budget-enforcer`, `python-testing-patterns`  
**Demo/Validation**:
- Every retention marker is contract-backed.
- No false-positive stage1 complete markers.
- Stage2 optimization work is blocked until Stage1 contract gate is green.

### Task 2.1: Stage1 completeness contract checker
- **Location**: `autocapture/storage/stage1.py`, `autocapture_nx/processing/idle.py`, `tools/gate_stage1_contract.py` (new)
- **Description**: Define/validate required Stage1 artifacts per frame (frame record, linkage, required normalized fields, marker integrity).
- **Complexity**: 6
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - `retention.eligible` only when Stage1 contract passes.
- **Validation**:
  - Unit tests for partial vs complete stage1 records.

### Task 2.2: Stage1/retention lineage proof
- **Location**: `tools/lineage_sample_report.py` (new), `artifacts/lineage/*`
- **Description**: Emit deterministic lineage samples:
  - frame -> stage1_complete -> retention.eligible
  - frame + uia_ref -> obs.uia.* -> stage1_complete
- **Complexity**: 5
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - At least 3 lineage examples always generated on demand.
- **Validation**:
  - Integration test verifies IDs and linkage fields.

### Task 2.3: Stage1 contract gate as Stage2 prerequisite
- **Location**: `tools/gate_stage1_contract.py`, `tools/release_gate.py`
- **Description**: Add explicit release-gate step that must pass before Stage2 throughput/coverage sprints run in promoted workflows.
- **Complexity**: 4
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Stage2 soak/optimization workflows fail fast when Stage1 contract gate is red.
- **Validation**:
  - Release gate tests for gate ordering and fail-fast behavior.

## Sprint 3: Stage2 Throughput and Coverage Lift
**Goal**: Raise Stage2 completion and extracted-text coverage to query-usable scale.  
**Skills**: `ccpm-debugging`, `resource-budget-enforcer`, `python-observability`  
**Demo/Validation**:
- Stage2 completion ratio increases monotonically during drains.
- `derived.text.ocr` and structured `adv.*` evidence rise materially.

### Task 3.1: Manual drain mode correctness and safety
- **Location**: `autocapture_nx/runtime/batch.py`, `tests/test_runtime_batch_adaptive_parallelism.py`
- **Description**: Keep `--no-require-idle` path deterministic and budgeted for operator-driven backlog drains.
- **Complexity**: 4
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - No `active_user` hard block when explicit non-idle drain is requested.
- **Validation**:
  - Deterministic batch runtime tests.

### Task 3.2: Extraction throughput tuning without raw-query coupling
- **Location**: `autocapture_nx/processing/idle.py`, `config/default.json`, `/mnt/d/autocapture/config_wsl/user.json`
- **Description**: Tune idle extraction batching, provider concurrency, and per-loop budget behavior to increase Stage2 yields.
- **Complexity**: 8
- **Dependencies**: Task 3.1, Task 2.3
- **Acceptance Criteria**:
  - Stage2 complete growth trend is positive across soak window.
  - No CPU/RAM budget violation in idle mode.
- **Validation**:
  - `tools/run_golden_triplet_soak.py`
  - resource budget gate artifacts.

### Task 3.3: Structured advanced evidence generation audit
- **Location**: `plugins/builtin/observation_graph/plugin.py`, `autocapture_nx/kernel/query.py`, `tools/audit_q40_answer_quality.py`
- **Description**: Ensure missing advanced records are surfaced as plugin-execution gaps and repaired by extraction coverage, not masked by fallback summaries.
- **Complexity**: 8
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Failing advanced cases map to concrete missing derived keys or doc kinds.
- **Validation**:
  - Automated mismatch report with top missing keys/doc kinds.

### Task 3.4: Synthetic parity lane for service-down progress
- **Location**: `tools/run_q40_uia_synthetic.sh`, `tools/run_golden_triplet_soak.py`, `artifacts/synthetic_*`
- **Description**: Keep deterministic synthetic replay lane active so strict gates continue yielding actionable diagnostics when external services are unstable.
- **Complexity**: 5
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Synthetic artifacts are clearly labeled and never promoted as real-corpus pass evidence.
  - Soak output records `source_tier=synthetic|real`.
- **Validation**:
  - Soak tests validating fallback behavior and artifact provenance.

## Sprint 4: Plugin Stack Full Enablement (Non-8000 first)
**Goal**: All required non-VLM plugins are enabled, allowlisted, loadable, and verified functional.  
**Skills**: `config-matrix-validator`, `policygate-penetration-suite`, `testing`  
**Demo/Validation**:
- Plugin gate reports `failed_count=0` against required canonical set.

### Task 4.1: Canonical plugin inventory + allowlist enforcement
- **Location**: `config/default.json`, `tools/gate_plugin_enablement.py`, `docs/contracts/plugin_inventory_contract.json`
- **Description**: Validate every required plugin across allowlist/hash/enabled/load/capability checks.
- **Complexity**: 7
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - No required plugin unresolved or silently disabled.
- **Validation**:
  - plugin enablement gate tests and runtime snapshot.

### Task 4.2: Default profile consistency checks
- **Location**: `config/profiles/*`, `tests/test_stage1_no_vlm_profile.py`, `tests/test_release_gate*.py`
- **Description**: Enforce profile behavior by mode:
  - stage1 profile
  - stage2 non-vlm
  - full-service profile
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - No profile drift that changes query contract unexpectedly.
- **Validation**:
  - config matrix and profile regression tests.

## Sprint 5: Query Path Canonicalization and PromptOps Path
**Goal**: Single deterministic query path from popup ingress to corpus-backed answer synthesis.  
**Skills**: `ccpm-debugging`, `evidence-trace-auditor`, `python-testing-patterns`  
**Demo/Validation**:
- `schedule_extract=false` query path is instant and compute-free.
- Missing capability returns explicit structured error fast.

### Task 5.1: Canonical query path assertion
- **Location**: `autocapture_nx/ux/facade.py`, `autocapture_nx/kernel/query.py`, `tools/verify_query_upstream_runtime_contract.py`
- **Description**: Ensure read-only query runtime includes required capabilities and one orchestrator route.
- **Complexity**: 7
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - No crash-on-boot-failure; deterministic error payload instead.
  - `schedule_extract=false` path triggers no extraction and no raw-media reads.
  - Query path returns deterministic `not_available_yet` style response when normalized evidence is missing.
- **Validation**:
  - query runtime contract tests and popup regression tests.
  - query contract counter tests (`query_raw_media_reads_total=0`, `query_schedule_extract_requests_total=0`).

### Task 5.2: PromptOps envelopes and context injection contract
- **Location**: `promptops/*`, query upstream integration glue, `docs/runbooks/promptops_golden_ops.md`
- **Description**: Define deterministic pre/post context envelopes for 8000-bound requests while preserving strict no-fabrication and citation requirements.
- **Complexity**: 7
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Envelope schema logged and reproducible for identical inputs.
- **Validation**:
  - promptops policy/perf gates and sampled transcript checks.

## Sprint 6: Citation and Claim-Evidence Integrity
**Goal**: Every `state=ok` answer has valid citation linkage to normalized records.  
**Skills**: `evidence-trace-auditor`, `source-quality-linter`, `golden-answer-harness`  
**Demo/Validation**:
- Strict gate rejects answers with missing or invalid citation linkage.

### Task 6.1: Citation linkage hard gate
- **Location**: `tools/run_real_corpus_readiness.py`, `tools/gate_real_corpus_strict.py`, `autocapture_nx/kernel/query.py`
- **Description**: Convert citation linkage warnings into strict failures for required suites.
- **Complexity**: 6
- **Dependencies**: Sprint 5
- **Acceptance Criteria**:
  - `citation_invalid` failures can only pass after linkage is fixed.
- **Validation**:
  - Unit tests for malformed and missing citation entries.

### Task 6.2: Claim-evidence alignment sampler
- **Location**: `tools/audit_q40_answer_quality.py`, `tools/report_q40_uia_mismatches.py`
- **Description**: Sample answers and verify expected claims appear in cited evidence.
- **Complexity**: 5
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Output includes exact question text, exact answer text, citation refs, mismatch reason.
- **Validation**:
  - Deterministic report output tests.

## Sprint 7: Strict Gauntlet Closure and Soak
**Goal**: Close strict gates and prove stable operation under soak.  
**Skills**: `golden-answer-harness`, `deterministic-tests-marshal`, `perf-regression-gate`, `resource-budget-enforcer`  
**Demo/Validation**:
- Repeated strict gate passes and stable soak metrics.

### Task 7.1: Strict triplet pass criteria
- **Location**: `tools/run_golden_triplet_soak.py`, `tools/gate_golden_pipeline_triplet.py`, `artifacts/release/*`
- **Description**: Require consecutive pass windows for popup/Q40/Temporal40 and fail fast on regression.
- **Complexity**: 5
- **Dependencies**: Sprint 6
- **Acceptance Criteria**:
  - Target: popup 10/10, Q40 40/40 (0 skip/0 fail), Temporal40 40/40 (0 skip/0 fail).
- **Validation**:
  - Soak summary artifacts with pass streak counters.

### Task 7.2: Real-corpus strict closure
- **Location**: `tools/run_real_corpus_readiness.py`, `tools/gate_real_corpus_strict.py`, `artifacts/real_corpus_gauntlet/latest/*`
- **Description**: Drive strict failures to zero with cause-by-cause remediation.
- **Complexity**: 9
- **Dependencies**: Task 7.1
- **Acceptance Criteria**:
  - `matrix_failed=0` and `ok=true` for real-corpus strict suite.
- **Validation**:
  - Consecutive reruns without cause drift.

## Sprint 8: Operationalization and Handoff
**Goal**: Make operations reproducible for nightly runs and incident triage.  
**Skills**: `observability-engineer`, `python-observability`, `shell-lint-ps-wsl`  
**Demo/Validation**:
- Runbooks and one-command checks for operators.

### Task 8.1: Operator runbook and one-line checks
- **Location**: `docs/runbooks/*`, `tools/*_health*.py`, `REPO_TOC.md`
- **Description**: Provide short one-line commands for:
  - service health
  - stage coverage
  - strict gate status
  - top failure reason extraction
- **Complexity**: 4
- **Dependencies**: Sprint 7
- **Acceptance Criteria**:
  - Operator can determine pipeline state in < 2 minutes.
- **Validation**:
  - Dry-run runbook walkthrough artifact.

### Task 8.2: Release gate promotion criteria
- **Location**: `tools/release_gate.py`, `docs/reports/blueprint_items.md`
- **Description**: Make promotion contingent on strict triplet + real-corpus strict + coverage thresholds.
- **Complexity**: 5
- **Dependencies**: Task 8.1
- **Acceptance Criteria**:
  - No manual bypass for strict correctness gates in default promotion path.
  - Promotion fails if strict pass evidence is synthetic-only (`source_tier=synthetic` without real-corpus green evidence).
- **Validation**:
  - release gate test updates and sample pass/fail artifacts.

### Task 8.3: Synthetic-vs-real artifact isolation gate
- **Location**: `tools/release_gate.py`, `tools/gate_golden_pipeline_triplet.py`, `tests/test_release_gate.py`
- **Description**: Enforce that synthetic fallback artifacts are diagnostic-only and cannot satisfy real-corpus promotion gates.
- **Complexity**: 5
- **Dependencies**: Task 8.2
- **Acceptance Criteria**:
  - Real promotion requires real-corpus strict green artifacts.
  - Synthetic artifacts remain available for debugging but never counted as release pass criteria.
- **Validation**:
  - Regression tests covering mixed synthetic/real artifact scenarios.

## Testing Strategy
- Unit tests for each modified gate, parser, and contract evaluator.
- Integration tests for:
  - stage1 -> stage2 progression
  - query read-only contract behavior
  - citation linkage validity
- Determinism tests:
  - repeated gauntlet runs with stable pass/fail classification.
- Performance tests:
  - batch throughput and query latency under idle/active budgets.

## Potential Risks and Gotchas
- Stage2 backlog can appear to “process” while `records_completed=0` due missing completion semantics.
  - Mitigation: explicit stage2 completion counters and contract-driven completion definitions.
- Service-up can mask retrieval defects if strict gates only check transport health.
  - Mitigation: separate transport health from answer-correctness gates.
- Sparse OCR output can make strict answers fail even when pipeline is “running”.
  - Mitigation: coverage thresholds on derived text/doc kinds before strict answer evaluation.
- Profile drift can re-enable forbidden query compute paths.
  - Mitigation: profile matrix tests and query contract counters in release gate.
- Metadata DB churn/instability can stall stage2 progression despite healthy services.
  - Mitigation: keep metadata guard telemetry, use deterministic fail reason tags, and maintain synthetic replay lane for non-blocked development.

## Rollback Plan
- Revert by sprint-sized commits only.
- Preserve current gate artifacts and baseline snapshots before each sprint merge.
- If regression appears in soak:
  - disable only newly introduced gate in env flag
  - keep prior strict gates active
  - restore previous known-good commit for affected sprint scope.

## Success Criteria (End State)
- Strict popup: `sample=10 accepted=10 failed=0`.
- Strict Q40: `evaluated=40 skipped=0 failed=0`.
- Strict Temporal40: `evaluated=40 skipped=0 failed=0`.
- Real-corpus strict: `matrix_failed=0`.
- Stage2 completion and derived evidence coverage sufficient for query correctness across corpus windows.
- All `state=ok` answers include valid citation lineage, with deterministic non-OK results when evidence is absent.
