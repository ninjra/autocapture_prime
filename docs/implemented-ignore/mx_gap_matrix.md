# Autocapture MX Gap Matrix (baseline)

Source blueprint: docs/autocapture_mx_blueprint.md
Spec extract: docs/spec/autocapture_mx_spec.yaml
Baseline date: 2026-01-25

Legend:
- PRESENT = required artifacts exist at the Appendix A paths and validators are already implemented.
- PARTIAL = similar behavior exists in NX, but paths/validators/spec coverage differ.
- MISSING = no equivalent artifacts found.

## Requirements

### MX-CONFIG-0001 — Configuration loader with safe defaults (offline, cloud disabled)
Status: PARTIAL
- Existing (NX): autocapture_nx/kernel/config.py, config/default.json, contracts/config_schema.json
- Missing (MX paths/tests): autocapture/config/models.py, autocapture/config/load.py, autocapture/config/defaults.py, tests/test_config_defaults.py
- Planned (Appendix A):
  - Artifacts: autocapture/config/models.py; autocapture/config/load.py; autocapture/config/defaults.py
  - Validators: python_import autocapture.config.load:load_config; unit_test tests/test_config_defaults.py

### MX-RETENTION-0001 — Archive-only user data management (no delete or purge surfaces)
Status: PARTIAL
- Existing (NX): autocapture_nx/cli.py (no delete/purge/wipe commands detected)
- Missing (MX paths/tests): autocapture/ux/facade.py, autocapture/web/api.py, HTTP route checks
- Planned (Appendix A):
  - Artifacts: autocapture/ux/facade.py; autocapture/web/api.py
  - Validators: cli_output_regex_absent (autocapture --help, delete/purge/wipe); http_routes_absent (/api/delete, /api/purge, /api/wipe)

### MX-CORE-0001 — Deterministic IDs + canonical hashing utilities
Status: PARTIAL
- Existing (NX): autocapture_nx/kernel/canonical_json.py; autocapture_nx/kernel/hashing.py
- Missing (MX paths/tests): autocapture/core/hashing.py, autocapture/core/ids.py, autocapture/core/jsonschema.py, tests/test_hashing_canonical.py, tests/test_ids_stable.py
- Planned (Appendix A):
  - Artifacts: autocapture/core/hashing.py; autocapture/core/ids.py; autocapture/core/jsonschema.py
  - Validators: unit_test tests/test_hashing_canonical.py; unit_test tests/test_ids_stable.py

### MX-PLUGIN-0001 — Plugin manifest schema + manager + discovery
Status: PARTIAL
- Existing (NX): autocapture_nx/plugin_system/registry.py; contracts/plugin_manifest.schema.json; plugins/**/plugin.json; config/plugin_locks.json
- Missing (MX paths/tests): autocapture/plugins/manifest.py, manager.py, kinds.py; tests/test_plugin_discovery_no_import.py; CLI JSON schema
- Planned (Appendix A):
  - Artifacts: autocapture/plugins/manifest.py; autocapture/plugins/manager.py; autocapture/plugins/kinds.py
  - Validators: python_import PluginManager + ExtensionManifest; unit_test tests/test_plugin_discovery_no_import.py; cli_json autocapture plugins list --json

### MX-KINDS-0001 — Plugin kind registry includes required baseline and MX kinds
Status: PARTIAL
- Existing (NX): kinds are implicit in plugins/**/plugin.json entrypoints
- Missing (MX paths/tests): autocapture/plugins/kinds.py; tests/test_plugin_kinds_registry.py
- Planned (Appendix A):
  - Artifacts: autocapture/plugins/kinds.py
  - Validators: unit_test tests/test_plugin_kinds_registry.py

### MX-PLUGSET-0001 — Built-in plugin set covers essential kinds and is enabled by default
Status: MISSING
- Existing (NX): plugins/builtin/** with builtin.* IDs; default_pack in config/default.json
- Missing (MX paths/tests): autocapture_plugins/ manifests with mx.* IDs; tests for required IDs/kinds; plugins verify-defaults CLI
- Planned (Appendix A):
  - Artifacts: autocapture_plugins/
  - Validators: plugins_have_ids (mx.* list); plugins_have_kinds (required kinds list); cli_exit autocapture plugins verify-defaults

### MX-PLUGIN-0002 — Plugin hot-swap for non-core plugins
Status: MISSING
- Existing (NX): no hot-swap support identified
- Missing (MX paths/tests): autocapture/plugins/manager.py hot-swap; tests/test_plugin_hotswap.py
- Planned (Appendix A):
  - Artifacts: autocapture/plugins/manager.py
  - Validators: unit_test tests/test_plugin_hotswap.py

### MX-PLUGIN-0003 — Safe mode restricts external plugins and blocks cloud egress
Status: PARTIAL
- Existing (NX): safe_mode config in autocapture_nx/kernel/config.py and autocapture_nx/plugin_system/registry.py; network allowlist in autocapture_nx/kernel/loader.py
- Missing (MX paths/tests): autocapture/plugins/policy_gate.py; (note: tests/test_safe_mode.py exists but targets NX paths/capabilities)
- Planned (Appendix A):
  - Artifacts: autocapture/plugins/manager.py; autocapture/plugins/policy_gate.py
  - Validators: unit_test tests/test_safe_mode.py

### MX-POLICY-0001 — PolicyGate enforced network egress control
Status: PARTIAL
- Existing (NX): autocapture_nx/plugin_system/runtime.py (network_guard); plugins/builtin/egress_gateway/plugin.py
- Missing (MX paths/tests): autocapture/plugins/policy_gate.py; autocapture/core/http.py; tests/test_policy_gate.py
- Planned (Appendix A):
  - Artifacts: autocapture/plugins/policy_gate.py; autocapture/core/http.py
  - Validators: python_import PolicyGate; unit_test tests/test_policy_gate.py

### MX-SAN-0001 — Egress sanitizer with deterministic entity hashing for text
Status: PARTIAL
- Existing (NX): plugins/builtin/egress_sanitizer/plugin.py; plugins/builtin/storage_encrypted/plugin.py (entity map); tests/test_sanitizer.py (NX behavior)
- Missing (MX paths/tests): autocapture/memory/entities.py; autocapture/ux/redaction.py; tests/test_entity_hashing_stable.py; tests/test_sanitizer_no_raw_pii.py
- Planned (Appendix A):
  - Artifacts: autocapture/memory/entities.py; autocapture/ux/redaction.py
  - Validators: unit_test tests/test_entity_hashing_stable.py; unit_test tests/test_sanitizer_no_raw_pii.py

### MX-GOV-0001 — RuntimeGovernor blocks heavy work during active interaction
Status: PARTIAL
- Existing (NX): plugins/builtin/runtime_governor/plugin.py
- Missing (MX paths/tests): autocapture/runtime/governor.py; autocapture/runtime/activity.py; autocapture/runtime/scheduler.py; autocapture/runtime/budgets.py; tests/test_governor_gating.py
- Planned (Appendix A):
  - Artifacts: autocapture/runtime/governor.py; autocapture/runtime/activity.py; autocapture/runtime/scheduler.py; autocapture/runtime/budgets.py
  - Validators: unit_test tests/test_governor_gating.py

### MX-LEASE-0001 — Work leases prevent duplicate processing and support cancellation
Status: MISSING
- Existing (NX): no lease subsystem identified
- Missing (MX paths/tests): autocapture/runtime/leases.py; tests/test_work_leases.py
- Planned (Appendix A):
  - Artifacts: autocapture/runtime/leases.py
  - Validators: unit_test tests/test_work_leases.py

### MX-STORE-0001 — Encrypted metadata DB + media blob encryption + portable keys
Status: PARTIAL
- Existing (NX): plugins/builtin/storage_encrypted/plugin.py; plugins/builtin/storage_sqlcipher/plugin.py; autocapture_nx/kernel/crypto.py; autocapture_nx/kernel/keyring.py; autocapture_nx/kernel/key_rotation.py
- Missing (MX paths/tests): autocapture/storage/database.py; autocapture/storage/sqlcipher.py; autocapture/storage/keys.py; autocapture/storage/media_store.py; autocapture/storage/blob_store.py; tests/test_key_export_import_roundtrip.py; tests/test_sqlcipher_roundtrip.py; tests/test_blob_encryption_roundtrip.py
- Planned (Appendix A):
  - Artifacts: autocapture/storage/database.py; autocapture/storage/sqlcipher.py; autocapture/storage/keys.py; autocapture/storage/media_store.py; autocapture/storage/blob_store.py
  - Validators: unit_test tests/test_key_export_import_roundtrip.py; unit_test tests/test_sqlcipher_roundtrip.py; unit_test tests/test_blob_encryption_roundtrip.py

### MX-LEDGER-0001 — Provenance ledger hash chain + verification CLI
Status: PARTIAL
- Existing (NX): plugins/builtin/ledger_basic/plugin.py (hash chain); plugins/builtin/journal_basic/plugin.py
- Missing (MX paths/tests): autocapture/pillars/citable.py; autocapture/storage/archive.py; tests/test_provenance_chain.py; CLI provenance verify
- Planned (Appendix A):
  - Artifacts: autocapture/pillars/citable.py; autocapture/core/hashing.py; autocapture/storage/archive.py
  - Validators: unit_test tests/test_provenance_chain.py; cli_exit autocapture provenance verify

### MX-RULES-0001 — Append-only rules ledger with state rebuild and query integration
Status: MISSING
- Existing (NX): no rules ledger identified
- Missing (MX paths/tests): autocapture/rules/ledger.py; autocapture/rules/store.py; autocapture/rules/schema.py; autocapture/rules/cli.py; tests/test_rules_ledger_append_only.py; tests/test_rules_state_rebuild.py
- Planned (Appendix A):
  - Artifacts: autocapture/rules/ledger.py; autocapture/rules/store.py; autocapture/rules/schema.py; autocapture/rules/cli.py
  - Validators: unit_test tests/test_rules_ledger_append_only.py; unit_test tests/test_rules_state_rebuild.py

### MX-CAPTURE-0001 — Capture pipeline writes durable spool records and encrypted screenshots
Status: PARTIAL
- Existing (NX): plugins/builtin/capture_windows/plugin.py; plugins/builtin/capture_stub/plugin.py; plugins/builtin/audio_windows/plugin.py; plugins/builtin/window_metadata_windows/plugin.py
- Missing (MX paths/tests): autocapture/capture/spool.py; autocapture/capture/pipelines.py; autocapture/capture/models.py; tests/test_capture_spool_idempotent.py
- Planned (Appendix A):
  - Artifacts: autocapture/capture/spool.py; autocapture/capture/pipelines.py; autocapture/capture/models.py
  - Validators: unit_test tests/test_capture_spool_idempotent.py

### MX-INGEST-0001 — Ingest pipeline produces normalized spans with stable IDs
Status: MISSING
- Existing (NX): no ingest normalization pipeline found
- Missing (MX paths/tests): autocapture/ingest/normalizer.py; autocapture/ingest/spans.py; tests/test_span_ids_stable.py; tests/test_span_bbox_norm.py
- Planned (Appendix A):
  - Artifacts: autocapture/ingest/normalizer.py; autocapture/ingest/spans.py
  - Validators: unit_test tests/test_span_ids_stable.py; unit_test tests/test_span_bbox_norm.py

### MX-TABLE-0001 — Table extractor supports structured + image + pdf strategies
Status: MISSING
- Existing (NX): no table extractor plugins or registry
- Missing (MX paths/tests): autocapture/plugins/kinds.py entries + table extractor implementation; tests/test_table_extractor_strategies.py
- Planned (Appendix A):
  - Artifacts: autocapture/plugins/kinds.py
  - Validators: unit_test tests/test_table_extractor_strategies.py

### MX-INDEX-0001 — Lexical indexing via SQLite FTS5 for events and threads
Status: MISSING
- Existing (NX): retrieval uses storage.metadata_store without FTS
- Missing (MX paths/tests): autocapture/indexing/lexical.py; tests/test_fts_query_returns_hits.py
- Planned (Appendix A):
  - Artifacts: autocapture/indexing/lexical.py
  - Validators: unit_test tests/test_fts_query_returns_hits.py

### MX-INDEX-0002 — Vector indexing using embedder plugins and vector backend
Status: MISSING
- Existing (NX): embedder_stub plugin only; no vector index
- Missing (MX paths/tests): autocapture/indexing/vector.py; tests/test_vector_index_roundtrip.py
- Planned (Appendix A):
  - Artifacts: autocapture/indexing/vector.py
  - Validators: unit_test tests/test_vector_index_roundtrip.py

### MX-INDEX-0003 — Local Qdrant sidecar supported as vector backend
Status: MISSING
- Existing (NX): none
- Missing (MX paths/tests): autocapture/indexing/vector.py; autocapture/tools/vendor_windows_binaries.py; tests/test_qdrant_sidecar_healthcheck.py
- Planned (Appendix A):
  - Artifacts: autocapture/indexing/vector.py; autocapture/tools/vendor_windows_binaries.py
  - Validators: unit_test tests/test_qdrant_sidecar_healthcheck.py

### MX-GRAPH-0001 — Graph adapter interface + optional retrieval tier integration
Status: MISSING
- Existing (NX): none
- Missing (MX paths/tests): autocapture/indexing/graph.py; tests/test_graph_adapter_contract.py
- Planned (Appendix A):
  - Artifacts: autocapture/indexing/graph.py
  - Validators: unit_test tests/test_graph_adapter_contract.py

### MX-RETR-0001 — Tiered retrieval (FAST/FUSION/RERANK) + deterministic fusion
Status: PARTIAL
- Existing (NX): plugins/builtin/retrieval_basic/plugin.py; plugins/builtin/reranker_stub/plugin.py; autocapture_nx/kernel/query.py
- Missing (MX paths/tests): autocapture/retrieval/tiers.py; autocapture/retrieval/fusion.py; autocapture/retrieval/rerank.py; autocapture/retrieval/signals.py; tests/test_rrf_fusion_determinism.py; tests/test_tier_planner_escalation.py
- Planned (Appendix A):
  - Artifacts: autocapture/retrieval/tiers.py; autocapture/retrieval/fusion.py; autocapture/retrieval/rerank.py; autocapture/retrieval/signals.py
  - Validators: unit_test tests/test_rrf_fusion_determinism.py; unit_test tests/test_tier_planner_escalation.py

### MX-CTX-0001 — Context pack JSON + TRON formats with retrieval signals
Status: MISSING
- Existing (NX): none
- Missing (MX paths/tests): autocapture/memory/context_pack.py; tests/test_context_pack_formats.py
- Planned (Appendix A):
  - Artifacts: autocapture/memory/context_pack.py; autocapture/retrieval/signals.py
  - Validators: unit_test tests/test_context_pack_formats.py

### MX-ANS-0001 — Claim-level citations + citation validation + verifier enforced
Status: PARTIAL
- Existing (NX): plugins/builtin/answer_basic/plugin.py; plugins/builtin/citation_basic/plugin.py; autocapture_nx/kernel/query.py
- Missing (MX paths/tests): autocapture/memory/answer_orchestrator.py; autocapture/memory/citations.py; autocapture/memory/verifier.py; autocapture/memory/conflict.py; tests/test_citation_validation.py; tests/test_verifier_enforced.py; tests/test_conflict_reporting.py
- Planned (Appendix A):
  - Artifacts: autocapture/memory/answer_orchestrator.py; autocapture/memory/citations.py; autocapture/memory/verifier.py; autocapture/memory/conflict.py
  - Validators: unit_test tests/test_citation_validation.py; unit_test tests/test_verifier_enforced.py; unit_test tests/test_conflict_reporting.py

### MX-GATEWAY-0001 — OpenAI-compatible gateway enforces schema + stage routing + policy gate
Status: MISSING
- Existing (NX): none (no FastAPI gateway)
- Missing (MX paths/tests): autocapture/gateway/app.py; autocapture/gateway/router.py; autocapture/gateway/schemas.py; tests/test_gateway_schema_enforced.py; tests/test_gateway_policy_block_cloud_default.py
- Planned (Appendix A):
  - Artifacts: autocapture/gateway/app.py; autocapture/gateway/router.py; autocapture/gateway/schemas.py
  - Validators: unit_test tests/test_gateway_schema_enforced.py; unit_test tests/test_gateway_policy_block_cloud_default.py

### MX-UX-0001 — UX Facade is the single surface for UI and CLI parity
Status: MISSING
- Existing (NX): none
- Missing (MX paths/tests): autocapture/ux/facade.py; autocapture/ux/models.py; tests/test_ux_facade_parity.py
- Planned (Appendix A):
  - Artifacts: autocapture/ux/facade.py; autocapture/ux/models.py
  - Validators: python_import UXFacade; unit_test tests/test_ux_facade_parity.py

### MX-SETTINGS-0001 — Tiered settings schema + preview tokens + apply confirmation
Status: MISSING
- Existing (NX): none
- Missing (MX paths/tests): autocapture/ux/settings_schema.py; autocapture/ux/preview_tokens.py; autocapture/web/routes/settings.py; tests/test_settings_preview_tokens.py
- Planned (Appendix A):
  - Artifacts: autocapture/ux/settings_schema.py; autocapture/ux/preview_tokens.py; autocapture/web/routes/settings.py
  - Validators: unit_test tests/test_settings_preview_tokens.py; http_endpoint GET /api/settings/schema

### MX-WEB-0001 — Web Console API routes present and return validated schemas
Status: MISSING
- Existing (NX): none
- Missing (MX paths/tests): autocapture/web/api.py; autocapture/web/routes/query.py; autocapture/web/routes/citations.py; autocapture/web/routes/plugins.py; autocapture/web/routes/health.py; autocapture/web/routes/metrics.py; tests/test_* web validators
- Planned (Appendix A):
  - Artifacts: autocapture/web/api.py; autocapture/web/routes/query.py; autocapture/web/routes/citations.py; autocapture/web/routes/plugins.py; autocapture/web/routes/health.py; autocapture/web/routes/metrics.py
  - Validators: http_endpoint GET /api/health; http_endpoint POST /api/query

### MX-CIT-OVERLAY-0001 — Citation overlay API for bounding boxes and source rendering
Status: MISSING
- Existing (NX): none
- Missing (MX paths/tests): autocapture/web/routes/citations.py; tests/test_citation_overlay_contract.py
- Planned (Appendix A):
  - Artifacts: autocapture/web/routes/citations.py
  - Validators: unit_test tests/test_citation_overlay_contract.py

### MX-DOCTOR-0001 — Doctor report summarizes environment and binary availability
Status: PARTIAL
- Existing (NX): autocapture_nx/cli.py (doctor); autocapture_nx/kernel/loader.py (doctor checks)
- Missing (MX paths/tests): autocapture/ux/models.py; autocapture/web/routes/health.py; tests/test_doctor_report_schema.py
- Planned (Appendix A):
  - Artifacts: autocapture/ux/models.py; autocapture/web/routes/health.py
  - Validators: unit_test tests/test_doctor_report_schema.py

### MX-OBS-0001 — Observability via OTel traces and Prometheus metrics
Status: PARTIAL
- Existing (NX): plugins/builtin/observability_basic/plugin.py (file logger); tests/test_observability.py (NX)
- Missing (MX paths/tests): autocapture/web/routes/metrics.py; tests/test_metrics_endpoint_exposes_counters.py; OTel/Prometheus integrations
- Planned (Appendix A):
  - Artifacts: autocapture/web/routes/metrics.py
  - Validators: unit_test tests/test_metrics_endpoint_exposes_counters.py

### MX-EXPORT-0001 — Export/import bundles with manifest + hash verification
Status: MISSING
- Existing (NX): none
- Missing (MX paths/tests): autocapture/storage/archive.py; tests/test_export_import_roundtrip.py
- Planned (Appendix A):
  - Artifacts: autocapture/storage/archive.py
  - Validators: unit_test tests/test_export_import_roundtrip.py

### MX-VENDOR-0001 — Vendor binaries tool supports Qdrant and FFmpeg with hash verification
Status: MISSING
- Existing (NX): none
- Missing (MX paths/tests): autocapture/tools/vendor_windows_binaries.py; tests/test_vendor_binaries_hashcheck.py
- Planned (Appendix A):
  - Artifacts: autocapture/tools/vendor_windows_binaries.py
  - Validators: unit_test tests/test_vendor_binaries_hashcheck.py

### MX-PROMPTOPS-0001 — PromptOps propose/validate/evaluate/apply with deterministic diffs
Status: MISSING
- Existing (NX): none
- Missing (MX paths/tests): autocapture/promptops/propose.py; validate.py; evaluate.py; patch.py; github.py; tests/test_promptops_validation.py
- Planned (Appendix A):
  - Artifacts: autocapture/promptops/propose.py; autocapture/promptops/validate.py; autocapture/promptops/evaluate.py; autocapture/promptops/patch.py; autocapture/promptops/github.py
  - Validators: unit_test tests/test_promptops_validation.py

### MX-TRAIN-0001 — Training pipelines (LoRA + DPO) with reproducible manifests
Status: MISSING
- Existing (NX): none
- Missing (MX paths/tests): autocapture/training/pipelines.py; autocapture/training/lora.py; autocapture/training/dpo.py; autocapture/training/datasets.py; tests/test_training_manifest_schema.py
- Planned (Appendix A):
  - Artifacts: autocapture/training/pipelines.py; autocapture/training/lora.py; autocapture/training/dpo.py; autocapture/training/datasets.py
  - Validators: unit_test tests/test_training_manifest_schema.py

### MX-RESEARCH-0001 — Research scout with caching and diff thresholding
Status: MISSING
- Existing (NX): none
- Missing (MX paths/tests): autocapture/research/scout.py; autocapture/research/cache.py; autocapture/research/diff.py; tests/test_research_scout_cache.py
- Planned (Appendix A):
  - Artifacts: autocapture/research/scout.py; autocapture/research/cache.py; autocapture/research/diff.py
  - Validators: unit_test tests/test_research_scout_cache.py

### MX-GATE-0001 — Pillar gate suite available and wired to codex
Status: MISSING
- Existing (NX): none
- Missing (MX paths/tests): autocapture/tools/pillar_gate.py; privacy_scanner.py; provenance_gate.py; coverage_gate.py; latency_gate.py; retrieval_sensitivity.py; conflict_gate.py; integrity_gate.py; CLI codex pillar-gates
- Planned (Appendix A):
  - Artifacts: autocapture/tools/pillar_gate.py; autocapture/tools/privacy_scanner.py; autocapture/tools/provenance_gate.py; autocapture/tools/coverage_gate.py; autocapture/tools/latency_gate.py; autocapture/tools/retrieval_sensitivity.py; autocapture/tools/conflict_gate.py; autocapture/tools/integrity_gate.py
  - Validators: cli_exit autocapture codex pillar-gates

### MX-CODEX-0001 — Codex CLI validates against this blueprint spec
Status: MISSING
- Existing (NX): tools/validate_blueprint_spec.py; tests/test_blueprint_spec_validation.py (NX spec checks only)
- Missing (MX paths/tests): autocapture/codex/cli.py; autocapture/codex/spec.py; autocapture/codex/validators.py; autocapture/codex/report.py; codex validate CLI
- Planned (Appendix A):
  - Artifacts: autocapture/codex/cli.py; autocapture/codex/spec.py; autocapture/codex/validators.py; autocapture/codex/report.py
  - Validators: cli_exit autocapture codex validate --json
