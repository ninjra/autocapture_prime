# JEPA State Layer Recon (PHASE 1)

**Generated**: 2026-02-01
**Scope**: Implement State Layer + plugins per `docs/jepa plan.md` and `docs/jepa-specs.md` before any code changes.

## 1) Current pipeline stages & extension points
- **SST pipeline stages**: defined in `autocapture_nx/processing/sst/pipeline.py` (`_STAGE_NAMES`). Stage hooks are dispatched via capability `processing.stage.hooks` using `SSTStagePluginBase` in `autocapture_nx/processing/sst/stage_plugins.py`.
- **On-demand extraction**: `autocapture_nx/kernel/query.py::extract_on_demand` triggers SST pipeline when on-query extraction is enabled.
- **Idle processing**: `autocapture_nx/processing/idle.py::IdleProcessor` handles OCR/VLM extraction and optionally SST pipeline on idle.
- **Query orchestration**: `autocapture_nx/kernel/query.py::run_query` uses `retrieval.strategy` + `answer.builder`.

## 2) Core subsystems locations
- **Plugin registry / DI container**: `autocapture_nx/plugin_system/registry.py`, capabilities exposed via `PluginBase.capabilities()`.
- **Job scheduler / background worker**: `autocapture/runtime/scheduler.py`, `autocapture/runtime/conductor.py`, `autocapture/runtime/governor.py`.
- **Artifact store + encryption boundary**: storage plugins in `plugins/builtin/storage_sqlcipher/plugin.py` and `plugins/builtin/storage_encrypted/plugin.py`.
- **Database schema & migrations**: SQLCipher and SQLite stores initialize schema inline (`plugins/builtin/storage_sqlcipher/plugin.py`, `autocapture/storage/sqlcipher.py`). No dedicated migration framework; schema changes are additive `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE`.

## 3) Inventory: files/modules to modify/add
### New modules
- `autocapture_nx/state_layer/` package:
  - `contracts.py` (schema validation)
  - `ids.py` (deterministic IDs/cache keys)
  - `store_sqlite.py` (state tape store)
  - `builder_jepa.py` (StateBuilderPlugin)
  - `vector_index.py` (LinearScanVectorIndex)
  - `vector_index_sqlite.py` (optional SQLite vector/time-series index)
  - `evidence_compiler.py` (EvidenceCompilerPlugin)
  - `retrieval.py` (QueryEvidenceBundle API)
  - `policy_gate.py` (Policy boundary)

### Existing modules to modify
- `autocapture_nx/processing/sst/pipeline.py` (emit frame evidence id + pass into state)
- `autocapture_nx/processing/idle.py` (state tape generation on idle)
- `autocapture_nx/kernel/query.py` (route to state-layer retrieval when enabled)
- `autocapture_nx/ux/facade.py` (expose state query)
- `autocapture/web/routes/query.py` (add `/api/state/query` endpoint)
- `plugins/builtin/storage_sqlcipher/plugin.py` (state tape DB + capability)
- `autocapture_nx/plugin_system/contracts.py` (I/O schemas for state capabilities)
- `contracts/config_schema.json`, `config/default.json` (state layer config + budgets)
- `autocapture/ux/plugin_options.py`, `autocapture/web/ui/app.js` (settings UI)
- `contracts/evidence.schema.json` (explicit frame evidence requirements)
- `autocapture/promptops/engine.py` + prompt sources (state-layer prompt bundle)
- `docs/jepa-specs.md` coverage map + new ADRs

### New plugin wrappers (builtin)
- `plugins/builtin/state_jepa_like/*`
- `plugins/builtin/state_vector_linear/*`
- `plugins/builtin/state_vector_sqlite_ts/*`
- `plugins/builtin/state_evidence_compiler/*`
- `plugins/builtin/state_retrieval/*`
- `plugins/builtin/state_policy/*`
- `plugins/builtin/state_workflow_miner/*`
- `plugins/builtin/state_anomaly/*`
- `plugins/builtin/state_jepa_training/*`

## 4) New DB tables / migrations
- SQLite state tape DB (separate file, SQLCipher when available):
  - `state_span`, `state_edge`, `state_evidence_link`
  - Indexes: `idx_state_span_time`, `idx_state_span_session`, `idx_state_edge_from_to`
- Evidence schema extension for `evidence.capture.frame` to include `segment_id`, `frame_index`, `image_sha256`, `width`, `height`, `ts_utc`.

## 5) Config flags / feature gating
- `processing.state_layer.enabled` (default false)
- `processing.state_layer.query_enabled` (default false)
- `processing.state_layer.builder_plugin_id` / `vector_index_plugin_id` / `evidence_compiler_plugin_id` / `policy_plugin_id`
- `processing.state_layer.windowing_mode`, `window_ms`, `app_change_boundary`
- `performance.state_layer.*` budgets: ingestion regression %, query p95 ms, storage growth MB/day

## 6) Mapping changes to new components
- **StateBuilderPlugin**: `autocapture_nx/state_layer/builder_jepa.py` + `plugins/builtin/state_jepa_like`
- **EvidenceCompilerPlugin**: `autocapture_nx/state_layer/evidence_compiler.py`
- **StateTape storage**: `autocapture_nx/state_layer/store_sqlite.py` + storage plugin capability
- **VectorIndexPlugin**: `autocapture_nx/state_layer/vector_index.py` (linear) + optional sqlite
- **QueryEvidenceBundle API + policy gate**: `autocapture_nx/state_layer/retrieval.py` + `policy_gate.py` + `autocapture_nx/kernel/query.py`

## 7) Risks
- **Performance hot paths**: vector query + edge expansion; must bound hops and use deterministic ordering.
- **Security boundaries**: ensure no raw artifacts passed to LLM; policy gate must be enforced.
- **Determinism pitfalls**: embedding projection and pooling must be stable; must avoid float nondeterminism.
- **Schema migration hazards**: SQLCipher availability varies; must fail closed if encryption is required.

## 8) Test plan (high-level)
- Contracts: evidence/provenance required; schema validation for state objects.
- Determinism: same inputs/config -> same IDs/cache keys.
- Policy gate: no raw export when disabled.
- Query behavior: stable evidence references; no-evidence path returns literal "no evidence".
- Regression gates: ingest/query performance budgets; state accuracy harness.

## 9) Rollout plan (feature flags)
- Default flags off in config.
- Enable state tape generation only after validation in dev.
- Enable `/api/state/query` before routing `/api/query` to state-layer.
- Full rollout requires passing DO_NOT_SHIP gates and synthetic accuracy harness.
