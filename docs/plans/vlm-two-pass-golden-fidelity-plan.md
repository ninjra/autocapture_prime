# Plan: VLM Two-Pass Golden Fidelity Closure

**Generated**: 2026-02-14  
**Estimated Complexity**: High

## Overview
Raise screenshot understanding fidelity to deterministic, citation-backed quality by enforcing a generic two-step VLM pipeline (thumbnail ROI proposal -> hi-res ROI parsing), then routing all Q/H answers through structured extracted state (not raw OCR fallback) with strict evaluation.

This plan is built to satisfy the 4 pillars:
- Performance: ROI-first inference, bounded budgets, parallelizable extraction.
- Accuracy: hi-res crop parsing + structured validators + strict fail-closed eval.
- Security: localhost-only VLM, policy-gated plugin graph, no raw data deletion.
- Citeability: every claim tied to derived records with producer trace.

## Prerequisites
- External VLM server reachable at `http://127.0.0.1:8000`.
- Golden profile and eval corpora available:
  - `config/profiles/golden_full.json`
  - `docs/query_eval_cases_advanced20.json`
  - `docs/autocapture_prime_testquestions2.txt`
- Processing entry points:
  - `tools/process_single_screenshot.py`
  - `tools/run_advanced10_queries.py`
  - `tools/query_latest_single.py`

## Sprint 1: Stabilize Golden Runtime Contract
**Goal**: Make golden runs deterministic and fail-closed before fidelity tuning.
**Demo/Validation**:
- One command run produces non-zero exit on any missing required plugin or VLM outage.
- Artifact includes required plugin load report + VLM health details.

### Task 1.1: Pin determinism contract and ban drift flags
- **Location**: `config/profiles/golden_full.json`, `tools/process_single_screenshot.py`, `tools/run_advanced10_queries.py`
- **Description**: Define immutable deterministic inputs for golden runs (model fingerprint, decode params, locale/timezone, seed/fallback deterministic mode) and reject env overrides/degraded flags in strict mode.
- **Complexity**: 7
- **Dependencies**: None
- **Acceptance Criteria**:
  - Strict mode refuses execution when deterministic contract is incomplete.
  - `temperature=0`, `top_p=1`, `n=1` are enforced for extraction requests.
- **Validation**:
  - N-run reproducibility gate (`N=3`) with canonicalized output diff = empty.

### Task 1.2: Normalize required plugin gate
- **Location**: `config/profiles/golden_full.json`, `tools/process_single_screenshot.py`
- **Description**: Ensure required plugin list reflects true golden dependencies; remove accidental hard dependencies that are not required for Q/H correctness.
- **Complexity**: 5
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Required plugins are explicit and stable.
  - Run fails immediately when any required plugin is missing.
- **Validation**:
  - Negative test: disable one required plugin and confirm fail-closed behavior.

### Task 1.3: Add execution lineage ledger (plugin-level truth source)
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/kernel/derived_records.py`, `tools/process_single_screenshot.py`
- **Description**: Emit per-plugin stage ledger fields (`loaded`, `admitted`, `executed`, `emitted_record_ids`, `errors`, `no_op_reason`, `input_record_ids`) so attribution is computed from lineage, not inferred from citations.
- **Complexity**: 7
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Every run has complete plugin execution ledger.
- **Validation**:
  - Schema test requires ledger completeness across all loaded plugins.

### Task 1.4: Enforce run metadata completeness
- **Location**: `tools/process_single_screenshot.py`, `tools/run_advanced10_queries.py`
- **Description**: Require run artifact fields for profile hash, plugin load states, VLM endpoint status, and model id used.
- **Complexity**: 4
- **Dependencies**: Task 1.3
- **Acceptance Criteria**:
  - Every run includes machine-readable metadata for reproducibility.
- **Validation**:
  - JSON schema check in test for required run fields.

### Task 1.5: Lock profile checksum at start of pipeline
- **Location**: `config/profiles/golden_full.json`, `tools/run_advanced10_queries.py`, `docs/reports/implementation_matrix.md`
- **Description**: Add profile checksum and test gate before any tuning/eval work so all later runs are on a fixed baseline.
- **Complexity**: 4
- **Dependencies**: Task 1.4
- **Acceptance Criteria**:
  - Mismatch between expected and runtime profile checksum fails run before processing.
- **Validation**:
  - Drift test verifies checksum mismatch fails.

## Sprint 2: Two-Step VLM Extraction Hardening
**Goal**: Make the two-step method the authoritative extraction path.
**Demo/Validation**:
- Processing artifact shows thumbnail pass and hi-res ROI pass evidence.
- Structured UI state has stable windows/ROIs/facts for repeated runs.

### Task 2.1: Force two-pass path in golden profile
- **Location**: `config/profiles/golden_full.json`, `tools/process_single_screenshot.py`
- **Description**: Pin `two_pass_enabled=true` and lock high-fidelity defaults (thumb size, max ROIs, ROI side, token budgets) for golden runs.
- **Complexity**: 4
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Golden run never silently downgrades to single-pass unless explicitly marked degraded.
- **Validation**:
  - Report asserts `backend=openai_compat_two_pass` for VLM extraction.

### Task 2.2: Improve ROI quality and dedupe
- **Location**: `plugins/builtin/vlm_vllm_localhost/plugin.py`
- **Description**: Tune ROI candidate scoring/deduplication and add deterministic merge rules for overlapping windows/panes.
- **Complexity**: 7
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Window detection on fixture set achieves at least `precision>=0.90`, `recall>=0.90`.
  - ROI dedupe stability delta across 3 runs is `<= 1%` on bbox coordinates after normalization.
- **Validation**:
  - Regression fixtures for z-order/occlusion/window-count classes.

### Task 2.3: Add OCR-as-context (not authority) for hi-res ROI parse
- **Location**: `plugins/builtin/vlm_vllm_localhost/plugin.py`, `autocapture_nx/processing/sst/stage_plugins.py`
- **Description**: Feed OCR snippets into ROI parsing prompt as context only; final records remain VLM-structured with confidence and provenance.
- **Complexity**: 7
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Table/form/timeline extraction improves without reverting to OCR-only answering.
- **Validation**:
  - Fixture tests where OCR alone was previously noisy.

## Sprint 3: Structured State + Generic Reasoning
**Goal**: Ensure answers come from extracted state graph, not question-specific shortcuts.
**Demo/Validation**:
- Paraphrased versions of Q/H queries return equivalent answers.
- No keyword-specific tactical branch required.

### Task 3.1: Expand canonical state records
- **Location**: `plugins/builtin/observation_graph/plugin.py`, `autocapture_nx/kernel/derived_records.py`
- **Description**: Persist typed records for windows, focus evidence, details KV, record activity, calendar items, chat messages, console color lines, browser chrome, and action buttons.
- **Complexity**: 8
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Q1-Q10 and H1-H10 are answerable from derived records only.
- **Validation**:
  - Record schema tests + fixture assertions for each record class.

### Task 3.2: Remove tactical query branches
- **Location**: `autocapture_nx/kernel/query.py`, `plugins/builtin/observation_graph/plugin.py`, `autocapture_nx/processing/sst/stage_plugins.py`
- **Description**: Replace string-triggered answer paths and extraction-layer marker shortcuts with intent/capability resolution; remove hard-question tactical handlers and enforce generic record-driven logic.
- **Complexity**: 8
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Query paraphrase equivalence rate is `>= 95%` on Q/H set.
  - No tactical marker/rule table is used by production answer path.
- **Validation**:
  - Paraphrase test suite with strict equivalence checks.
  - Static lint gate that fails on reintroduction of tactical question-marker tables.

## Sprint 4: Full Metrics, Attribution, and Confidence
**Goal**: Prove which plugins actually contributed and quantify correctness.
**Demo/Validation**:
- Per-question output includes plugin path, citations, confidence, and latency.
- Effectiveness report flags weak plugins and recommends actions.

### Task 4.1: End-to-end plugin contribution graph
- **Location**: `autocapture_nx/kernel/query.py`, `tools/generate_qh_plugin_validation_report.py`
- **Description**: Emit full plugin inventory for each answer: loaded, executed, in-path, out-of-path, contribution score, and supporting record ids.
- **Complexity**: 6
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Every citation resolves to a concrete producer execution event.
  - Every out-of-path plugin has explicit exclusion reason.
  - Chain completeness validation passes with zero missing links.
- **Validation**:
  - Snapshot tests for plugin attribution payload schema.

### Task 4.2: Confidence calibration and strict grading
- **Location**: `tools/query_eval_suite.py`, `tools/run_advanced10_queries.py`
- **Description**: Calibrate confidence labels (`high`, `medium`, `low`) from evidence coverage + consistency and fail strict runs on wrong high-confidence answers.
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Confidence is aligned with correctness, not just verbosity.
- **Validation**:
  - Confusion-matrix export and threshold test.

## Sprint 5: Golden Closure and Drift Guard
**Goal**: Keep golden profile stable and prevent regressions.
**Demo/Validation**:
- All 20 Q/H cases pass in strict mode on the sample artifact.
- Drift gate blocks release when any regression occurs.

### Task 5.1: Strict 20-case closure run
- **Location**: `tools/run_advanced10_queries.py`, `docs/query_eval_cases_advanced20.json`
- **Description**: Run full strict suite and require 20/20 pass with citations and confidence fields present.
- **Complexity**: 5
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - `cases_passed=20`, `cases_failed=0`, strict evaluation true for all.
- **Validation**:
  - Run artifact archived under `artifacts/advanced10/` with timestamp.

### Task 5.2: Controlled rebaseline protocol
- **Location**: `docs/reports/implementation_matrix.md`, `docs/reports/`
- **Description**: Keep drift gate from Sprint 1 and add explicit rebaseline protocol requiring new strict artifact, changed checksum, and reviewer approval note.
- **Complexity**: 3
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - No baseline changes without matching strict artifact and rationale.
- **Validation**:
  - Rebaseline checklist test in CI/local gate.

## vLLM Server-Side Changes (What You Need)
### Required
- Serve OpenAI-compatible VLM endpoint on `127.0.0.1:8000` with:
  - `GET /health` (exact path)
  - `GET /v1/models`
  - `POST /v1/chat/completions` supporting image input (`image_url` data URL payload)
- Keep model loaded and stable (no model-id churn between requests), and expose stable model + tokenizer fingerprint in startup logs used by run metadata.
- Enforce deterministic decode contract for extraction path: `temperature=0`, `top_p=1`, `n=1`; support fixed seed if available, otherwise document deterministic fallback.
- Ensure context window is large enough for hi-res ROI prompts (`max_model_len >= 8192` minimum).
- Keep service localhost-only (fail closed if bound to non-localhost).
- Throughput/runtime contract for two-pass strict runs:
  - Concurrent request capacity `>= 2`.
  - Timeout floor `>= 45s` for image parsing requests.

### Strongly Recommended
- Use a VLM tuned for UI reading (current target: InternVL3.5-8B served via vLLM-compatible API at port 8000).
- Keep backend runtime warm (no cold unload between golden-run requests).

### Optional (Quality/Speed)
- Provide separate embedding endpoint (for `builtin.embedder.vllm_localhost`) if GPU budget allows; otherwise keep `builtin.embedder.basic` as fallback.
- Enable backend optimizations (FlashAttention/FlashInfer where supported) after correctness is stable.

## Testing Strategy
- Unit tests for ROI parsing/merge, record extraction, query intent routing, and confidence calibration.
- Deterministic fixture tests for Q/H schema-level outputs.
- End-to-end strict run against advanced20 corpus with artifact retention.
- 3-run reproducibility check for canonicalized outputs and plugin lineage.
- Negative tests: VLM unavailable, plugin missing, and profile drift.

## Potential Risks & Gotchas
- VLM uptime instability at `:8000` can mask pipeline quality issues.
  - Mitigation: hard preflight + explicit degraded-mode flag.
- Overfitting to one sample screenshot.
  - Mitigation: paraphrase tests + cross-fixture variants.
- OCR noise contaminating structured extraction.
  - Mitigation: OCR as auxiliary context only, never sole authority for structured claims.

## Rollback Plan
- Keep previous golden profile copy and last passing strict artifact.
- Revert profile/plugin setting deltas first if regressions appear.
- If extraction quality degrades, disable newly introduced tuning knobs behind profile flags and rerun strict suite.
