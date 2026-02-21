# Plan: Repo 4 Pillars + Pure Function Optimization

**Generated**: 2026-02-18
**Estimated Complexity**: High

## Overview
This plan hardens `autocapture_prime` around its intended pure function: deterministic local ingest -> derived extraction -> index -> citation-backed query answering, with capture/orchestration owned externally by Hypervisor. The plan is release-oriented: every sprint is demoable, testable, and bound to numeric gates.

## Prerequisites
- Runtime endpoints available when required:
  - VLM: `http://127.0.0.1:8000/v1`
  - Embeddings: `127.0.0.1:8001`
  - Grounding sidecar: `127.0.0.1:8011`
- `.venv` test environment ready
- Existing eval corpora (`docs/query_eval_cases*.json`) and golden scripts

## Skill Map (explicit)
- `plan-harder`: top-level sequencing and dependency-safe phase structure.
- `config-matrix-validator`: validate config/profile/runtime matrix and drift.
- `golden-answer-harness`: deterministic Q/H/Generic answer evaluation.
- `evidence-trace-auditor`: enforce answer -> evidence chain completeness.
- `perf-regression-gate`: stage latency/throughput baselines and regression blocking.
- `resource-budget-enforcer`: enforce active/idle CPU+RAM constraints.
- `deterministic-tests-marshal`: repeated-run flake detection and control.
- `python-testing-patterns`: reliable unit/integration test additions.
- `security-threat-model`: define threat-driven security coverage first.
- `policygate-penetration-suite`: fuzz plugin/policy boundaries from threat model.
- `audit-log-integrity-checker`: verify append-only ledger/journal integrity.
- `state-recovery-simulator`: crash/restart resilience verification.
- `logging-best-practices` + `python-observability`: structured telemetry standards.
- `observability-slo-broker`: derive SLOs and release gate thresholds from metrics.
- `source-quality-linter`: validate citation source quality, not just citation presence.

## Sprint 0: Measurement + Determinism Foundation
**Goal**: Establish objective baselines before changing behavior.
**Skills**: `perf-regression-gate`, `deterministic-tests-marshal`, `logging-best-practices`, `python-observability`
**Why**: optimization without stable measurement causes false progress.
**Demo/Validation**:
- Baseline artifact package emitted twice with normalized-equal outputs.
- Determinism report available for tests and eval scripts.

### Task 0.1: Unified telemetry schema and stage timings
- **Location**: `autocapture_nx/kernel/telemetry.py`, `autocapture/runtime/conductor.py`, `autocapture_nx/processing/idle.py`, `tools/*.py`
- **Description**: Define and implement one telemetry schema (`run_id`, `stage`, `duration_ms`, `outcome`, `error_code`, `queue_depth`, `evidence_count`).
- **Complexity**: 7
- **Dependencies**: none
- **Acceptance Criteria**:
  - >= 95% of critical entrypoints emit schema-compliant logs.
  - Missing telemetry is gate-failing.
- **Validation**:
  - Observability smoke test with schema assertions.

### Task 0.2: Baseline performance and correctness snapshots
- **Location**: `tools/gate_perf.py`, `tools/run_golden_qh_cycle.sh`, `tools/q40.sh`, `docs/reports/`
- **Description**: Capture pinned baseline metrics for stage p50/p95 and question-suite accuracy.
- **Complexity**: 5
- **Dependencies**: Task 0.1
- **Acceptance Criteria**:
  - Baseline report includes stage latencies and pass/fail per question suite.
- **Validation**:
  - Two baseline runs produce normalized-equal summaries (ignore timestamps/UUIDs).

### Task 0.3: Flake-rate audit
- **Location**: `tests/`, `tools/`
- **Description**: Run repeated test/eval cycles to compute flake rate and isolate unstable tests.
- **Complexity**: 4
- **Dependencies**: Task 0.2
- **Acceptance Criteria**:
  - Critical gate suites flake rate <= 1% over N=20 runs.
- **Validation**:
  - Deterministic marshal report checked into artifacts.

## Sprint 1: Intent Lock + Config Integrity
**Goal**: Freeze active requirements, eliminate spec/config ambiguity.
**Skills**: `plan-harder`, `config-matrix-validator`
**Why**: avoid implementing superseded or duplicate work.
**Demo/Validation**:
- Updated authoritative matrix with active vs superseded IDs.
- Config matrix gate passing.

### Task 1.1: Regenerate authoritative implementation map
- **Location**: `docs/reports/implementation_matrix.md`, `docs/reports/implementation_authority_map.md`, `docs/reports/full_repo_miss_inventory_*.md`
- **Description**: Rebuild requirement-to-module-to-test mapping from ADR/spec/runbook sources.
- **Complexity**: 4
- **Dependencies**: Sprint 0
- **Acceptance Criteria**:
  - Every active requirement has exactly one owner and one validating test/gate.
- **Validation**:
  - Matrix generation deterministic across two runs.

### Task 1.2: Normalize profile/default behavior
- **Location**: `config/default.json`, `config/autocapture_prime.yaml`, `contracts/config_schema.json`, `tools/preflight_live_stack.py`
- **Description**: Resolve conflicting defaults and enforce Hypervisor-owned orchestration assumptions.
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - No conflicting endpoint/profile defaults.
  - Preflight returns machine-readable fail codes for each failure class.
- **Validation**:
  - Config matrix validator + schema tests pass.

### Task 1.3: Drift-blocking runbook updates
- **Location**: `docs/runbooks/release_gate_ops.md`, `docs/runbooks/live_stack_validation.md`
- **Description**: Document canonical no-drift run sequence and required artifacts.
- **Complexity**: 3
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Runbook provides exact deterministic gate order and success criteria.
- **Validation**:
  - Dry run with generated artifact checklist passes.

## Sprint 2: Accuracy Plumbing (PromptOps + Evidence)
**Goal**: Ensure all answers flow through generic reasoning path with traceability.
**Skills**: `golden-answer-harness`, `evidence-trace-auditor`, `python-testing-patterns`
**Why**: improve correctness without tactical shortcuts.
**Demo/Validation**:
- End-to-end query traces show PromptOps and evidence chain for every answer.

### Task 2.1: Canonical eval corpus unification
- **Location**: `docs/query_eval_cases*.json`, `tools/run_advanced10_queries.py`, `tools/q40.sh`
- **Description**: Merge all suites into one schema with explicit scoring rules and tolerances.
- **Complexity**: 6
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - 100% of existing Q/H/generic cases converted.
  - Each case has deterministic grading logic.
- **Validation**:
  - Golden harness schema + deterministic grading tests.

### Task 2.2: PromptOps mandatory query path (plumbing only)
- **Location**: `autocapture_nx/kernel/query.py`, `services/chronicle_api/app.py`, `autocapture_nx/kernel/export_chatgpt.py`
- **Description**: Enforce mandatory PromptOps transform + trace capture for every query; no autonomous optimization yet.
- **Complexity**: 8
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - 100% queries store raw prompt, transformed prompt, retrieval set, and evidence refs.
  - Direct answer bypass path removed/blocked.
- **Validation**:
  - Integration tests asserting prompt transform hook invocation.

### Task 2.3: Plugin contribution + calibrated confidence
- **Location**: `autocapture_nx/plugin_system/manager.py`, `autocapture_nx/processing/*`, `docs/reports/question-validation-plugin-trace-*.md`
- **Description**: Emit per-plugin contribution trace and calibrated confidence.
- **Complexity**: 7
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Answer payload includes ordered plugin chain and contribution scores.
  - Confidence calibration ECE <= 0.08 on evaluation suite.
- **Validation**:
  - Golden harness confidence calibration report.

### Task 2.4: Held-out and adversarial suite gate
- **Location**: `docs/query_eval_cases_generic20.json`, `docs/autocapture_prime_testquestions2.txt`, `tools/q40.sh`
- **Description**: Add held-out/adversarial suite distinct from tuning corpus.
- **Complexity**: 5
- **Dependencies**: Task 2.3
- **Acceptance Criteria**:
  - Held-out accuracy >= 90% with citation completeness >= 95%.
- **Validation**:
  - Separate regression report for held-out suite.

## Sprint 3: Security + Citeability (Threat-Driven)
**Goal**: Enforce hard boundaries and proof integrity before performance tuning.
**Skills**: `security-threat-model`, `policygate-penetration-suite`, `audit-log-integrity-checker`, `evidence-trace-auditor`, `source-quality-linter`
**Why**: discover high-severity trust gaps early.
**Demo/Validation**:
- Threat model and fuzz coverage report linked to mitigations.
- Citation strictness + replay reproducibility passing.

### Task 3.1: Threat model and coverage matrix
- **Location**: `docs/reports/risk_register.md`, `docs/reports/implementation_authority_map.md`, `docs/adr/`
- **Description**: Create/update threat model aligned to plugin boundaries, local-only contracts, and export paths.
- **Complexity**: 6
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Each threat has owner, mitigation, and test/gate mapping.
- **Validation**:
  - Threat-to-test traceability check passes.

### Task 3.2: PolicyGate + boundary fuzzing
- **Location**: `autocapture_nx/plugin_system/*`, `tests/test_policy_gate.py`, `tests/test_plugin_*`
- **Description**: Implement seed-controlled fuzz suites for capability, filesystem, network, and subprocess boundaries.
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - 0 critical escapes across seeded fuzz runs.
- **Validation**:
  - Reproducible fuzz report hash stable across two runs.

### Task 3.3: Append-only audit and integrity strictness
- **Location**: `plugins/builtin/ledger_basic/plugin.py`, `plugins/builtin/journal_basic/plugin.py`, `tools/gate_ledger.py`
- **Description**: Add explicit tamper/gap detection diagnostics and privileged-action append-only audits.
- **Complexity**: 6
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - 100% simulated tamper cases fail closed with machine-readable reason.
- **Validation**:
  - Integrity checker tamper suite passes.

### Task 3.4: Citation strict mode + replay reproducibility
- **Location**: `autocapture_nx/kernel/proof_bundle.py`, `autocapture/pillars/citable.py`, `services/chronicle_api/app.py`
- **Description**: Block uncitable answers; enforce proof replay reproducibility and source-quality constraints.
- **Complexity**: 7
- **Dependencies**: Tasks 2.2, 2.3, 3.3
- **Acceptance Criteria**:
  - Citation completeness >= 98% on corpus.
  - Replay verification pass rate = 100% for answered cases.
- **Validation**:
  - Evidence auditor + source-quality lint + replay tests.

## Sprint 4: Performance + Runtime Governance
**Goal**: Improve speed and stability without violating resource constraints.
**Skills**: `perf-regression-gate`, `resource-budget-enforcer`, `state-recovery-simulator`
**Why**: throughput gains must be safe under real runtime stress.
**Demo/Validation**:
- Stage p95 reductions and budget compliance report.

### Task 4.1: VLM request gate tuning
- **Location**: `autocapture_nx/inference/vllm_endpoint.py`, `tools/preflight_live_stack.py`
- **Description**: Tune inflight gate, timeout envelopes, retries, and orchestrator fallback signaling.
- **Complexity**: 7
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Max restart attempts <= 1 per preflight cycle.
  - Concurrency gate enforces `max_inflight` deterministically.
- **Validation**:
  - Concurrent stress test with induced VLM slowness/crashes.

### Task 4.2: Runtime queue/backpressure optimization
- **Location**: `autocapture/runtime/scheduler.py`, `autocapture/runtime/governor.py`, `autocapture/runtime/conductor.py`
- **Description**: Optimize queue behavior and preemption to minimize latency while preserving foreground gating.
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Active-mode heavy-job execution rate = 0.
  - CPU/RAM during active mode <= configured limits.
- **Validation**:
  - Resource budget enforcer active/idle tests.

### Task 4.3: Perf regression thresholds
- **Location**: `tools/gate_perf.py`, `docs/runbooks/release_gate_ops.md`
- **Description**: Lock performance budgets and block regressions relative to Sprint 0 baseline.
- **Complexity**: 4
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - No >10% p95 regression on critical stages without waiver.
- **Validation**:
  - Perf gate with baseline diff artifact.

## Sprint 5: PromptOps Autonomous Optimizer + SLOs
**Goal**: Add safe self-improvement loop on top of already-correct query plumbing.
**Skills**: `logging-best-practices`, `python-observability`, `observability-slo-broker`, `golden-answer-harness`
**Why**: adaptive gains must remain observable and gated.
**Demo/Validation**:
- Versioned prompt-template updates with measured effect.
- SLO-driven gates integrated into release path.

### Task 5.1: Autonomous PromptOps review scheduler
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture/runtime/conductor.py`, `docs/runbooks/promptops_golden_ops.md`
- **Description**: Add background clustering/review of failed or low-confidence queries, propose template changes, and stage them behind approval gates.
- **Complexity**: 9
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - Each template proposal includes before/after metrics and rollback token.
- **Validation**:
  - Golden harness verifies no regression and >= 3% uplift on targeted class.

### Task 5.2: SLO definitions and automated enforcement
- **Location**: `docs/runbooks/release_gate_ops.md`, `tools/gate_perf.py`, `tools/gate_security.py`, `tools/gate_doctor.py`
- **Description**: Define release SLOs for correctness, citation completeness, latency, and recovery.
- **Complexity**: 5
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - SLOs are versioned, machine-readable, and evaluated each run.
- **Validation**:
  - SLO broker output consumed by gates.

## Sprint 6: Golden Readiness + Soak Entry
**Goal**: Reach stable soak-ready golden profile.
**Skills**: `state-recovery-simulator`, `golden-answer-harness`, `deterministic-tests-marshal`
**Why**: final readiness requires resilience first, then deterministic correctness.
**Demo/Validation**:
- Recovery report, then repeated deterministic golden report, then profile freeze artifact.

### Task 6.1: Crash/restart robustness first
- **Location**: `tools/preflight_live_stack.py`, `services/chronicle_api/app.py`, `autocapture/runtime/conductor.py`
- **Description**: Validate graceful degradation/recovery for VLM outages and partial service failures.
- **Complexity**: 6
- **Dependencies**: Sprint 5
- **Acceptance Criteria**:
  - Recovery success >= 99% across N=100 simulated fault injections.
- **Validation**:
  - State-recovery simulator report.

### Task 6.2: Repeated deterministic 40-question cycles
- **Location**: `tools/run_golden_qh_cycle.sh`, `tools/q40.sh`, `docs/reports/advanced20_answers_latest.txt`
- **Description**: Execute repeated full-suite runs after resilience stabilization.
- **Complexity**: 6
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Accuracy >= 95% over N=10 repeated full cycles.
  - Flake rate <= 1%.
- **Validation**:
  - Determinism marshal + golden harness combined report.

### Task 6.3: Golden profile freeze and anti-drift controls
- **Location**: `config/default.json`, `config/plugin_locks.json`, `docs/runbooks/release_gate_ops.md`
- **Description**: Freeze golden profile hash/lock digest and define anti-drift release checks.
- **Complexity**: 4
- **Dependencies**: Task 6.2
- **Acceptance Criteria**:
  - Frozen profile and lock digest required for soak entry.
- **Validation**:
  - Gate verifies profile and lock hash before start.

## Testing Strategy
- Unit tests for query path, attribution, confidence, security checks, and recovery logic.
- Integration tests for PromptOps path enforcement, VLM preflight/gating, and citation strict mode.
- Fuzz tests with fixed seeds for PolicyGate and plugin boundaries.
- Repeated deterministic runs (N>=10) on full question suites.
- Replay tests proving citation/evidence reproducibility.

## Potential Risks & Gotchas
- PromptOps overfitting to fixed datasets.
  Mitigation: held-out/adversarial suite gate (Sprint 2.4).
- Confidence score miscalibration.
  Mitigation: explicit ECE metric threshold and recalibration checks.
- VLM instability interpreted as logic failure.
  Mitigation: isolated resilience-first sprint and fail-code taxonomy.
- Spec/document drift.
  Mitigation: authority map regeneration and drift gate before release.
- Security regressions hidden by non-deterministic fuzz.
  Mitigation: seed-controlled fuzz and artifact hash checks.

## Rollback Plan
- Keep optimizer behaviors behind flags and versioned template bundles.
- Roll back to last passing profile hash + plugin lock digest.
- Disable autonomous PromptOps updates while preserving baseline query plumbing.
- Restore previous gate thresholds only with documented waiver and expiry.
