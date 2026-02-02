# Plan: JEPA State Layer Plugin

**Generated**: 2026-02-01
**Estimated Complexity**: High

## Overview
Implement the JEPA State Layer as a new plugin-driven subsystem: deterministic StateSpan/StateEdge generation, append-only state tape storage, evidence/provenance enforcement, vector search, evidence bundle compilation, and an evidence-only query/LLM contract (no evidence -> no answer). Integrate with the existing NX plugin system, idle processing (foreground gating), policy gate, promptops prompt bundles, and audit logging. Introduce explicit frame evidence records for citations. Ship behind feature flags (default off) with regression gates and full SRC coverage mapping.

## Prerequisites (recommended decisions for 4 pillars + UX)
- **State tape DB**: separate SQLCipher-backed DB file (e.g., `data/state_tape.db`) to isolate write-heavy state tape data and keep metadata DB lean. If `storage.encryption_required=true` and SQLCipher is unavailable, fail closed by keeping the state layer disabled and emitting a clear diagnostic.
- **When to run**: state tape generation runs **idle-only** (via `IdleProcessor`) to avoid UX impact; optional on-query backfill allowed only when idle and within budgets.
- **Embeddings**: multi-modal (text, ROI/vision, layout, input events) with deterministic pooling. If ROI/vision embeddings are missing, use deterministic image hashing as a fallback (not preferred but compliant).
- **Evidence**: introduce explicit `evidence.capture.frame` records (derived from segments) and use those as `EvidenceRef.media_id` targets.
- **API**: add `/api/state/query` returning `QueryEvidenceBundle`. Keep `/api/query` stable; when feature flag enabled, it should internally route to state-layer retrieval but preserve response shape for existing UX.
- **Budgets**: define defaults in config (overridable): ingestion regression max 10%, query p95 <= `performance.query_latency_ms` (default 2000ms), storage growth <= 1024 MB/day.
- **Accuracy golden set**: create a deterministic synthetic golden set fixture + harness; allow real dataset override paths later.
- **Optional plugins**: ship stubs now (workflow miner, anomaly, JEPA training gate) and keep disabled by default.
- **Proposed plugin IDs** (manifest/plugin_id): `builtin.state.builder.jepa_like`, `builtin.state.vector.linear`, `builtin.state.vector.sqlite_ts` (optional), `builtin.state.evidence.compiler`, `builtin.state.retrieval`, `builtin.state.policy`.

## Sprint 1: Recon + Contracts + Scaffolding (PHASE 1 compliance)
**Goal**: Produce the required pre-edit recon artifact and establish schemas, config, and plugin capability scaffolding.
**Demo/Validation**:
- `docs/reports/jepa_state_layer_recon.md` exists and maps all change points to new components.
- Schema validation rejects missing EvidenceRef/ProvenanceRecord.

### Task 1.1: Produce Codex PHASE 1 recon artifact
- **Location**: `docs/reports/jepa_state_layer_recon.md`
- **Description**: Inventory current pipeline stages, plugin registry, job scheduler, storage boundaries, and migration framework. List files to modify/add, DB tables/migrations, and feature flags. Map changes to StateBuilder, EvidenceCompiler, StateTape storage, VectorIndex, QueryEvidenceBundle API/PolicyGate. Include risks and rollout plan (flags default off).
- **Complexity**: 3
- **Dependencies**: None
- **Acceptance Criteria**:
  - Recon includes file-path inventory, migration plan, test plan, rollout plan.
  - Risks list covers perf, security boundaries, determinism, migrations.
- **Validation**:
  - Manual review against SRC-101..SRC-107.

### Task 1.2: Add state-layer data contract schemas + validators
- **Location**: `contracts/state_layer.schema.json`, `autocapture_nx/state_layer/contracts.py`
- **Description**: Define EvidenceRef, ProvenanceRecord, StateSpan, StateEdge, QueryEvidenceBundle schemas and validator helpers. Provide deterministic validation errors.
- **Complexity**: 5
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Validation fails when EvidenceRef[] or ProvenanceRecord missing.
  - QueryEvidenceBundle schema enforces policy fields.
- **Validation**:
  - New tests: `tests/test_state_contracts.py`.

### Task 1.3: Deterministic hashing + ID helpers
- **Location**: `autocapture_nx/state_layer/ids.py`
- **Description**: Implement config hash, cache key, embedding hash, and deterministic ID derivation per SRC-048/SRC-089 using canonical JSON and stable byte preimages.
- **Complexity**: 4
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Same inputs/config/model_version produce identical IDs and cache keys.
- **Validation**:
  - New tests: `tests/test_state_ids_deterministic.py`.

### Task 1.4: Config schema + defaults + feature flags
- **Location**: `contracts/config_schema.json`, `config/default.json`, `autocapture/ux/plugin_options.py`
- **Description**: Add `processing.state_layer` config block (enabled flag, plugin IDs, windowing mode, pooling params, vector index settings, budgets) with defaults off. Add `performance.state_layer` budgets (ingestion regression %, query p95 ms, storage growth MB/day). Surface settings in UX plugin options.
- **Complexity**: 4
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Default config disables state layer and evidence-only query path.
  - Settings schema validates new config paths.
- **Validation**:
  - Update/extend `tests/test_config_defaults.py`.

### Task 1.5: Plugin capability + I/O contract scaffolding
- **Location**: `autocapture_nx/plugin_system/contracts.py`, `contracts/state_builder_input.schema.json`, `contracts/state_builder_output.schema.json`, `contracts/state_retrieval_input.schema.json`, `contracts/state_retrieval_output.schema.json`
- **Description**: Register new capability contracts: `state.builder`, `state.index`, `state.evidence.compiler`, `state.retrieval`. Add input/output schemas for each. Define plugin manifest permissions (no network, least-privilege filesystem) and required_capabilities for the new plugins.
- **Complexity**: 5
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Capability calls are schema-validated and audited.
  - State-layer plugins default to sandboxed, local-only permissions.
- **Validation**:
  - Extend `tests/test_plugin_io_contracts.py` with state-layer cases.

### Task 1.6: ADR + coverage scaffolding
- **Location**: `docs/adr/ADR-00xx-state-layer.md`, `docs/adr/ADR-00xx-evidence-provenance.md`, `docs/adr/ADR-00xx-state-retrieval.md`, `docs/reports/implementation_matrix.md` (or new `docs/reports/jepa_implementation_matrix.md`)
- **Description**: Add ADRs for State Layer, Evidence/Provenance, Plugin types, Storage/Indexing, Evidence-only retrieval. Update coverage mapping to reference module/ADR/test per SRC.
- **Complexity**: 4
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Each SRC in jepa-specs has module + ADR + test references.
- **Validation**:
  - Update `tests/test_blueprint_spec_validation.py` if needed.

### Task 1.7: Codex verification prompt artifact
- **Location**: `docs/reports/jepa_codex_verification_prompt.md` (or `docs/promptops/jepa_codex_verification_prompt.md` if prompt artifacts are centralized there)
- **Description**: Add the exact PHASE 1/PHASE 2 verification prompt from jepa plan/spec as a standalone artifact referenced by the coverage map.
- **Complexity**: 2
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Prompt text matches the spec verbatim (no edits).
- **Validation**:
  - Manual diff against `docs/jepa plan.md` section 8.

### Task 1.8: State-layer plugin manifests + allowlist scaffolding
- **Location**: `plugins/builtin/*/plugin.json`, `config/default.json`, `autocapture_nx/plugin_system/registry.py`
- **Description**: Add manifests for state-layer plugins (builder/index/compiler/retrieval/policy/optional stubs) with least-privilege permissions, required_capabilities, and sandbox filesystem policies. Update plugin allowlist defaults.
- **Complexity**: 4
- **Dependencies**: Task 1.5
- **Acceptance Criteria**:
  - State-layer plugins are disabled by default and sandboxed.
  - Allowlist includes new plugin IDs for opt-in use.
- **Validation**:
  - Extend `tests/test_plugin_loader.py` and `tests/test_plugin_capability_policies.py`.

## Sprint 2: State Tape Store + Baseline State Builder
**Goal**: Persist StateSpan/StateEdge in SQLite and generate baseline JEPA-like state tape deterministically.
**Demo/Validation**:
- State tape tables created with indexes.
- StateBuilder plugin produces deterministic spans/edges with evidence + provenance.

### Task 2.1: Implement StateTape SQLite store + migration
- **Location**: `autocapture_nx/state_layer/store_sqlite.py`, `autocapture_nx/kernel/paths.py`, `plugins/builtin/storage_sqlcipher/plugin.py` (schema extension or new store capability)
- **Description**: Add `state_span`, `state_edge`, `state_evidence_link` tables and indexes in a **separate** SQLCipher DB file. Enforce append-only inserts and expose `storage.state_tape` capability. Fail closed when SQLCipher is required but unavailable.
- **Complexity**: 7
- **Dependencies**: Task 1.3, Task 1.4
- **Acceptance Criteria**:
  - Tables exist with required indexes.
  - No UPDATE/DELETE operations on state objects.
-- **Validation**:
  - New tests: `tests/test_state_store_schema.py`, `tests/test_state_append_only.py`, `tests/test_state_store_encryption_required.py`.

### Task 2.2: Explicit frame evidence records
- **Location**: `autocapture_nx/capture/pipeline.py`, `autocapture_nx/kernel/metadata_store.py`, `contracts/evidence.schema.json`
- **Description**: Emit `evidence.capture.frame` records that reference the source segment + frame_index + timestamps. Avoid duplicating raw bytes; decode from segment when exporting unless explicit frame storage is enabled.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - EvidenceRef.media_id references `evidence.capture.frame` records.
  - Frame evidence records are append-only and validated by evidence schema.
- **Validation**:
  - New tests: `tests/test_frame_evidence_records.py`, `tests/test_evidence_ref_frame_link.py`.

### Task 2.3: Evidence + provenance persistence gate
- **Location**: `autocapture_nx/state_layer/validator.py`, `autocapture_nx/state_layer/store_sqlite.py`
- **Description**: Block persistence if EvidenceRef[] or ProvenanceRecord missing. Enforce EvidenceRef structure and sha256 references.
- **Complexity**: 5
- **Dependencies**: Task 1.2, Task 2.1
- **Acceptance Criteria**:
  - Missing evidence/provenance fails fast (DO_NOT_SHIP gate).
- **Validation**:
  - New tests: `tests/test_state_provenance_gate.py`.

### Task 2.4: Baseline JEPA-like StateBuilderPlugin
- **Location**: `autocapture_nx/state_layer/builder_jepa.py`, `plugins/builtin/state_jepa_like/plugin.py`, `plugins/builtin/state_jepa_like/plugin.json`
- **Description**: Implement deterministic windowing (fixed duration or app/window-change), pooling for **text + ROI/vision + layout + input** embeddings, deterministic projection to dim 768, delta and pred_error, and deterministic IDs. Provide deterministic fallback embedding via image hash + text hash when embedder signals are missing. Attach EvidenceRef + ProvenanceRecord.
- **Complexity**: 8
- **Dependencies**: Task 1.2, Task 1.3, Task 2.1
- **Acceptance Criteria**:
  - Output IDs derived from inputs + plugin + config + model_version.
  - pred_error = 1 - cosine(z_t, z_{t-1}).
- **Validation**:
  - New tests: `tests/test_state_builder_determinism.py`, `tests/test_state_builder_pred_error.py`.

### Task 2.5: Integrate state builder with pipeline + foreground gating
- **Location**: `autocapture_nx/processing/idle.py`, `autocapture_nx/processing/sst/pipeline.py`, `autocapture/runtime/governor.py`, `autocapture/runtime/conductor.py`
- **Description**: Hook state builder to run only when allowed (idle + budgets). If inline pipeline integration is chosen, ensure heavy work is skipped when user is ACTIVE. Record telemetry for runs.
- **Complexity**: 7
- **Dependencies**: Task 2.4
- **Acceptance Criteria**:
  - ACTIVE user state blocks state tape generation.
  - CPU/RAM budgets enforced.
- **Validation**:
  - Extend `tests/test_governor_gating.py`; add `tests/test_state_foreground_gating.py`.

### Task 2.6: State layer audit + ledger events
- **Location**: `autocapture_nx/kernel/event_builder.py`, `autocapture_nx/kernel/audit.py`, `autocapture_nx/state_layer/store_sqlite.py`
- **Description**: Emit ledger events for state tape writes; ensure plugin exec audit logs state builder calls and rows written.
- **Complexity**: 4
- **Dependencies**: Task 2.1, Task 2.4
- **Acceptance Criteria**:
  - Audit rows exist for state tape operations.
- **Validation**:
  - Extend `tests/test_plugin_exec_audit.py` or add `tests/test_state_audit.py`.

## Sprint 3: Vector Index + Retrieval + Evidence Compiler + LLM Contract
**Goal**: Enable evidence-only retrieval and answering over the state tape.
**Demo/Validation**:
- Query returns QueryEvidenceBundle; empty hits return literal "no evidence".
- Inline citations reference EvidenceRef.media_id + timestamps.

### Task 3.1: LinearScanVectorIndex plugin
- **Location**: `autocapture_nx/state_layer/vector_index.py`, `plugins/builtin/state_vector_linear/plugin.py`, `plugins/builtin/state_vector_linear/plugin.json`
- **Description**: Provide deterministic topK over StateSpan embeddings with staleness checks `(state_id, embedding_hash, model_version)`.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Stable ordering for equal scores.
  - Stale embeddings rejected.
- **Validation**:
  - New tests: `tests/test_state_vector_index.py`.

### Task 3.1b: Optional SQLite vector/time-series index plugin
- **Location**: `autocapture_nx/state_layer/vector_index_sqlite.py`, `plugins/builtin/state_vector_sqlite_ts/plugin.py`, `plugins/builtin/state_vector_sqlite_ts/plugin.json`
- **Description**: Optional plugin that uses a SQLite vector/time-series table if available (no heavy deps). Must be snapshot/versioned and deterministic; fallback to linear scan when unavailable.
- **Complexity**: 5
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Deterministic build or versioned snapshot.
  - Staleness checks enforced.
- **Validation**:
  - New tests: `tests/test_state_vector_sqlite_optional.py`.

### Task 3.2: EvidenceCompilerPlugin
- **Location**: `autocapture_nx/state_layer/evidence_compiler.py`, `plugins/builtin/state_evidence_compiler/plugin.py`, `plugins/builtin/state_evidence_compiler/plugin.json`
- **Description**: Deterministically assemble QueryEvidenceBundle from StateSpan hits and EvidenceRefs; enforce policy.can_export_text for text snippets.
- **Complexity**: 6
- **Dependencies**: Task 1.2, Task 3.1
- **Acceptance Criteria**:
  - Evidence selection rules versioned and deterministic.
- **Validation**:
  - New tests: `tests/test_state_evidence_compiler.py`.

### Task 3.3: Retrieval API service (QueryEvidenceBundle)
- **Location**: `autocapture_nx/state_layer/retrieval.py`, `autocapture_nx/kernel/query.py`, `autocapture_nx/ux/facade.py`, `autocapture/web/routes/query.py`
- **Description**: Implement retrieval sequence: parse question -> structured filters -> vector search -> edge expansion -> evidence compilation -> policy gate. Add `/api/state/query` for QueryEvidenceBundle; keep `/api/query` stable and internally route to state-layer when enabled.
- **Complexity**: 8
- **Dependencies**: Task 2.1, Task 3.1, Task 3.2
- **Acceptance Criteria**:
  - No raw store browsing; LLM sees only evidence bundle.
  - Continuity expansion over StateEdge graph is deterministic.
- **Validation**:
  - New tests: `tests/test_state_retrieval_bundle.py`, `tests/test_state_edge_walk.py`.

### Task 3.4: LLM orchestrator evidence-only contract + PromptOps integration
- **Location**: `autocapture_nx/kernel/query.py` (or new `autocapture_nx/kernel/state_query.py`), `autocapture/memory/answer_orchestrator.py`, `autocapture/promptops/engine.py`, `promptops/sources/`
- **Description**: Enforce "no evidence" response when hits empty. Generate answers using only evidence bundle and permitted summaries; include inline citations referencing EvidenceRef.media_id + ts. Add PromptOps bundle sources/prompts for state-layer query/answer (e.g., `promptops/sources/state_query.md`) and wire via `prompt.bundle` capability with a repo default when `promptops.bundle_root` is empty.
- **Complexity**: 7
- **Dependencies**: Task 3.3
- **Acceptance Criteria**:
  - If hits empty -> literal "no evidence".
  - If hits exist -> citations are present and validated.
- **Validation**:
  - New tests: `tests/test_state_no_evidence.py`, `tests/test_state_citation_format.py`.

### Task 3.5: PolicyGate enforcement between retrieval and LLM
- **Location**: `autocapture_nx/state_layer/policy_gate.py`, `plugins/builtin/meta_policy_noop/plugin.py` (if extended)
- **Description**: Enforce app allow/deny, redaction/egress policy at boundary; ensure sanitization only on explicit export; log policy decisions.
- **Complexity**: 4
- **Dependencies**: Task 3.3
- **Acceptance Criteria**:
  - Disallowed payloads never reach LLM.
- **Validation**:
  - New tests: `tests/test_state_policy_gate.py`.

## Sprint 4: Rollout + Optional Modules + Gates + Coverage
**Goal**: Ship behind flags, add optional plugin scaffolds, and satisfy coverage/gates.
**Demo/Validation**:
- Flags default off; enabling switches query path to state layer.
- All DO_NOT_SHIP gates covered by tests.

### Task 4.1: Feature flags + UI/UX surfacing
- **Location**: `config/default.json`, `contracts/config_schema.json`, `autocapture/ux/plugin_options.py`, `autocapture/web/ui/app.js`
- **Description**: Add feature flags for state layer, retrieval path, and optional plugins; default off. Surface in UI settings.
- **Complexity**: 4
- **Dependencies**: Task 3.4
- **Acceptance Criteria**:
  - Flags control enable/disable behavior deterministically.
- **Validation**:
  - New tests: `tests/test_state_feature_flags.py`.

### Task 4.2: Optional plugins (WorkflowMiner, Anomaly, JEPA Training)
- **Location**: `autocapture_nx/state_layer/workflow_miner.py`, `autocapture_nx/state_layer/anomaly.py`, `autocapture_nx/state_layer/jepa_training.py`, plus plugin wrappers in `plugins/builtin/`
- **Description**: Provide optional, versioned stubs with strict gating. Training plugin must refuse unsigned/mismatched models.
- **Complexity**: 5
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Optional plugins are disabled by default and deterministic when enabled.
- **Validation**:
  - New tests: `tests/test_state_optional_plugins_disabled.py`, `tests/test_state_training_gate.py`.

### Task 4.3: DO_NOT_SHIP gates + budgets
- **Location**: `tools/gate_perf.py`, `tools/gate_pillars.py`, `config/default.json`, `tests/test_state_gates.py`
- **Description**: Add explicit gates for provenance completeness, determinism, no-evidence path, citation correctness, and latency budgets. Enforce budgets from config (`performance.state_layer.*`).
- **Complexity**: 6
- **Dependencies**: Task 3.4
- **Acceptance Criteria**:
  - Gates fail when any DO_NOT_SHIP condition triggers.
-- **Validation**:
  - Run `tools/run_all_tests.py` and ensure gates pass.

### Task 4.4: Accuracy golden set harness (synthetic default)
- **Location**: `tests/fixtures/state_golden.json`, `tools/gate_state_accuracy.py`, `tests/test_state_accuracy_golden.py`
- **Description**: Add a deterministic synthetic golden set and harness; allow overriding with real datasets via config/env. Fails closed on regression relative to the synthetic baseline.
- **Complexity**: 5
- **Dependencies**: Task 3.4
- **Acceptance Criteria**:
  - Golden harness runs in CI and passes with synthetic data.
  - Override path documented for real data.
- **Validation**:
  - `tests/test_state_accuracy_golden.py`.

### Task 4.5: Coverage map + ADR/doc updates
- **Location**: `docs/jepa-specs.md`, `docs/reports/implementation_matrix.md` (or new `docs/reports/jepa_implementation_matrix.md`), `docs/adr/ADR-00xx-*.md`
- **Description**: Update Coverage_Map to reference concrete modules/ADRs/tests. Add Sources lists to new ADRs and modules.
- **Complexity**: 5
- **Dependencies**: All prior tasks
- **Acceptance Criteria**:
  - Every SRC has an implemented module/ADR/test reference.
- **Validation**:
  - Manual checklist against jepa-specs Validation_Checklist.

## Testing Strategy
- Unit tests: state contracts, deterministic IDs, state builder determinism, vector index ordering, evidence compiler ordering, frame evidence records.
- Integration tests: retrieval -> evidence bundle -> answer flow; no-evidence path; policy gate enforcement; feature flags; PromptOps prompt wiring.
- Regression gates: run `tools/run_all_tests.py` and ensure `tools/gate_perf.py`, `tools/gate_security.py`, `tools/gate_state_accuracy.py`, and DO_NOT_SHIP checks pass.

## Potential Risks & Gotchas
- Missing budgets/golden set definitions can block DO_NOT_SHIP gates; default synthetic golden set mitigates but may not reflect real workloads.
- ROI/vision embeddings may be unavailable; deterministic fallback must still be stable and clearly marked in provenance.
- SQLCipher availability varies; if encryption_required and SQLCipher missing, state layer must stay disabled (fail closed) to avoid violating security rules.
- Explicit frame evidence records can increase storage; keep them as metadata pointers to segments unless explicit frame bytes are enabled.
- PromptOps bundle root defaults to data dir; ensure repo-supplied default sources are discoverable to avoid empty prompts.
- Edge expansion could be expensive; ensure bounded hops and deterministic ordering.

## Rollback Plan
- Disable state layer feature flags; leave state tape DB intact (append-only, no deletions).
- Revert query path to existing retrieval/answer builder.
- Keep migration additive; no schema rollbacks required.
