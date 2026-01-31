# Autocapture MX Implementation Plan

Source blueprint: docs/autocapture_mx_blueprint.md
Spec extract: docs/spec/autocapture_mx_spec.yaml
Baseline date: 2026-01-25

Goals
- Implement Appendix A requirements with offline-first, deterministic behavior.
- Preserve NX behavior where functionally equivalent, using adapters when possible.
- Keep changes additive; avoid modifying existing NX behavior unless equivalence is proven.

Repo conventions and constraints
- Language: Python (pyproject.toml), no network, no sudo, no global tooling.
- Tests: `./dev.sh test` runs `python3 tools/run_all_tests.py` (unittest discovery).
- CLI: argparse in `autocapture_nx/cli.py` (keep argparse for MX CLI to avoid new deps).
- Config: JSON default in `config/default.json`, schema in `contracts/config_schema.json`.
- Plugin manifests: JSON `plugin.json` with schema `contracts/plugin_manifest.schema.json`, lockfile `config/plugin_locks.json`.
- CI: none detected; dev harness is the canonical local/CI parity runner.
- Fail closed: if a command or dependency is unclear, add TODOs instead of guessing.

Dependency graph (high level)
- Config -> Core hashing/ids -> Storage keys/crypto -> Plugin system -> PolicyGate/EgressClient
- Runtime governor + leases -> Capture -> Ingest -> Indexing -> Retrieval -> Answering
- UX facade + Settings -> Gateway + Web API -> Observability + Doctor
- Export/import + Ledger -> Tools (vendor + pillar gates) -> Codex validators

Strategy
- Add a new top-level `autocapture/` package with MX paths and thin adapters to NX where safe.
- Use `docs/spec/autocapture_mx_spec.yaml` as the authoritative Codex spec source.
- Avoid new dependencies; reuse stdlib and existing deps in pyproject.toml.
- Where NX already meets a requirement, create adapter modules under `autocapture/` to prove equivalence and satisfy Appendix A paths/tests.

Milestones (ordered)
1) Config + Core hashing/ids + Spec wiring (MX-CONFIG-0001, MX-CORE-0001, MX-CODEX-0001 scaffolding)
2) Plugin system + kinds + default plugin set (MX-PLUGIN-0001/2/3, MX-KINDS-0001, MX-PLUGSET-0001)
3) PolicyGate/Egress + Sanitizer + Runtime governor/leases (MX-POLICY-0001, MX-SAN-0001, MX-GOV-0001, MX-LEASE-0001)
4) Storage + Ledger + Export/Import (MX-STORE-0001, MX-LEDGER-0001, MX-EXPORT-0001)
5) Capture + Ingest + Indexing + Retrieval + Context + Answering (MX-CAPTURE-0001, MX-INGEST-0001, MX-INDEX-0001/2/3, MX-GRAPH-0001, MX-RETR-0001, MX-CTX-0001, MX-ANS-0001, MX-TABLE-0001)
6) UX + Settings + Gateway + Web + Observability + Doctor (MX-UX-0001, MX-SETTINGS-0001, MX-GATEWAY-0001, MX-WEB-0001, MX-CIT-OVERLAY-0001, MX-OBS-0001, MX-DOCTOR-0001, MX-RETENTION-0001)
7) Vendor binaries + PromptOps + Training + Research + Pillar gates + Codex validate (MX-VENDOR-0001, MX-PROMPTOPS-0001, MX-TRAIN-0001, MX-RESEARCH-0001, MX-GATE-0001, MX-CODEX-0001)

Build order and early gate tests
| Group | Modules | Primary deliverables | Gate tests (early) |
| --- | --- | --- | --- |
| A | MOD-001..005 | autocapture CLI + config + core utils + plugin system + autocapture_plugins manifests | tests/test_config_defaults.py; tests/test_plugin_discovery_no_import.py; tests/test_plugin_kinds_registry.py; tests/test_policy_gate.py |
| B | MOD-006..011 | redaction + runtime governor/leases + storage v2 + capture spool/pipeline | tests/test_sanitizer_no_raw_pii.py; tests/test_governor_gating.py; tests/test_work_leases.py; tests/test_capture_spool_idempotent.py; tests/test_sqlcipher_roundtrip.py |
| C | MOD-012..017 | ingest -> indexing -> retrieval -> context -> answers | tests/test_span_ids_stable.py; tests/test_fts_query_returns_hits.py; tests/test_vector_index_roundtrip.py; tests/test_context_pack_formats.py; tests/test_citation_validation.py |
| D | MOD-018..021 | gateway + web + citation overlay + UX + settings | tests/test_gateway_schema_enforced.py; tests/test_gateway_policy_block_cloud_default.py; tests/test_citation_overlay_contract.py; tests/test_ux_facade_parity.py; tests/test_settings_preview_tokens.py |
| E | MOD-022..030 | doctor + obs + export + vendor + promptops + training/research stubs + pillar gates + codex CLI | tests/test_doctor_report_schema.py; tests/test_metrics_endpoint_exposes_counters.py; tests/test_export_import_roundtrip.py; tests/test_vendor_binaries_hashcheck.py; tests/test_promptops_validation.py |
| F | MOD-031 | Appendix A required test files present and enforced | tests/test_blueprint_spec_validation.py; unittest discovery; codex validate CLI |

Hard rules (acceptance criteria)
- HR-003 single HTTP surface: all egress via autocapture/core/http.py; PolicyGate denies non-gateway.
- HR-004 privacy: no keystroke text capture, even if config enables raw input.
- HR-005/006 append-only: put-if-absent + strong IDs; idempotent same-content puts allowed; overwrites forbidden.
- HR-008 DO_NOT_SHIP: missing required tests or CLI commands fails deterministically.

Traceability map (validators -> owners)
| Requirement ID | Validators (tests/CLI/http) | Owning MX paths |
| --- | --- | --- |
| MX-CONFIG-0001 | python_import autocapture.config.load:load_config; tests/test_config_defaults.py | autocapture/config/models.py; autocapture/config/load.py; autocapture/config/defaults.py |
| MX-RETENTION-0001 | cli_output_regex_absent autocapture --help; http_routes_absent /api/delete|/api/purge|/api/wipe | autocapture/ux/facade.py; autocapture/web/api.py |
| MX-CORE-0001 | tests/test_hashing_canonical.py; tests/test_ids_stable.py | autocapture/core/hashing.py; autocapture/core/ids.py; autocapture/core/jsonschema.py |
| MX-PLUGIN-0001 | python_import PluginManager + ExtensionManifest; tests/test_plugin_discovery_no_import.py; autocapture plugins list --json | autocapture/plugins/manifest.py; autocapture/plugins/manager.py; autocapture/plugins/kinds.py |
| MX-KINDS-0001 | tests/test_plugin_kinds_registry.py | autocapture/plugins/kinds.py |
| MX-PLUGSET-0001 | plugins_have_ids; plugins_have_kinds; autocapture plugins verify-defaults | autocapture_plugins/ |
| MX-PLUGIN-0002 | tests/test_plugin_hotswap.py | autocapture/plugins/manager.py |
| MX-PLUGIN-0003 | tests/test_safe_mode.py | autocapture/plugins/manager.py; autocapture/plugins/policy_gate.py |
| MX-POLICY-0001 | python_import PolicyGate; tests/test_policy_gate.py | autocapture/plugins/policy_gate.py; autocapture/core/http.py |
| MX-SAN-0001 | tests/test_entity_hashing_stable.py; tests/test_sanitizer_no_raw_pii.py | autocapture/memory/entities.py; autocapture/ux/redaction.py |
| MX-GOV-0001 | tests/test_governor_gating.py | autocapture/runtime/governor.py; autocapture/runtime/activity.py; autocapture/runtime/scheduler.py; autocapture/runtime/budgets.py |
| MX-LEASE-0001 | tests/test_work_leases.py | autocapture/runtime/leases.py |
| MX-STORE-0001 | tests/test_key_export_import_roundtrip.py; tests/test_sqlcipher_roundtrip.py; tests/test_blob_encryption_roundtrip.py | autocapture/storage/database.py; autocapture/storage/sqlcipher.py; autocapture/storage/keys.py; autocapture/storage/media_store.py; autocapture/storage/blob_store.py |
| MX-LEDGER-0001 | tests/test_provenance_chain.py; autocapture provenance verify | autocapture/pillars/citable.py; autocapture/core/hashing.py; autocapture/storage/archive.py |
| MX-RULES-0001 | tests/test_rules_ledger_append_only.py; tests/test_rules_state_rebuild.py | autocapture/rules/ledger.py; autocapture/rules/store.py; autocapture/rules/schema.py; autocapture/rules/cli.py |
| MX-CAPTURE-0001 | tests/test_capture_spool_idempotent.py | autocapture/capture/spool.py; autocapture/capture/pipelines.py; autocapture/capture/models.py |
| MX-INGEST-0001 | tests/test_span_ids_stable.py; tests/test_span_bbox_norm.py | autocapture/ingest/normalizer.py; autocapture/ingest/spans.py |
| MX-TABLE-0001 | tests/test_table_extractor_strategies.py | autocapture/plugins/kinds.py |
| MX-INDEX-0001 | tests/test_fts_query_returns_hits.py | autocapture/indexing/lexical.py |
| MX-INDEX-0002 | tests/test_vector_index_roundtrip.py | autocapture/indexing/vector.py |
| MX-INDEX-0003 | tests/test_qdrant_sidecar_healthcheck.py | autocapture/indexing/vector.py; autocapture/tools/vendor_windows_binaries.py |
| MX-GRAPH-0001 | tests/test_graph_adapter_contract.py | autocapture/indexing/graph.py |
| MX-RETR-0001 | tests/test_rrf_fusion_determinism.py; tests/test_tier_planner_escalation.py | autocapture/retrieval/tiers.py; autocapture/retrieval/fusion.py; autocapture/retrieval/rerank.py; autocapture/retrieval/signals.py |
| MX-CTX-0001 | tests/test_context_pack_formats.py | autocapture/memory/context_pack.py; autocapture/retrieval/signals.py |
| MX-ANS-0001 | tests/test_citation_validation.py; tests/test_verifier_enforced.py; tests/test_conflict_reporting.py | autocapture/memory/answer_orchestrator.py; autocapture/memory/citations.py; autocapture/memory/verifier.py; autocapture/memory/conflict.py |
| MX-GATEWAY-0001 | tests/test_gateway_schema_enforced.py; tests/test_gateway_policy_block_cloud_default.py | autocapture/gateway/app.py; autocapture/gateway/router.py; autocapture/gateway/schemas.py |
| MX-UX-0001 | python_import autocapture.ux.facade:UXFacade; tests/test_ux_facade_parity.py | autocapture/ux/facade.py; autocapture/ux/models.py |
| MX-SETTINGS-0001 | tests/test_settings_preview_tokens.py; http_endpoint GET /api/settings/schema | autocapture/ux/settings_schema.py; autocapture/ux/preview_tokens.py; autocapture/web/routes/settings.py |
| MX-WEB-0001 | http_endpoint GET /api/health; POST /api/query | autocapture/web/api.py; autocapture/web/routes/query.py; autocapture/web/routes/citations.py; autocapture/web/routes/plugins.py; autocapture/web/routes/health.py; autocapture/web/routes/metrics.py |
| MX-CIT-OVERLAY-0001 | tests/test_citation_overlay_contract.py | autocapture/web/routes/citations.py |
| MX-DOCTOR-0001 | tests/test_doctor_report_schema.py | autocapture/ux/models.py; autocapture/web/routes/health.py |
| MX-OBS-0001 | tests/test_metrics_endpoint_exposes_counters.py | autocapture/web/routes/metrics.py |
| MX-EXPORT-0001 | tests/test_export_import_roundtrip.py | autocapture/storage/archive.py |
| MX-VENDOR-0001 | tests/test_vendor_binaries_hashcheck.py | autocapture/tools/vendor_windows_binaries.py |
| MX-PROMPTOPS-0001 | tests/test_promptops_validation.py | autocapture/promptops/propose.py; autocapture/promptops/validate.py; autocapture/promptops/evaluate.py; autocapture/promptops/patch.py; autocapture/promptops/github.py |
| MX-TRAIN-0001 | tests/test_training_manifest_schema.py | autocapture/training/pipelines.py; autocapture/training/lora.py; autocapture/training/dpo.py; autocapture/training/datasets.py |
| MX-RESEARCH-0001 | tests/test_research_scout_cache.py | autocapture/research/scout.py; autocapture/research/cache.py; autocapture/research/diff.py |
| MX-GATE-0001 | autocapture codex pillar-gates | autocapture/tools/pillar_gate.py; autocapture/tools/privacy_scanner.py; autocapture/tools/provenance_gate.py; autocapture/tools/coverage_gate.py; autocapture/tools/latency_gate.py; autocapture/tools/retrieval_sensitivity.py; autocapture/tools/conflict_gate.py; autocapture/tools/integrity_gate.py |
| MX-CODEX-0001 | autocapture codex validate --json | autocapture/codex/cli.py; autocapture/codex/spec.py; autocapture/codex/validators.py; autocapture/codex/report.py |

Requirement checklist (Appendix A)

MX-CONFIG-0001
- Artifacts: autocapture/config/models.py; autocapture/config/load.py; autocapture/config/defaults.py
- Validation: python_import autocapture.config.load:load_config; unit_test tests/test_config_defaults.py
- Minimal implementation: wrap or port NX config loader; defaults must keep offline=true and cloud disabled.

MX-RETENTION-0001
- Artifacts: autocapture/ux/facade.py; autocapture/web/api.py
- Validation: cli_output_regex_absent (autocapture --help); http_routes_absent (/api/delete|/api/purge|/api/wipe)
- Minimal implementation: ensure CLI and web router contain no delete/purge/wipe surfaces or routes.

MX-CORE-0001
- Artifacts: autocapture/core/hashing.py; autocapture/core/ids.py; autocapture/core/jsonschema.py
- Validation: unit_test tests/test_hashing_canonical.py; tests/test_ids_stable.py
- Minimal implementation: canonical JSON + stable hashing (prefer blake3 if available; otherwise document fallback and test expectations).

MX-PLUGIN-0001
- Artifacts: autocapture/plugins/manifest.py; autocapture/plugins/manager.py; autocapture/plugins/kinds.py
- Validation: python_import PluginManager + ExtensionManifest; unit_test tests/test_plugin_discovery_no_import.py; cli_json autocapture plugins list --json
- Minimal implementation: manifest parsing/validation, discovery without importing plugin code, list command returns plugins + extensions.

MX-KINDS-0001
- Artifacts: autocapture/plugins/kinds.py
- Validation: unit_test tests/test_plugin_kinds_registry.py
- Minimal implementation: registry contains all required kinds listed in Appendix A.

MX-PLUGSET-0001
- Artifacts: autocapture_plugins/
- Validation: plugins_have_ids; plugins_have_kinds; cli_exit autocapture plugins verify-defaults
- Minimal implementation: built-in manifests for required mx.* IDs, enabled by default, kind coverage passes.

MX-PLUGIN-0002
- Artifacts: autocapture/plugins/manager.py
- Validation: unit_test tests/test_plugin_hotswap.py
- Minimal implementation: hot-swap non-core plugins at safe boundaries (not mid-request).

MX-PLUGIN-0003
- Artifacts: autocapture/plugins/manager.py; autocapture/plugins/policy_gate.py
- Validation: unit_test tests/test_safe_mode.py
- Minimal implementation: safe mode restricts external plugins; cloud egress blocked by policy.

MX-POLICY-0001
- Artifacts: autocapture/plugins/policy_gate.py; autocapture/core/http.py
- Validation: python_import PolicyGate; unit_test tests/test_policy_gate.py
- Minimal implementation: PolicyGate decision logic for offline/cloud/sanitizer; EgressClient is sole network path.

MX-SAN-0001
- Artifacts: autocapture/memory/entities.py; autocapture/ux/redaction.py
- Validation: unit_test tests/test_entity_hashing_stable.py; tests/test_sanitizer_no_raw_pii.py
- Minimal implementation: deterministic entity hashing and redaction pipeline; no raw PII in egress.

MX-GOV-0001
- Artifacts: autocapture/runtime/governor.py; autocapture/runtime/activity.py; autocapture/runtime/scheduler.py; autocapture/runtime/budgets.py
- Validation: unit_test tests/test_governor_gating.py
- Minimal implementation: block heavy work during ACTIVE_INTERACTION; degrade deterministically.

MX-LEASE-0001
- Artifacts: autocapture/runtime/leases.py
- Validation: unit_test tests/test_work_leases.py
- Minimal implementation: lease manager supports cancellation and prevents duplicate processing.

MX-STORE-0001
- Artifacts: autocapture/storage/database.py; autocapture/storage/sqlcipher.py; autocapture/storage/keys.py; autocapture/storage/media_store.py; autocapture/storage/blob_store.py
- Validation: unit_test tests/test_key_export_import_roundtrip.py; tests/test_sqlcipher_roundtrip.py; tests/test_blob_encryption_roundtrip.py
- Minimal implementation: encrypted metadata + blob storage; portable key export/import; SQLCipher if available (fail closed otherwise).

MX-LEDGER-0001
- Artifacts: autocapture/pillars/citable.py; autocapture/core/hashing.py; autocapture/storage/archive.py
- Validation: unit_test tests/test_provenance_chain.py; cli_exit autocapture provenance verify
- Minimal implementation: ledger append with hash chaining; CLI verify.

MX-RULES-0001
- Artifacts: autocapture/rules/ledger.py; autocapture/rules/store.py; autocapture/rules/schema.py; autocapture/rules/cli.py
- Validation: unit_test tests/test_rules_ledger_append_only.py; tests/test_rules_state_rebuild.py
- Minimal implementation: append-only rules ledger, rebuildable state, query integration hook.

MX-CAPTURE-0001
- Artifacts: autocapture/capture/spool.py; autocapture/capture/pipelines.py; autocapture/capture/models.py
- Validation: unit_test tests/test_capture_spool_idempotent.py
- Minimal implementation: durable spool records + encrypted screenshots; idempotent writes.

MX-INGEST-0001
- Artifacts: autocapture/ingest/normalizer.py; autocapture/ingest/spans.py
- Validation: unit_test tests/test_span_ids_stable.py; tests/test_span_bbox_norm.py
- Minimal implementation: span normalization + stable span IDs.

MX-TABLE-0001
- Artifacts: autocapture/plugins/kinds.py
- Validation: unit_test tests/test_table_extractor_strategies.py
- Minimal implementation: table extractor strategies (structured + image + pdf).

MX-INDEX-0001
- Artifacts: autocapture/indexing/lexical.py
- Validation: unit_test tests/test_fts_query_returns_hits.py
- Minimal implementation: SQLite FTS5 lexical indexing.

MX-INDEX-0002
- Artifacts: autocapture/indexing/vector.py
- Validation: unit_test tests/test_vector_index_roundtrip.py
- Minimal implementation: vector index backed by embedder + vector backend.

MX-INDEX-0003
- Artifacts: autocapture/indexing/vector.py; autocapture/tools/vendor_windows_binaries.py
- Validation: unit_test tests/test_qdrant_sidecar_healthcheck.py
- Minimal implementation: Qdrant sidecar supported; healthcheck validates availability.

MX-GRAPH-0001
- Artifacts: autocapture/indexing/graph.py
- Validation: unit_test tests/test_graph_adapter_contract.py
- Minimal implementation: graph adapter interface + optional retrieval tier integration.

MX-RETR-0001
- Artifacts: autocapture/retrieval/tiers.py; autocapture/retrieval/fusion.py; autocapture/retrieval/rerank.py; autocapture/retrieval/signals.py
- Validation: unit_test tests/test_rrf_fusion_determinism.py; tests/test_tier_planner_escalation.py
- Minimal implementation: tiered retrieval with deterministic fusion (RRF).

MX-CTX-0001
- Artifacts: autocapture/memory/context_pack.py; autocapture/retrieval/signals.py
- Validation: unit_test tests/test_context_pack_formats.py
- Minimal implementation: context pack JSON + TRON formats with retrieval signals.

MX-ANS-0001
- Artifacts: autocapture/memory/answer_orchestrator.py; autocapture/memory/citations.py; autocapture/memory/verifier.py; autocapture/memory/conflict.py
- Validation: unit_test tests/test_citation_validation.py; tests/test_verifier_enforced.py; tests/test_conflict_reporting.py
- Minimal implementation: claim-level citations + verifier + conflict reporting.

MX-GATEWAY-0001
- Artifacts: autocapture/gateway/app.py; autocapture/gateway/router.py; autocapture/gateway/schemas.py
- Validation: unit_test tests/test_gateway_schema_enforced.py; tests/test_gateway_policy_block_cloud_default.py
- Minimal implementation: OpenAI-compatible gateway with schema validation and PolicyGate routing.

MX-UX-0001
- Artifacts: autocapture/ux/facade.py; autocapture/ux/models.py
- Validation: python_import autocapture.ux.facade:UXFacade; unit_test tests/test_ux_facade_parity.py
- Minimal implementation: UXFacade is the single surface for CLI + UI parity.

MX-SETTINGS-0001
- Artifacts: autocapture/ux/settings_schema.py; autocapture/ux/preview_tokens.py; autocapture/web/routes/settings.py
- Validation: unit_test tests/test_settings_preview_tokens.py; http_endpoint GET /api/settings/schema
- Minimal implementation: settings schema tiers + preview tokens + apply confirmation.

MX-WEB-0001
- Artifacts: autocapture/web/api.py; autocapture/web/routes/query.py; autocapture/web/routes/citations.py; autocapture/web/routes/plugins.py; autocapture/web/routes/health.py; autocapture/web/routes/metrics.py
- Validation: http_endpoint GET /api/health; POST /api/query
- Minimal implementation: FastAPI routes with validated schemas.

MX-CIT-OVERLAY-0001
- Artifacts: autocapture/web/routes/citations.py
- Validation: unit_test tests/test_citation_overlay_contract.py
- Minimal implementation: citation overlay API returns bbox metadata and deterministic image or placeholder.

MX-DOCTOR-0001
- Artifacts: autocapture/ux/models.py; autocapture/web/routes/health.py
- Validation: unit_test tests/test_doctor_report_schema.py
- Minimal implementation: doctor report schema + route.

MX-OBS-0001
- Artifacts: autocapture/web/routes/metrics.py
- Validation: unit_test tests/test_metrics_endpoint_exposes_counters.py
- Minimal implementation: metrics endpoint exposes counters; OTel traces stubbed if deps absent.

MX-EXPORT-0001
- Artifacts: autocapture/storage/archive.py
- Validation: unit_test tests/test_export_import_roundtrip.py
- Minimal implementation: export/import bundles with manifest + hash verification.

MX-VENDOR-0001
- Artifacts: autocapture/tools/vendor_windows_binaries.py
- Validation: unit_test tests/test_vendor_binaries_hashcheck.py
- Minimal implementation: verify vendor binaries (Qdrant, FFmpeg) with hash checks.

MX-PROMPTOPS-0001
- Artifacts: autocapture/promptops/propose.py; validate.py; evaluate.py; patch.py; github.py
- Validation: unit_test tests/test_promptops_validation.py
- Minimal implementation: deterministic propose/validate/evaluate/apply pipeline; offline-friendly.

MX-TRAIN-0001
- Artifacts: autocapture/training/pipelines.py; autocapture/training/lora.py; autocapture/training/dpo.py; autocapture/training/datasets.py
- Validation: unit_test tests/test_training_manifest_schema.py
- Minimal implementation: reproducible manifests for LoRA + DPO (stub workloads OK).

MX-RESEARCH-0001
- Artifacts: autocapture/research/scout.py; autocapture/research/cache.py; autocapture/research/diff.py
- Validation: unit_test tests/test_research_scout_cache.py
- Minimal implementation: scout caching + diff thresholding.

MX-GATE-0001
- Artifacts: autocapture/tools/pillar_gate.py; autocapture/tools/privacy_scanner.py; autocapture/tools/provenance_gate.py; autocapture/tools/coverage_gate.py; autocapture/tools/latency_gate.py; autocapture/tools/retrieval_sensitivity.py; autocapture/tools/conflict_gate.py; autocapture/tools/integrity_gate.py
- Validation: cli_exit autocapture codex pillar-gates
- Minimal implementation: pillar gate suite writes JSON reports; integrated with Codex.

MX-CODEX-0001
- Artifacts: autocapture/codex/cli.py; autocapture/codex/spec.py; autocapture/codex/validators.py; autocapture/codex/report.py
- Validation: cli_exit autocapture codex validate --json
- Minimal implementation: spec loader + validator engine + JSON report + exit codes.

Notes and TODOs
- TODO: Decide how to parse YAML without adding new deps (prefer embedded spec or stdlib-safe parsing).
- TODO: Define how `autocapture` CLI will be wired in pyproject.toml (new console script or reuse existing).
- TODO: Ensure Windows-only functionality is safely skipped or mocked in tests.
