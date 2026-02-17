# Plan: Golden Pipeline Remaining Failures

**Generated**: 2026-02-16  
**Estimated Complexity**: High

## Overview
This plan fixes the remaining Golden pipeline failures for `Q1-Q10` and `H10` using generic class-level extraction and reasoning improvements. It explicitly avoids per-question shortcuts and enforces metadata-only, citation-grounded answering.

## Prerequisites
- External VLM endpoint healthy at `http://127.0.0.1:8000` (localhost only).
- `.venv` and test tooling available.
- Golden question files:
  - `docs/query_eval_cases_advanced20.json`
  - `docs/autocapture_prime_testquestions2.txt`
- Test image(s) available, including new 7680x2160 layout captures.

## Sprint 0: Preflight and Fail-Closed Contracts
**Goal**: Ensure execution environment is valid before extractor work begins.  
**Demo/Validation**:
- One preflight command reports VLM/model/profile/case checksums and fails closed on mismatch.

### Task 0.1: Localhost and Endpoint Policy Preflight
- **Location**: `tools/preflight_live_stack.py`, `autocapture_nx/inference/vllm_endpoint.py`
- **Description**: Validate localhost-only VLM usage, endpoint readiness, and model availability.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Preflight rejects non-`127.0.0.1` endpoints.
  - Preflight emits model id and readiness status.
- **Validation**:
  - Unit tests for endpoint policy.
  - Preflight command pass/fail cases.

### Task 0.2: Profile/Cases Checksum Pinning
- **Location**: `tools/preflight_live_stack.py`, `tools/run_golden_qh_cycle.sh`
- **Description**: Pin and verify checksums for golden profile and case files before runs.
- **Complexity**: 3
- **Dependencies**: Task 0.1
- **Acceptance Criteria**:
  - Run aborts if case/profile hash differs from expected.
- **Validation**:
  - Negative test with modified case file.

## Sprint 1: Stable Inputs + Baseline
**Goal**: Make runs reproducible and baseline failures measurable.  
**Demo/Validation**:
- Deterministic run produces report + failure snapshot with stable ids.

### Task 1.1: Deterministic Input/Report Selection
- **Location**: `tools/process_single_screenshot.py`, `tools/run_golden_qh_smoke.sh`, `tools/run_golden_qh_cycle.sh`
- **Description**: Remove ambiguous latest-file behavior and require explicit image/report inputs for golden/eval commands.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Golden scripts fail-fast when explicit input is missing.
- **Validation**:
  - Unit tests for explicit input resolution.

### Task 1.2: Screenshot Skill Capture Entry Script
- **Location**: `tools/`, `docs/runbooks/`
- **Description**: Add capture-to-pipeline script that takes screenshot via skill helper and immediately runs golden processing.
- **Complexity**: 3
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Captured image path recorded in run artifact.
  - End-to-end runs from one command.
- **Validation**:
  - Automated smoke test asserts report image path equals captured file.

### Task 1.3: Baseline Failure Snapshot
- **Location**: `tools/run_advanced10_queries.py`, `docs/reports/`
- **Description**: Persist per-question missing-check snapshots and generate pre/post diff reports.
- **Complexity**: 4
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Snapshot includes question id, failed checks, and missing tokens.
- **Validation**:
  - Two-run diff output verified.

## Sprint 2: High-Resolution Generic Extraction
**Goal**: Improve extraction quality for all advanced classes under 7680x2160 layouts.  
**Demo/Validation**:
- Candidate debug shows ROI/tile coverage and non-degenerate structured payloads.

### Task 2.1: 12-Segment Tiling + Topic ROI Overlays
- **Location**: `autocapture_nx/kernel/query.py`, `plugins/builtin/processing_sst_vlm_ui/plugin.py`
- **Description**: Implement reusable 12-segment tiling with topic overlays for ingest-time and query-time VLM.
- **Complexity**: 8
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Candidate generator emits tile+ROI metadata for every advanced topic.
- **Validation**:
  - Candidate count/bounds tests.

### Task 2.2a: Structured Contract Batch A (Window/Focus/Incident)
- **Location**: `autocapture_nx/kernel/query.py`, `plugins/builtin/observation_graph/plugin.py`
- **Description**: Enforce strict schemas for `adv.window.inventory`, `adv.focus.window`, `adv.incident.card`.
- **Complexity**: 7
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Valid structured fields or explicit indeterminate reason.
- **Validation**:
  - Contract tests for these 3 topics.

### Task 2.2b: Structured Contract Batch B (Activity/Details/Calendar)
- **Location**: same as Task 2.2a
- **Description**: Enforce strict schemas for `adv.activity.timeline`, `adv.details.kv`, `adv.calendar.schedule`.
- **Complexity**: 7
- **Dependencies**: Task 2.2a
- **Acceptance Criteria**:
  - Ordered rows and required fields preserved.
- **Validation**:
  - Contract tests for these 3 topics.

### Task 2.2c: Structured Contract Batch C (Slack/Dev/Console/Browser)
- **Location**: same as Task 2.2a
- **Description**: Enforce strict schemas for `adv.slack.dm`, `adv.dev.summary`, `adv.console.colors`, `adv.browser.windows`.
- **Complexity**: 8
- **Dependencies**: Task 2.2b
- **Acceptance Criteria**:
  - Typed fields; no placeholder/generic JSON accepted.
- **Validation**:
  - Contract tests for these 4 topics.

### Task 2.3: Evidence-Weighted Support Snippets
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Build provenance-aware snippet retrieval from extracted metadata only (`derived.text.*`, `derived.sst.*`), no screenshot-time dependence.
- **Complexity**: 6
- **Dependencies**: Task 2.2c
- **Acceptance Criteria**:
  - Snippets include source ids and confidence weighting.
- **Validation**:
  - Unit tests for snippet scoring and dedupe.

## Sprint 3: PromptOps + Arbitration + Anti-Hack Gates
**Goal**: Ensure robust answer selection and policy enforcement.  
**Demo/Validation**:
- Query trace shows arbitration inputs, winner rationale, and plugin in-path attribution.

### Task 3.1: Arbitration 2.0 (No Early Exit for Advanced)
- **Location**: `autocapture_nx/kernel/query.py`
- **Description**: Score all advanced candidates with structural + semantic + provenance factors and select best.
- **Complexity**: 8
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Advanced queries evaluate full candidate set before final pick.
- **Validation**:
  - Arbitration tie-break and regression tests.

### Task 3.2: PromptOps Mandatory Advanced/Hard Path
- **Location**: `autocapture/promptops/*`, `autocapture_nx/kernel/query.py`
- **Description**: Enforce PromptOps usage for Q/H query families and persist rewrite traces + timing.
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - `promptops_used=true` for all Q/H eval rows.
- **Validation**:
  - PromptOps policy/perf tests and gate scripts.

### Task 3.3: Plugin Attribution Expansion
- **Location**: `autocapture_nx/kernel/query.py`, `tools/generate_qh_plugin_validation_report.py`
- **Description**: Emit `in_path` status and confidence contribution per plugin and sequence.
- **Complexity**: 6
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Reports show exact plugin sequence used to produce final answer.
- **Validation**:
  - Attribution report test updates.

### Task 3.4: Anti-Hack Policy Gate
- **Location**: `tools/gate_promptops_policy.py`, `tests/`
- **Description**: Add blocking checks forbidding question-id-specific branching and hardcoded expected answer literals in query/parsing code.
- **Complexity**: 5
- **Dependencies**: Task 3.3
- **Acceptance Criteria**:
  - CI fails on banned patterns.
- **Validation**:
  - Policy gate tests with positive/negative fixtures.

## Sprint 4: Question-Class Completion
**Goal**: Pass all `Q1-Q10` and `H10` while preserving `H1-H9` correctness.  
**Demo/Validation**:
- Full advanced20 passes with strict metadata-only gates.

### Task 4.1.0: Commit Q-Only Case File
- **Location**: `docs/query_eval_cases_q10.json`
- **Description**: Create repo-tracked Q-only case file for fast iteration (no `/tmp` dependency).
- **Complexity**: 2
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Q-only runner works from committed file path.
- **Validation**:
  - Q-only eval command succeeds.

### Task 4.1.1: Q1 Window Inventory Parser Hardening
- **Location**: `autocapture_nx/kernel/query.py`, `plugins/builtin/observation_graph/plugin.py`, `tests/test_query_advanced_display.py`
- **Description**: Generic top-level window inventory with host/VDI attribution and occlusion/z-order rules.
- **Complexity**: 6
- **Dependencies**: Task 4.1.0
- **Acceptance Criteria**:
  - Q1 expected fields and ordering checks pass.
- **Validation**:
  - Deterministic Q1 test + eval assertion.

### Task 4.1.2: Q2 Focus Evidence Parser Hardening
- **Location**: same pattern as Task 4.1.1
- **Description**: Enforce two evidence items with exact highlighted text extraction.
- **Complexity**: 6
- **Dependencies**: Task 4.1.1
- **Acceptance Criteria**:
  - Q2 passes exact evidence checks.
- **Validation**:
  - Q2 focused parser tests + eval.

### Task 4.1.3: Q3 Incident Header and Domain Parsing
- **Location**: same pattern as Task 4.1.1
- **Description**: Robust sender display/domain extraction with domain normalization and redaction-safe behavior.
- **Complexity**: 6
- **Dependencies**: Task 4.1.2
- **Acceptance Criteria**:
  - Q3 passes subject/sender/domain/button checks.
- **Validation**:
  - Q3 contract tests + eval.

### Task 4.1.4: Q4 Timeline Row Grouping
- **Location**: same pattern as Task 4.1.1
- **Description**: Ordered timestamp-text row grouping for Record Activity.
- **Complexity**: 6
- **Dependencies**: Task 4.1.3
- **Acceptance Criteria**:
  - Q4 passes complete timeline checks.
- **Validation**:
  - Q4 tests + eval.

### Task 4.1.5: Q5 Details KV Pairing
- **Location**: same pattern as Task 4.1.1
- **Description**: Two-column KV pairing, empty-field retention, stable order.
- **Complexity**: 6
- **Dependencies**: Task 4.1.4
- **Acceptance Criteria**:
  - Q5 passes required labels/values.
- **Validation**:
  - Q5 tests + eval.

### Task 4.1.6: Q6 Calendar Schedule Extraction
- **Location**: same pattern as Task 4.1.1
- **Description**: Month/year, selected date, and first-5 schedule rows extraction with time-title alignment.
- **Complexity**: 6
- **Dependencies**: Task 4.1.5
- **Acceptance Criteria**:
  - Q6 passes expected month/date/items checks.
- **Validation**:
  - Q6 tests + eval.

### Task 4.1.7: Q7 Slack Transcript + Thumbnail Description
- **Location**: same pattern as Task 4.1.1
- **Description**: Last-two messages (sender/time/text) and visible-only thumbnail description.
- **Complexity**: 6
- **Dependencies**: Task 4.1.6
- **Acceptance Criteria**:
  - Q7 passes message and thumbnail checks.
- **Validation**:
  - Q7 tests + eval.

### Task 4.1.8: Q8 Dev Summary Section Parser
- **Location**: same pattern as Task 4.1.1
- **Description**: Section boundary parser for What changed / Files / Tests command.
- **Complexity**: 6
- **Dependencies**: Task 4.1.7
- **Acceptance Criteria**:
  - Q8 passes exact file path and command checks.
- **Validation**:
  - Q8 tests + eval.

### Task 4.1.9: Q9 Color-Aware Console Line Extraction
- **Location**: same pattern as Task 4.1.1
- **Description**: Color-band line extraction with red/green/other counts and full red line text.
- **Complexity**: 6
- **Dependencies**: Task 4.1.8
- **Acceptance Criteria**:
  - Q9 passes count + red line checks.
- **Validation**:
  - Q9 tests + eval.

### Task 4.1.10: Q10 Browser Chrome Parser
- **Location**: same pattern as Task 4.1.1
- **Description**: Per-window active tab, hostname-only address extraction, tab count.
- **Complexity**: 6
- **Dependencies**: Task 4.1.9
- **Acceptance Criteria**:
  - Q10 passes required browser tuple checks.
- **Validation**:
  - Q10 tests + eval.

### Task 4.2: H10 Action Grounding Accuracy
- **Location**: `autocapture_nx/kernel/query.py`, `tests/`
- **Description**: Robust normalized box extraction with mapping (`VIEW DETAILS` vs `VIEW_DETAILS`), bounds checks, non-degenerate boxes, and IoU validation.
- **Complexity**: 7
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - H10 passes IoU threshold.
- **Validation**:
  - H10-specific regression tests.

### Task 4.3: Coordinate Frame Contract Test
- **Location**: `tests/test_query_advanced_display.py`, `tests/test_run_advanced10_expected_eval.py`
- **Description**: Validate coordinate transforms across 7680x2160 tile space and normalized 2048x575 reference expectations.
- **Complexity**: 5
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - No frame mismatch drift in grounding outputs.
- **Validation**:
  - Deterministic coordinate-frame tests.

### Task 4.4: H1-H9 Non-Regression Gate
- **Location**: `tools/run_advanced10_queries.py`, `tests/`
- **Description**: Add explicit checks to ensure H1-H9 stay passing while fixing H10/Q failures.
- **Complexity**: 4
- **Dependencies**: Task 4.1.10, Task 4.2
- **Acceptance Criteria**:
  - No regression for H1-H9.
- **Validation**:
  - Full advanced20 strict eval.

## Sprint 5: Blocking Gates Then Soak
**Goal**: Lock correctness and stability before release/soak.  
**Demo/Validation**:
- CI blocks regressions; soak metrics stay within thresholds.

### Task 5.1: Strict Golden Gate Wiring
- **Location**: `.github/workflows/chronicle-stack-gate.yml`, `tools/gate_*`
- **Description**: Make this command blocking in CI:
  - `tools/run_advanced10_queries.py --cases docs/query_eval_cases_advanced20.json --strict-all --metadata-only --repro-runs 3 --confidence-drift-tolerance-pct 1.0`
- **Complexity**: 5
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - CI fails on any Q/H mismatch, confidence drift breach, or policy gate failure.
- **Validation**:
  - Local and CI gate runs.

### Task 5.2: Soak With Numeric SLO Thresholds
- **Location**: `tools/soak/*`, `tools/run_golden_qh_cycle.sh`
- **Description**: Run repeated cycles with hard thresholds:
  - pass rate >= 100% on golden set,
  - confidence drift <= 1.0%,
  - p95 query latency target (documented by mode),
  - retry/error rate <= configured cap.
- **Complexity**: 6
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - Soak report includes threshold pass/fail and trend lines.
- **Validation**:
  - Soak report artifacts and threshold assertions.

## Testing Strategy
- Unit tests for extraction, arbitration, and normalization.
- Contract tests for all advanced topic schemas.
- Policy gates for anti-hack and PromptOps enforcement.
- Eval strategy:
  - Q-only loop: `docs/query_eval_cases_q10.json` for fast iteration.
  - Full strict loop: `docs/query_eval_cases_advanced20.json`.
- Determinism:
  - minimum `repro-runs=3` with confidence drift checks.
- Metadata-only enforcement:
  - required on all final golden gate runs.

## Potential Risks & Gotchas
- VLM context/token limits reduce structured quality.
  - Mitigation: adaptive tile/ROI sizing, retries, strict schema acceptance.
- Overfitting to one screenshot.
  - Mitigation: class-level parser contracts and anti-hack policy gate.
- Timeout-based false negatives.
  - Mitigation: per-topic timeout budgets and retry policy.
- Coordinate-frame mismatches for grounding.
  - Mitigation: dedicated transform contract tests.
- Attribution ambiguity.
  - Mitigation: `in_path` plugin trace and confidence contribution reporting.

## Rollback Plan
- Keep new arbitration/extraction behavior behind config flags in `processing.on_query`.
- Rollback steps:
  1. Disable new arbitration mode.
  2. Re-enable last stable query display path.
  3. Run strict advanced20 gate to confirm restoration.
- Preserve baseline and post-change snapshot artifacts for rapid diff-based rollback decisions.
