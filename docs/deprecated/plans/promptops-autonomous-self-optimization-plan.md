# Plan: PromptOps Autonomous Self-Optimization

**Generated**: 2026-02-17  
**Estimated Complexity**: High

## Overview
Build PromptOps into a background, self-reviewing, self-growing subsystem that silently improves query quality for all downstream plugins/projects while enforcing hard safety/quality guardrails.  
The system must:
- Learn from run history, failures, and reviewer feedback.
- Split/merge query logic into known-good templates.
- Create new candidate templates from recent runs.
- Promote only proven winners and rollback losers automatically.
- Expose stable APIs so other repos/plugins can consume optimized prompts without owning PromptOps internals.

Assumptions used (no blockers):
- Local-first only, localhost model endpoints, no cloud dependency required for optimization loop.
- PromptOps runs continuously in background under runtime governor idle policies.
- Existing query feedback and promptops metrics artifacts remain source-of-truth inputs.

## Skill Plan (by section)

### Architecture & sequencing
- **Skill**: `plan-harder`
- **Why**: Dependency-ordered phased plan, atomic tasks, verifiable milestones.

### Evaluation and quality gates
- **Skill**: `python-testing-patterns`
- **Why**: Deterministic, reproducible acceptance tests for prompt evolution and template routing.

### Silent background operations and telemetry
- **Skill**: `logging-best-practices`
- **Why**: Structured, low-noise metrics/events to audit autonomous changes without user interruption.

### Reliability and drift control
- **Skill**: `golden-answer-harness`
- **Why**: Prevent regressions with explicit winner/loser prompt promotion gates.

### Prompt evidence and provenance correctness
- **Skill**: `evidence-trace-auditor`
- **Why**: Ensure answer improvements remain grounded and citable.

### Runtime and policy invariants
- **Skill**: `config-matrix-validator`
- **Why**: Validate behavior across profile variants and ensure safe defaults for all consumers.

## Prerequisites
- Existing PromptOps modules:
  - `autocapture/promptops/engine.py`
  - `autocapture/promptops/service.py`
  - `autocapture/promptops/{propose,validate,evaluate}.py`
- Existing metrics and feedback stores:
  - `data/promptops/metrics.jsonl`
  - `data/facts/query_feedback.ndjson`
  - `data/facts/query_trace.ndjson`
- Existing quality/eval entrypoints:
  - `tools/promptops_metrics_report.py`
  - `tools/query_effectiveness_report.py`
  - `tools/run_advanced10_queries.py`

## Sprint 1: PromptOps Safety Foundation
**Goal**: Stop unsafe prompt drift and establish strict prompt artifact governance.  
**Demo/Validation**:
- PromptOps cannot persist malformed/unsafe prompts.
- Prompt files remain semantically scoped (no query-overwrite corruption).

### Task 1.1: Add prompt artifact schema + guardrail validator
- **Location**: `autocapture/promptops/validate.py`, `tests/test_promptops_validation.py`
- **Description**: Introduce strict schema checks:
  - forbid `<think>` and chain-of-thought fragments
  - enforce prompt-id scope invariants (e.g., `query` prompt must remain generic)
  - block degenerate single-example overwrite patterns
- **Complexity**: 6
- **Dependencies**: None
- **Acceptance Criteria**:
  - Unsafe prompt candidate rejected with reason codes.
  - `query`/`state_query` cannot be replaced with one test question.
- **Validation**:
  - New deterministic tests for each reject rule.

### Task 1.2: Add prompt manifest and semantic contract checks
- **Location**: `promptops/prompts/*.txt`, `autocapture/promptops/engine.py`, `tests/test_promptops_template_diff.py`
- **Description**: Add manifest metadata (scope, intent class, constraints) and enforce it before apply.
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - apply path requires manifest-compatible rewrite.
  - mismatched-scope rewrites are rejected and logged.
- **Validation**:
  - tests that inject wrong-scope candidates and assert non-apply.

### Task 1.3: Add immutable baseline snapshots + rollback pointer
- **Location**: `data/promptops/` management logic in `autocapture/promptops/engine.py`
- **Description**: Snapshot winning prompt set and maintain automatic rollback pointer.
- **Complexity**: 5
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - each promotion creates versioned snapshot.
  - rollback can restore previous baseline atomically.
- **Validation**:
  - tests simulating failed promotion -> automatic rollback.

## Sprint 2: Real Evaluation Engine (No More Trivial Passes)
**Goal**: Replace weak evaluation with robust scoring tied to real outcomes.  
**Demo/Validation**:
- Prompt candidates are scored on meaningful criteria, not empty-example pass.

### Task 2.1: Redesign prompt evaluation model
- **Location**: `autocapture/promptops/evaluate.py`, `tests/test_promptops_eval_harness.py`
- **Description**: Introduce composite score:
  - parse validity
  - schema compliance
  - grounding/citation coverage
  - task success proxy from recent query outcomes
  - latency budget penalty
- **Complexity**: 8
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - empty example list never yields blind pass.
  - candidate requires minimum support window and confidence interval.
- **Validation**:
  - statistical tests with synthetic good/bad candidates.

### Task 2.2: Build prompt challenge set generation pipeline
- **Location**: `tools/promptops_eval.py`, `tools/query_effectiveness_report.py`, `docs/query_eval_cases_*.json`
- **Description**: Auto-build eval sets from:
  - failed queries
  - low-confidence runs
  - user feedback disagreement rows
  - known golden Q/H/generic suites
- **Complexity**: 7
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - every prompt-id has non-empty challenge set before promotion.
  - challenge set is versioned and reproducible.
- **Validation**:
  - test verifies deterministic challenge set generation from fixture logs.

### Task 2.3: Add promotion gate with canary threshold
- **Location**: `autocapture/promptops/engine.py`, `tools/gate_promptops_perf.py`, `tools/gate_promptops_policy.py`
- **Description**: Candidate apply requires:
  - quality delta > threshold
  - no policy violations
  - no latency regression beyond budget
- **Complexity**: 6
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - bad candidate remains in review state; not applied.
  - winner candidate auto-promotes and snapshots.
- **Validation**:
  - integration test for fail/accept branches.

## Sprint 3: Autonomous Learning Loop
**Goal**: PromptOps silently proposes, evaluates, and curates prompts in background.  
**Demo/Validation**:
- Idle background loop runs without user interaction and updates only safe winners.

### Task 3.1: Add promptops optimizer worker
- **Location**: `autocapture/promptops/optimizer.py` (new), scheduler wiring in `autocapture_nx/runtime/*`
- **Description**: Periodic idle worker:
  - consumes fresh metrics/feedback
  - identifies weak prompt-ids
  - generates candidates via rule/model strategies
  - submits to evaluation gate
- **Complexity**: 8
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - worker respects idle/governor constraints.
  - no foreground interference.
- **Validation**:
  - tests for active-user block and idle-run execution.

### Task 3.2: Multi-strategy candidate generation
- **Location**: `autocapture/promptops/propose.py`, `promptops/prompts/*`, `tests/test_promptops_layer.py`
- **Description**: Add strategies:
  - structural rewrite templates by task class
  - compression/expansion templates
  - evidence-contract hardening templates
  - model-assisted rewrite with strict post-validation
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - candidate bank includes multiple variants per prompt-id.
  - each variant tagged with generation provenance.
- **Validation**:
  - tests assert strategy tags and deterministic fallback behavior.

### Task 3.3: Online bandit/ranking selector
- **Location**: `autocapture/promptops/service.py`, `autocapture/promptops/engine.py`
- **Description**: Serve top prompt by contextual score (task type + confidence + latency).
- **Complexity**: 7
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - selector chooses stable winner under same context.
  - exploration rate bounded and auditable.
- **Validation**:
  - deterministic tests for ranking and tie-break rules.

## Sprint 4: Query Split/Merge Intelligence
**Goal**: Automatically decompose complex queries and recompose answers using known-good templates.  
**Demo/Validation**:
- Hard multi-part queries route into composed sub-prompts and improve success rate.

### Task 4.1: Add query intent decomposition graph
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture/promptops/decompose.py` (new)
- **Description**: classify query into intent graph:
  - extraction
  - counting
  - timeline
  - cross-window relation
  - structured KV extraction
- **Complexity**: 8
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - decomposition output deterministic for same input.
  - each node maps to prompt-id family.
- **Validation**:
  - tests on Q/H/generic examples with stable decomposition snapshots.

### Task 4.2: Add split-execute-merge orchestration
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture/promptops/merge.py` (new)
- **Description**: execute sub-prompts, merge with evidence alignment, resolve conflicts.
- **Complexity**: 8
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - merged answer includes per-subquery provenance and confidence.
  - conflict resolution rules deterministic.
- **Validation**:
  - tests for merge correctness and evidence consistency.

### Task 4.3: Learn new templates from stable successful runs
- **Location**: `autocapture/promptops/library_builder.py` (new), `promptops/prompts/generated/`
- **Description**: mine high-performing prompt traces, abstract into reusable templates.
- **Complexity**: 7
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - generated templates pass schema/quality gates before library insertion.
  - template lineage stored.
- **Validation**:
  - tests for dedup, lineage, and quality gate enforcement.

## Sprint 5: Cross-Plugin and Cross-Project PromptOps API
**Goal**: Make PromptOps optimization consumable by other plugins/projects with zero extra thinking.  
**Demo/Validation**:
- External callers use stable API and get optimized prompts transparently.

### Task 5.1: Introduce promptops contract API
- **Location**: `autocapture/promptops/api.py` (new), `autocapture/promptops/service.py`
- **Description**: provide stable methods:
  - `prepare(task_class, raw_prompt, context)`
  - `record_outcome(...)`
  - `recommend_template(...)`
- **Complexity**: 6
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - API versioned and backward-compatible.
  - no direct file-level prompt mutation by consumers.
- **Validation**:
  - contract tests for API surface.

### Task 5.2: Route internal plugins through contract API
- **Location**: `autocapture_nx/kernel/query.py`, VLM/OCR integration call sites
- **Description**: remove ad-hoc prompt handling and unify through promptops API.
- **Complexity**: 6
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - all query-class prompt flows emit unified metrics.
  - no bypass paths for optimizable prompts.
- **Validation**:
  - integration tests asserting promptops_used=true on covered routes.

### Task 5.3: Add external project handoff contract doc
- **Location**: `docs/promptops_contract.md` (new)
- **Description**: document usage contract for sibling repos/plugins.
- **Complexity**: 4
- **Dependencies**: Task 5.2
- **Acceptance Criteria**:
  - clear inputs/outputs/SLA and failure behavior.
- **Validation**:
  - contract examples parse and run in test harness.

## Sprint 6: Silent Operations, Metrics, and Release Gate
**Goal**: Keep optimization invisible during normal use and fully observable for ops/debug.  
**Demo/Validation**:
- Background optimizer runs silently; release gate blocks regressions.

### Task 6.1: Add PromptOps SLO dashboards/artifacts
- **Location**: `tools/promptops_metrics_report.py`, `artifacts/promptops/*`
- **Description**: include:
  - promotion win-rate
  - rollback rate
  - template churn
  - task-class success delta
  - latency/cost budgets
- **Complexity**: 5
- **Dependencies**: Sprint 5
- **Acceptance Criteria**:
  - reports provide per prompt-id and per task-class breakdowns.
- **Validation**:
  - tests for report schema and required keys.

### Task 6.2: Add hard release gates for autonomous optimization
- **Location**: `tools/gate_promptops_policy.py`, `tools/gate_promptops_perf.py`, `tools/release_gate.py`
- **Description**: block release when:
  - prompt drift safety checks fail
  - success rate regresses
  - latency budgets exceeded
  - citation/grounding fall below threshold
- **Complexity**: 6
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - failed gate returns actionable reason codes.
- **Validation**:
  - gate fixture tests for each failure class.

## Testing Strategy
- Unit tests: validator/proposer/evaluator/selector/decomposer/merger.
- Integration tests: end-to-end prompt selection and outcome feedback loop.
- Regression suites:
  - Q/H/generic question batteries
  - hard VLM topic suites
  - prompt drift safety suite.
- Determinism checks:
  - same inputs -> same decomposition/selection/merge outputs.
- Soak checks:
  - 24h loop with optimizer enabled under idle-only budgets.

## Potential Risks & Gotchas
- **Current major risk**: naive evaluation can promote bad prompts.
  - Mitigation: disallow promotion without challenge-set coverage and support window.
- **Template overfitting to single screenshot/question set**.
  - Mitigation: cross-run stratified evaluation and holdout suites.
- **Background optimizer causing latency spikes**.
  - Mitigation: strict idle scheduling + bounded worker budget + backoff.
- **Prompt library corruption/drift**.
  - Mitigation: immutable snapshots + atomic promote/rollback.
- **Silent failures hiding quality regressions**.
  - Mitigation: mandatory metrics + release gates + stale-alert policies.

## Rollback Plan
- Disable optimizer worker via config flag (`promptops.optimizer.enabled=false`).
- Revert to last known-good prompt snapshot.
- Keep metrics ingestion running to preserve observability.
- Re-enable only after challenge-set + gate pass.

## Deliverables
- Autonomous PromptOps optimizer subsystem (idle/background).
- Safe prompt library governance with drift prevention.
- Split/merge query orchestration integrated with PromptOps.
- Cross-project PromptOps contract API + documentation.
- Release-grade policy/performance/quality gates.

## Post-Save Gotcha Review
- **Ambiguity resolved**: “silent optimization” means no interactive prompts during normal operation; all changes are audit-logged and gate-controlled.
- **Ambiguity resolved**: VLM outages do not block optimizer loop; offline-safe rule-based candidate generation still runs, but promotion remains gated by quality evidence.
- **Missing dependency added**: require prompt-id task-class taxonomy before split/merge rollout (Sprint 4 depends on Sprint 1 manifest schema).
- **Pitfall addressed**: avoid direct edits to `promptops/prompts/*.txt` from ad-hoc paths; only promote through atomic snapshot workflow.
- **Pitfall addressed**: ensure promotion gates consume both automated metrics and explicit user feedback rows when available.
