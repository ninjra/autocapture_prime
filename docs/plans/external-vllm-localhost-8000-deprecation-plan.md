# Plan: External vLLM Localhost 8000 Deprecation

**Generated**: 2026-02-13
**Estimated Complexity**: High

## Overview
Deprecate all local vLLM launch/orchestration behavior in this repo and make `http://127.0.0.1:8000` an always-external dependency.  
This repo must never start/stop/manage vLLM; it must only perform health/model compatibility checks and fail closed with actionable diagnostics.

## Prerequisites
- External sidecar/hypervisor repo serves vLLM on `127.0.0.1:8000`.
- OpenAI-compatible routes available: `/health`, `/v1/models`, `/v1/chat/completions`.
- Agreement on one of:
  - Server accepts explicit `model` from this repo, or
  - Server has a default model and ignores/overrides client `model` safely.

## Sprint 0: Launch-Surface Inventory and Guardrail
**Goal**: Freeze launch-surface growth before refactors and produce exact scope.
**Demo/Validation**:
- Inventory artifact lists all launch/start/probe call sites.
- CI guard test fails on reintroduction of launch patterns.

### Task 0.1: Build launch-surface inventory
- **Location**: `docs/reports/vllm_launch_surface_inventory_2026-02-13.md` (new)
- **Description**: Enumerate all launch and implicit-launch code paths, including shell/PowerShell scripts and Python subprocess usage.
- **Complexity**: 3/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - Includes at least: `tools/vllm_service.sh`, `tools/vllm_probe.sh`, `tools/start_vllm.ps1`, `tools/install_vllm.ps1`, `tools/vllm_foreground_probe.ps1`, `tools/wsl_vllm_log.ps1`, `tools/run_full_pipeline.ps1`, `tools/run_fixture_pipeline.ps1`, `tools/model_prep.ps1`, `tools/query_latest_single.py`, `tools/run_advanced10_queries.py`.
- **Validation**:
  - Manual cross-check against repo grep results.

### Task 0.2: Add forbidden-pattern guard test
- **Location**: `tests/test_no_local_vllm_launch_patterns.py` (new)
- **Description**: Add deterministic static guard that fails CI when launch patterns appear in runtime/tooling code.
- **Complexity**: 5/10
- **Dependencies**: Task 0.1
- **Acceptance Criteria**:
  - Fails on patterns like `python -m vllm.entrypoints.openai.api_server`, `start_vllm.ps1`, `vllm_service.sh start`, `subprocess.*vllm`.
- **Validation**:
  - Run targeted pytest and verify failing fixture catches synthetic violation.

## Sprint 1: Contract-First Externalization
**Goal**: Define one authoritative external-vLLM contract and remove ambiguity from runtime assumptions.
**Demo/Validation**:
- New contract doc exists and is linked from blueprint/matrix docs.
- A single health-check command reports pass/fail for `127.0.0.1:8000` without launching anything.

### Task 1.1: Author external vLLM contract doc
- **Location**: `docs/contracts/vllm_external_localhost_8000.md`
- **Description**: Specify required endpoints, response schema/version compatibility, timeout behavior, error codes, model-selection policy, and fail-closed behavior.
- **Complexity**: 4/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - Defines required routes: `/health`, `/v1/models`, `/v1/chat/completions`.
  - Defines hard pin to `http://127.0.0.1:8000` for this repo (no host/port override path).
  - Defines localhost-only enforcement and no-launch policy.
  - Defines troubleshooting/error mapping consumed by tools/runtime.
- **Validation**:
  - Markdown lint/manual review.

### Task 1.2: Link contract into implementation authority docs
- **Location**: `docs/blueprints/autocapture_nx_blueprint.md`, `docs/blueprints/feature_completeness_gap_matrix.md`, `docs/reports/implementation_matrix_remaining_2026-02-12.md`, `docs/spec/feature_completeness_spec.md`
- **Description**: Update docs so all vLLM ownership statements reference external sidecar ownership and this repo’s consumer-only role.
- **Complexity**: 3/10
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - No doc claims local vLLM launch responsibility.
  - Matrix rows updated with status + source-of-truth links.
- **Validation**:
  - Grep for stale local-launch language returns none in target docs.

## Sprint 2: Runtime Deprecation (No Local Launch)
**Goal**: Runtime/query/processing paths always target localhost:8000 and never attempt local launch.
**Demo/Validation**:
- Query/eval flows run with external server only.
- If server is unavailable, response is deterministic fail-closed with explicit remediation.

### Task 2.2: Centralize endpoint policy in inference utility
- **Location**: `autocapture_nx/inference/vllm_endpoint.py` (new), `autocapture_nx/kernel/query.py`, `autocapture_nx/inference/openai_compat.py`
- **Description**: Create shared resolver/probe utility hard-pinned to `http://127.0.0.1:8000`, with localhost enforcement, timeout defaults, and schema checks.
- **Complexity**: 6/10
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Runtime uses shared resolver (no duplicated endpoint literals in changed files).
  - Non-`127.0.0.1:8000` endpoint use is rejected in this repo.
- **Validation**:
  - New tests for resolver defaults and policy enforcement.

### Task 2.1: Remove `_ensure_vllm` launch behavior from query tools
- **Location**: `tools/query_latest_single.py`, `tools/run_advanced10_queries.py`
- **Description**: Replace launch calls with `check_vllm_ready()` diagnostics using Sprint 2.2 shared utility.
- **Complexity**: 5/10
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - No subprocess call to `tools/vllm_service.sh` remains in these files.
  - Tool outputs include `vllm_status` probe results (reachable, models listed, latency, schema status).
- **Validation**:
  - Unit tests for probe behavior and fail-closed output.

### Task 2.3: Remove runtime dependency on local model paths
- **Location**: `autocapture_nx/kernel/query.py`, `tools/process_single_screenshot.py`, `tools/query_latest_single.py`, `tools/run_advanced10_queries.py`
- **Description**: Deprecate local model fallback paths like `/var/tmp/autocapture_models/*`; make model selection server-driven or configured by API contract.
- **Complexity**: 5/10
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - No hardcoded local filesystem model fallback remains in runtime query path.
  - Errors explicitly state model negotiation failure vs endpoint failure.
- **Validation**:
  - Query tests pass when server provides models list.
  - Negative tests verify deterministic error when model unavailable.

## Sprint 3: Tooling and Script Deprecation
**Goal**: Deprecate/remove local launch scripts and update pipeline scripts to probe-only behavior.
**Demo/Validation**:
- Running deprecated launcher scripts prints deprecation + migration message and exits non-zero.
- Pipeline scripts no longer invoke local vLLM start routines.

### Task 3.1: Remove launcher calls from orchestration and prep scripts
- **Location**: `tools/run_full_pipeline.ps1`, `tools/run_fixture_pipeline.ps1`, `tools/model_prep.ps1`
- **Description**: Replace launch calls (`start_vllm` paths) with readiness probes and fail-closed status.
- **Complexity**: 6/10
- **Dependencies**: Sprint 2 complete
- **Acceptance Criteria**:
  - No launch subprocess branch remains.
  - `tools/model_prep.ps1` no longer downgrades to local-only on server-unavailable; it fail-closes with external dependency status.
  - Probe failures produce actionable remediation text.
- **Validation**:
  - PowerShell tests/smoke runs against reachable and unreachable localhost endpoint.

### Task 3.2: Deprecate launch scripts and wrappers
- **Location**: `tools/vllm_service.sh`, `tools/vllm_probe.sh`, `tools/start_vllm.ps1`, `tools/install_vllm.ps1`, `tools/vllm_foreground_probe.ps1`, `tools/wsl_vllm_log.ps1`
- **Description**: Convert scripts to deprecation stubs or archive under `tools/deprecated/` with clear migration text to sidecar-owned command.
- **Complexity**: 4/10
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Scripts do not launch vLLM.
  - Each script points to sidecar-owned startup command and contract doc.
- **Validation**:
  - Script execution returns deterministic deprecation output.

### Task 3.3: Update plugin metadata and capability statements
- **Location**: `plugins/builtin/vlm_vllm_localhost/plugin.json`, `plugins/builtin/ocr_nemotron_torch/plugin.json`, `plugins/builtin/embedder_vllm_localhost/plugin.json`, `plugins/builtin/answer_synth_vllm_localhost/plugin.json`
- **Description**: Ensure descriptors state “external localhost dependency” and remove any implied launch ownership.
- **Complexity**: 3/10
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Capability docs are consistent with externalized ownership.
  - No plugin metadata implies start/stop control.
- **Validation**:
  - Metadata grep + plugin lock regeneration smoke.

## Sprint 4: Verification, Metrics, and Rollout
**Goal**: Confirm end-to-end behavior and make regressions visible.
**Demo/Validation**:
- Query/eval works with external vLLM serving on port 8000.
- All launcher-related tests/docs updated and passing.

### Task 4.1: Add regression tests for no-launch guarantee
- **Location**: `tests/test_query_tools_external_vllm_only.py` (new), `tests/test_openai_compat_localhost.py` (extend)
- **Description**: Assert query/eval tools never spawn launch scripts and only perform probes.
- **Complexity**: 6/10
- **Dependencies**: Sprint 2 + Sprint 3
- **Acceptance Criteria**:
  - Tests fail if launch subprocess call is reintroduced.
  - Tests verify fail-closed message quality when endpoint unavailable.
- **Validation**:
  - `pytest -q` targeted suite.

### Task 4.2: Add observability plus append-only audit events for dependency status
- **Location**: `tools/query_latest_single.py`, `tools/run_advanced10_queries.py`, `autocapture_nx/kernel/query.py`, `autocapture_nx/kernel/ledger.py` (or equivalent audit path)
- **Description**: Record endpoint reachability, model list success, schema compatibility, and latency in artifacts and append-only audit records.
- **Complexity**: 5/10
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Output artifacts include vLLM probe metadata.
  - Append-only audit log contains probe outcome events with stable fields.
  - Failures distinguish network, route, and schema/model errors.
- **Validation**:
  - Run one success and one failure scenario and verify artifact fields.
  - Verify audit chain integrity after probe events.

### Task 4.3: Update implementation matrix and deprecation ledger
- **Location**: `docs/blueprints/feature_completeness_gap_matrix.md`, `docs/reports/feature_completeness_tracker.md`, `docs/reports/implementation_matrix_remaining_2026-02-12.md`, `docs/spec/feature_completeness_spec.md`
- **Description**: Mark launcher ownership removed, external dependency enforced, and residual risks.
- **Complexity**: 3/10
- **Dependencies**: Sprint 4 prior tasks
- **Acceptance Criteria**:
  - Matrix reflects new ownership and completion status.
  - Residual risk list includes external service availability dependency.
- **Validation**:
  - Manual doc review + diff audit.

## Testing Strategy
- Unit tests:
  - Endpoint resolver behavior, localhost enforcement, probe parsing.
  - No-launch guarantee tests for query/eval scripts.
- Integration tests:
  - External vLLM reachable on `127.0.0.1:8000` -> queries complete.
  - Endpoint down -> deterministic fail-closed output with remediation.
- Contract compatibility tests:
  - Validate schema/required fields for `/health`, `/v1/models`, `/v1/chat/completions`.
- Performance tests:
  - Probe overhead budget (p50/p95) and timeout budget enforcement.
- Accuracy/citeability regression:
  - Run advanced query suite and verify citation-bearing outputs under healthy external service.
  - Verify deterministic, cited indeterminate/failure output when service unavailable.
- Regression checks:
  - Grep for local launch invocations in runtime/query code paths.
  - Verify deprecated scripts do not start processes.

## Potential Risks & Gotchas
- External sidecar availability introduces startup-order dependency.
  - Mitigation: explicit probe-and-fail messaging; no silent fallback.
- Model ID mismatch between client payload and external server.
  - Mitigation: contract-driven model negotiation; clear incompatibility errors.
- Hidden launch branches in legacy PowerShell tooling.
  - Mitigation: scripted grep + tests asserting launch-free behavior.
- Docs drift can reintroduce ownership confusion.
  - Mitigation: single contract doc linked from matrix/blueprint.

## Rollback Plan
- Keep deprecation changes on feature branch until query/eval regression suite passes.
- If externalization breaks critical flows:
  - Revert to last known good commit in this repo.
  - Keep sidecar contract doc and tests for re-implementation.
- Invariant: rollback must not reintroduce local vLLM launch behavior in this repo.
- No data deletion required; rollback is code/config only.
