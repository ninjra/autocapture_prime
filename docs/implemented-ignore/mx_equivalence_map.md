# Autocapture MX Equivalence Map (NX -> MX)

Purpose
- Identify where NX already provides functionally equivalent behavior for MX Appendix A requirements.
- Provide proof via existing code paths and tests.
- Note gaps required to satisfy MX paths/validators (Codex).

Equivalence levels
- EQUIVALENT: NX behavior matches the requirement (proof provided).
- PARTIAL: NX has related behavior but misses required scope or coverage.
- MISSING: No equivalent behavior found in NX codebase.

Note
- Even when EQUIVALENT, Appendix A still requires new MX module paths/tests/CLI endpoints.
- Proof is listed as existing file paths and tests.

Requirements

MX-CONFIG-0001
- Equivalence: EQUIVALENT
- Proof: `autocapture_nx/kernel/config.py` (load_config + safe_mode); `config/default.json` (privacy.cloud.enabled=false); `tests/test_config.py`
- Gap to MX: add `autocapture/config/*` modules + `tests/test_config_defaults.py` and wire Codex paths.

MX-RETENTION-0001
- Equivalence: PARTIAL
- Proof: `autocapture_nx/cli.py` (argparse subcommands, no delete/purge/wipe); repo search found no delete/purge/wipe in CLI or web code
- Gap to MX: add `autocapture/ux/facade.py`, `autocapture/web/api.py`, and ensure HTTP routes absent per validator.

MX-CORE-0001
- Equivalence: PARTIAL
- Proof: `autocapture_nx/kernel/canonical_json.py` (canonical JSON); `autocapture_nx/kernel/hashing.py` (sha256 helpers); `tests/test_canonical_json.py`
- Gap to MX: add `autocapture/core/ids.py` (stable IDs) and MX tests; confirm hashing primitive (blake3 vs sha256).

MX-PLUGIN-0001
- Equivalence: PARTIAL
- Proof: `autocapture_nx/plugin_system/registry.py` (manifest discovery + validation + lockfile); `contracts/plugin_manifest.schema.json`; `tests/test_plugin_loader.py`
- Gap to MX: implement MX plugin manager/manifest/kinds modules and list output schema; add no-import discovery test.

MX-KINDS-0001
- Equivalence: PARTIAL
- Proof: `plugins/**/plugin.json` entrypoints include `kind` fields
- Gap to MX: add explicit registry `autocapture/plugins/kinds.py` + required kinds test.

MX-PLUGSET-0001
- Equivalence: MISSING
- Proof: NX plugin IDs are `builtin.*` not `mx.*`; no `autocapture_plugins/` manifests.
- Gap to MX: create `autocapture_plugins/` with required `mx.*` plugin IDs and default enablement.

MX-PLUGIN-0002
- Equivalence: MISSING
- Proof: no hot-swap logic in `autocapture_nx/plugin_system/registry.py`.
- Gap to MX: add hot-swap support + tests.

MX-PLUGIN-0003
- Equivalence: PARTIAL
- Proof: `autocapture_nx/kernel/config.py` safe_mode; `autocapture_nx/plugin_system/registry.py` default pack; `tests/test_safe_mode.py`.
- Gap to MX: add PolicyGate enforcement for cloud egress and MX test names.

MX-POLICY-0001
- Equivalence: PARTIAL
- Proof: `autocapture_nx/plugin_system/runtime.py` (network_guard); `plugins/builtin/egress_gateway/plugin.py` (egress checks); `tests/test_network_guard.py`; `tests/test_egress_gateway.py`
- Gap to MX: add `autocapture/plugins/policy_gate.py` and `autocapture/core/http.py` as sole network surface.

MX-SAN-0001
- Equivalence: EQUIVALENT (behavior)
- Proof: `plugins/builtin/egress_sanitizer/plugin.py` (deterministic tokens + leak_check); `tests/test_sanitizer.py`
- Gap to MX: add `autocapture/memory/entities.py` + `autocapture/ux/redaction.py` + MX tests.

MX-GOV-0001
- Equivalence: PARTIAL
- Proof: `plugins/builtin/runtime_governor/plugin.py` (mode selection)
- Gap to MX: add runtime governor module + gating enforcement + tests.

MX-LEASE-0001
- Equivalence: MISSING
- Proof: no lease manager in `autocapture_nx/`.
- Gap to MX: implement `autocapture/runtime/leases.py` + tests.

MX-STORE-0001
- Equivalence: PARTIAL
- Proof: `plugins/builtin/storage_encrypted/plugin.py` (encrypted metadata/blob/entity map); `autocapture_nx/kernel/keyring.py`; `autocapture_nx/kernel/key_rotation.py`; `tests/test_storage_encrypted.py`; `tests/test_key_rotation.py`; `plugins/builtin/storage_sqlcipher/plugin.py`; `tests/test_sqlcipher_store.py`
- Gap to MX: formal storage modules under `autocapture/storage/*` + key export/import + MX tests.

MX-LEDGER-0001
- Equivalence: PARTIAL
- Proof: `plugins/builtin/ledger_basic/plugin.py` (hash chain); `tests/test_ledger_journal.py`
- Gap to MX: add provenance verify CLI and `autocapture/pillars/citable.py` + `autocapture/storage/archive.py`.

MX-RULES-0001
- Equivalence: MISSING
- Proof: no rules ledger/store modules in NX.
- Gap to MX: implement rules ledger + tests.

MX-CAPTURE-0001
- Equivalence: PARTIAL
- Proof: `plugins/builtin/capture_windows/plugin.py` (segment capture + encrypted storage hooks); `plugins/builtin/capture_stub/plugin.py`
- Gap to MX: add capture spool + pipelines + models + idempotent spool test.

MX-INGEST-0001
- Equivalence: MISSING
- Proof: no ingest normalization modules in NX.
- Gap to MX: implement `autocapture/ingest/*` + tests.

MX-TABLE-0001
- Equivalence: MISSING
- Proof: no table extractor plugin or strategies in NX.
- Gap to MX: implement table extractor strategies and register kind.

MX-INDEX-0001
- Equivalence: MISSING
- Proof: no FTS5 lexical index in NX.
- Gap to MX: implement `autocapture/indexing/lexical.py` + tests.

MX-INDEX-0002
- Equivalence: MISSING
- Proof: no vector index implementation in NX (only embedder_stub plugin).
- Gap to MX: implement `autocapture/indexing/vector.py` + tests.

MX-INDEX-0003
- Equivalence: MISSING
- Proof: no Qdrant sidecar support in NX.
- Gap to MX: implement vector backend + vendor binary verifier.

MX-GRAPH-0001
- Equivalence: MISSING
- Proof: no graph adapter in NX.
- Gap to MX: implement `autocapture/indexing/graph.py` + tests.

MX-RETR-0001
- Equivalence: PARTIAL
- Proof: `plugins/builtin/retrieval_basic/plugin.py` (deterministic tie-break); `tests/test_retrieval.py`
- Gap to MX: tiered retrieval + fusion + rerank + signals.

MX-CTX-0001
- Equivalence: MISSING
- Proof: no context pack module in NX.
- Gap to MX: implement `autocapture/memory/context_pack.py` + tests.

MX-ANS-0001
- Equivalence: PARTIAL
- Proof: `plugins/builtin/answer_basic/plugin.py`; `plugins/builtin/citation_basic/plugin.py`; `autocapture_nx/kernel/query.py`; `tests/test_answer_builder.py`; `tests/test_query.py`
- Gap to MX: orchestrator + verifier + conflict handling + MX tests.

MX-GATEWAY-0001
- Equivalence: MISSING
- Proof: no gateway app/router/schemas in NX.
- Gap to MX: implement OpenAI-compatible gateway + tests.

MX-UX-0001
- Equivalence: MISSING
- Proof: no UX facade/models in NX.
- Gap to MX: implement `autocapture/ux/*` + tests.

MX-SETTINGS-0001
- Equivalence: MISSING
- Proof: no settings schema/preview in NX.
- Gap to MX: implement settings schema + route + tests.

MX-WEB-0001
- Equivalence: MISSING
- Proof: no web API routes in NX.
- Gap to MX: implement FastAPI web API + tests.

MX-CIT-OVERLAY-0001
- Equivalence: MISSING
- Proof: no citation overlay API in NX.
- Gap to MX: implement citations route + tests.

MX-DOCTOR-0001
- Equivalence: PARTIAL
- Proof: `autocapture_nx/cli.py` (doctor command); `autocapture_nx/kernel/loader.py` (doctor checks)
- Gap to MX: add web health route + doctor report schema test.

MX-OBS-0001
- Equivalence: PARTIAL
- Proof: `plugins/builtin/observability_basic/plugin.py`; `tests/test_observability.py`
- Gap to MX: metrics endpoint + OTel traces + tests.

MX-EXPORT-0001
- Equivalence: MISSING
- Proof: no archive export/import module in NX.
- Gap to MX: implement `autocapture/storage/archive.py` + tests.

MX-VENDOR-0001
- Equivalence: MISSING
- Proof: no vendor binary verifier in NX.
- Gap to MX: implement `autocapture/tools/vendor_windows_binaries.py` + tests.

MX-PROMPTOPS-0001
- Equivalence: MISSING
- Proof: no promptops modules in NX.
- Gap to MX: implement promptops pipeline + tests.

MX-TRAIN-0001
- Equivalence: MISSING
- Proof: no training pipelines in NX.
- Gap to MX: implement training modules + tests.

MX-RESEARCH-0001
- Equivalence: MISSING
- Proof: no research scout/cache/diff modules in NX.
- Gap to MX: implement research modules + tests.

MX-GATE-0001
- Equivalence: MISSING
- Proof: no pillar gate suite in NX.
- Gap to MX: implement gate tools + codex integration.

MX-CODEX-0001
- Equivalence: MISSING
- Proof: no Codex CLI/validators in NX (only NX-specific spec validator under tools/validate_blueprint_spec.py).
- Gap to MX: implement `autocapture/codex/*` and CLI commands.
