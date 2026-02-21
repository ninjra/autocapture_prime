# Plan: Advanced20 True Strict Correctness

**Generated**: 2026-02-19
**Estimated Complexity**: High

## Overview
This plan replaces token-presence scoring with true strict correctness and closes extraction gaps so Advanced20 and Generic20 can pass under fail-closed gates.

Target end state:
- 
- 
- 
- 
- all answers evidence-backed and contradiction-free

Approach: harden scorer semantics first, then harden answer construction/extraction, then enforce strict end-to-end gates and report integrity.

## Clarified Requirements
- Strictness means exact expected answer compliance for Advanced20; weak substring matches are insufficient.
- Generic20 remains best-effort, but must still be evaluated (no skip pass-through).
-  query mode remains required for golden runs.
- Local VLM on  is used for extraction support only, not to fabricate answers outside evidence.

## Four-Pillar Targets
- **Accuracy**: no pass on indeterminate/contradictory/misaligned fields.
- **Citeability**: every asserted field must map to topic-scoped structured evidence.
- **Security**: fail closed when required structured evidence is missing; no fallback to noisy text blobs.
- **Performance**: bounded per-query checks and deterministic gating without explosive retries.

## Prerequisites
-  usable for local tools/tests.
- VLM endpoint healthy at .
- Latest single-image fixture report available in .
- Golden profile lock valid:  hash matches report hash.

## Sprint 1: Freeze Strict Truth Contract
**Goal**: make the evaluator unable to emit false-green outcomes.

**Demo/Validation**:
- run strict evaluator on known-bad artifact and verify it fails.
- run strict evaluator on corrected fixture and verify pass conditions are explicit.

### Task 1.1: Introduce strict scoring rubric per case family
- **Location**: , new 
- **Description**: define explicit matching mode per case (, , , , ).
- **Complexity**: 4
- **Dependencies**: none
- **Acceptance Criteria**:
  - every Advanced20 case has an unambiguous strict matching mode.
- **Validation**:
  - fixture schema test in .

### Task 1.2: Remove broad haystack token-pass semantics from strict path
- **Location**: 
- **Description**: replace -based strict checks with answer-surface-only checks (summary + topic-local fields only), and disallow checks against full serialized result JSON.
- **Complexity**: 7
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - strict mode cannot pass via tokens appearing only in support/noise snippets.
- **Validation**:
  - extend  with false-positive regression fixtures.

### Task 1.3: Add contradiction and indeterminate fail-closed checks
- **Location**: 
- **Description**: enforce strict failure on , conflicting numeric counts, missing required ordered rows, or unsupported fallback modes.
- **Complexity**: 5
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - known contradictory outputs (for example Q6/Q9 current behavior) fail deterministically.
- **Validation**:
  - targeted tests in  and .

### Task 1.4: Sprint gate
- **Location**: , 
- **Description**: execute sprint-level regression gate.
- **Complexity**: 2
- **Dependencies**: Task 1.3
- **Acceptance Criteria**:
  - all sprint tests pass.
- **Validation**:
  - .........................                                                [100%]
25 passed in 6.56s

## Sprint 2: Topic-Scoped Evidence Construction
**Goal**: prevent cross-topic evidence contamination and ensure answer fields are built from the correct structured records.

**Demo/Validation**:
- per-topic answers only cite matching  doc kinds.
- no unrelated support snippet can satisfy strict expected tokens.

### Task 2.1: Enforce topic-local support selection
- **Location**:  (, topic display builders)
- **Description**: restrict support snippets and field hydration to doc-kind/topic mappings ( -> , etc.).
- **Complexity**: 7
- **Dependencies**: Sprint 1 complete
- **Acceptance Criteria**:
  - Q4 cannot inherit non-activity snippets; Q8/Q9 cannot pass from unrelated snippets.
- **Validation**:
  - extend  and .

### Task 2.2: Tighten observation graph pair merge precedence
- **Location**: 
- **Description**: ensure canonical structured pairs are not overwritten by noisy UI fact fragments; preserve ordered fields and exact key namespaces.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - deterministic  pairs for all ten Q topics.
- **Validation**:
  -  + new deterministic fixture assertions.

### Task 2.3: Normalize strict output fields for fragile topics
- **Location**: 
- **Description**: normalize timestamps/time formats, hostnames, test-command text, and ordered timeline rows before evaluation.
- **Complexity**: 5
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - equivalent evidence formats produce canonical strict-comparable values.
- **Validation**:
  - extend  and .

### Task 2.4: Sprint gate
- **Location**: 
- **Description**: run query/display/grounding regression suite.
- **Complexity**: 2
- **Dependencies**: Task 2.3
- **Acceptance Criteria**:
  - no regressions in advanced display and grounding tests.
- **Validation**:
  - .........................................                                [100%]
41 passed in 142.29s (0:02:22)

## Sprint 3: Close Advanced20 Remaining Mismatches
**Goal**: drive Advanced20 from mixed correctness to true strict pass.

**Demo/Validation**:
- strict advanced run reports  on the chosen report snapshot.

### Task 3.1: Q-series gap closure (Q1..Q10)
- **Location**: , 
- **Description**: harden extraction prompts and field mapping for currently weak cases (focus evidence exactness, calendar selected date, console color counts, browser hostname fields, dev tests command exactness).
- **Complexity**: 8
- **Dependencies**: Sprint 2 complete
- **Acceptance Criteria**:
  - Q1..Q10 strict evaluation each passes on fixed fixture run.
- **Validation**:
  - 

### Task 3.2: H-series deterministic field closure (H1..H10)
- **Location**: , 
- **Description**: ensure H outputs are always populated from structured fields with exact-key matching; no free-text fallback in strict mode.
- **Complexity**: 6
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - H1..H10 strict structured checks pass with exact values (or configured bbox IoU threshold for H10).
- **Validation**:
  - extend and run , .

### Task 3.3: Sprint gate
- **Location**: 
- **Description**: run full Advanced20 strict gate and archive deterministic output.
- **Complexity**: 2
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - strict artifact shows , , , .
- **Validation**:
  - 

## Sprint 4: Full Q40 Strict Gate and Report Integrity
**Goal**: achieve and prove full strict golden correctness with stable reports and no mixed-snapshot ambiguity.

**Demo/Validation**:
- Q40 matrix strict gate passes from one coherent capture snapshot.
- published report includes source artifact hashes and explicit strict-failure reasons schema.

### Task 4.1: Enforce single-snapshot provenance in evaluation reports
- **Location**: , {"ok": true, "out": "artifacts/advanced10/q40_matrix_latest.json", "matrix_total": 40, "matrix_failed": 0, "failure_reasons": []}
- **Description**: include report run ID + source report path checksum in every row/output; fail if mixed artifacts are combined.
- **Complexity**: 5
- **Dependencies**: Sprint 3 complete
- **Acceptance Criteria**:
  - impossible to present stale  and newer run as one status.
- **Validation**:
  - add tests in  and .

### Task 4.2: Run Generic20 + Advanced20 + matrix strict gate
- **Location**: {"event":"golden_qh.progress","pid":348569,"phase":"start","detail":"lock_acquired","ts_utc":"2026-02-19T15:54:17Z"}
{"event":"golden_qh.progress","pid":348569,"phase":"strict_override","detail":"forcing_skip_vlm_unstable=0","ts_utc":"2026-02-19T15:54:17Z"}
{"event":"golden_qh.progress","pid":348569,"phase":"preflight","detail":"checking_vllm","ts_utc":"2026-02-19T15:54:17Z"}
{"event":"golden_qh.progress","pid":348569,"phase":"preflight_failed","detail":"vllm_not_ready","ts_utc":"2026-02-19T15:55:20Z"}
{"ok":false,"error":"vllm_preflight_failed","base_url":"http://127.0.0.1:8000/v1","preflight":{"attempts": 61, "base_url": "http://127.0.0.1:8000/v1", "error": "models_unreachable:curl_failed:rc=7:curl: (7) Failed to connect to 127.0.0.1 port 8000 after 0 ms: Couldn't connect to server", "expected_model": "internvl3_5_8b", "final": {"base_url": "http://127.0.0.1:8000/v1", "error": "models_unreachable:curl_failed:rc=7:curl: (7) Failed to connect to 127.0.0.1 port 8000 after 0 ms: Couldn't connect to server", "expected_model": "internvl3_5_8b", "latency_ms": 4, "ok": false}, "initial": {"base_url": "http://127.0.0.1:8000/v1", "error": "models_unreachable:curl_failed:rc=7:curl: (7) Failed to connect to 127.0.0.1 port 8000 after 0 ms: Couldn't connect to server", "expected_model": "internvl3_5_8b", "latency_ms": 19, "ok": false}, "initial_error": "models_unreachable:curl_failed:rc=7:curl: (7) Failed to connect to 127.0.0.1 port 8000 after 0 ms: Couldn't connect to server", "latency_ms": 63381, "ok": false, "orchestrator": {"cmd": "bash /mnt/d/projects/hypervisor/tools/wsl/start_internvl35_8b_with_watch.sh", "detached": true, "latency_ms": 3001, "ok": true, "pid": 348587, "returncode": null}, "orchestrator_cmd": "bash /mnt/d/projects/hypervisor/tools/wsl/start_internvl35_8b_with_watch.sh", "watch_state": {"brain_statusz_http_status": "200", "brain_up": true, "completion_error": "probe_skipped_inflight:1.000 4.000", "completion_fail_streak": 0, "completion_latency_ms": null, "completion_ok": null, "configured_model": "brandonbeiler/InternVL3_5-8B-FP8-Dynamic", "embed_health_http_status": "200", "popup_auth_http_status": "200", "served_model": "internvl3_5_8b", "sidecar_health_http_status": "200", "sidecar_up": true, "tray_up": false, "ts_utc": "2026-02-19T15:55:16Z", "vllm_models_http_status": "200", "vllm_up": true, "watch_scope": "brain", "windows_sidecar_up": true}}}, , 
- **Description**: run end-to-end strict pipeline and capture final artifacts for both suites and combined matrix.
- **Complexity**: 4
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - matrix output: , , , strict .
- **Validation**:
  - {"ok": false, "error": "advanced20_not_found", "path": "artifacts/advanced10/advanced20_strict_latest.json"}

### Task 4.3: Update implementation matrices/reports
- **Location**: , , 
- **Description**: update outcomes, strict evidence rationale, and four-pillar traceability with final artifact references.
- **Complexity**: 3
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - docs reflect exact strict results and artifact paths; no stale “passed” claims.
- **Validation**:
  - manual diff review + targeted doc consistency checks.

## Testing Strategy
- Unit tests for strict evaluator semantics and contradiction detection.
- Integration tests for query topic display + observation graph grounding.
- Determinism checks with  in strict mode.
- Sprint gates executed after each sprint; failures block progression.

## Potential Risks & Gotchas
- **Cross-topic snippet leakage** can still reintroduce false positives.
  - Mitigation: strict topic-to-doc_kind allowlist checks and tests.
- **Normalization drift** may cause near-equal values to fail exact checks.
  - Mitigation: canonical format helpers + fixtures with known variants.
- **VLM nondeterminism** can destabilize strict runs.
  - Mitigation: deterministic env contract + bounded retries + repro gate.
- **Artifact staleness/mixing** can misreport status.
  - Mitigation: enforce source report hash/run-id in evaluator and matrix.

## Rollback Plan
- Keep strict path behind explicit evaluator mode flag for one release cycle.
- If regressions spike, revert scorer and topic-scoping changes only (Sprint 1+2 commits), retain provenance improvements.
- Preserve prior artifacts and document rollback reason in  before any gate override.
