# Plan: Stable Plugin-First Kernel Hardening (10 Recommendations)

**Generated**: 2026-01-31
**Estimated Complexity**: High

## Overview
Harden the current NX kernel to a fully isolated, deterministic, plugin-first architecture with strict schema validation, auditability, and sandboxing. This plan removes in-proc plugins, adds full JSON Schema validation for settings and outputs, enforces deterministic RNG usage, and records exhaustive execution audits in a dedicated DB. It also introduces golden migration fixtures, template diff/eval hooks (rooted in prompt templates), and updates ADRs + coverage mapping to satisfy traceability and verification requirements.

## Prerequisites
- Repo: `/mnt/d/projects/autocapture_prime`
- Python deps: add `jsonschema` (and optionally `psutil` for memory stats)
- Access to update `config/default.json`, `contracts/config_schema.json`, `contracts/plugin_manifest.schema.json`, plugin manifests, and docs/ADRs
- Ability to refresh plugin lockfile via `tools/hypervisor/scripts/update_plugin_locks.py`
- Decision: legacy `autocapture/plugins` is deprecated; PromptOps should be migrated to the NX plugin system

## Sprint 0: Non-Negotiables Compliance Baseline
**Goal**: Explicitly enforce hard rules (localhost-only, no deletion, raw-first, foreground gating, idle budgets, tray restrictions, PolicyGate) with tests.
**Demo/Validation**:
- Attempt to bind to `0.0.0.0` and confirm it fails closed.
- Run retention/cleanup paths and confirm no deletes occur.
- Verify ACTIVE-user mode blocks non-capture processing.

### Task 0.1: Enforce localhost-only binding
- **Location**: `autocapture_nx/cli.py`, `autocapture_nx/web/*`, `config/default.json`, `contracts/config_schema.json`
- **Description**: Force server binds to `127.0.0.1` only, reject or fail closed on non-localhost configuration.
- **Complexity**: 3
- **Dependencies**: None
- **Acceptance Criteria**:
  - Any attempt to bind non-localhost is rejected.
- **Validation**:
  - New test that asserts bind to `0.0.0.0` fails.

### Task 0.2: Remove/disable delete endpoints and retention pruning
- **Location**: `autocapture/runtime/conductor.py`, `autocapture/storage/retention.py`, `autocapture_nx/cli.py`, `autocapture/web/ui/*`
- **Description**: Audit and disable delete/retention paths (no deletion endpoints). Replace with archive/migrate-only flows if needed.
- **Complexity**: 5
- **Dependencies**: None
- **Acceptance Criteria**:
  - No delete endpoints or retention pruning reachable in normal mode.
- **Validation**:
  - Tests that scan routes/CLI for delete operations and fail if present.

### Task 0.3: Enforce raw-first local store
- **Location**: `autocapture/ux/redaction.py`, `autocapture/plugins/policy_gate.py`, `autocapture_nx/kernel/query.py`, `config/default.json`
- **Description**: Ensure local storage is raw/unmasked; sanitization only on explicit export. Add guards and tests.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Sanitization is never applied to local storage paths.
- **Validation**:
  - Tests verifying export-only sanitization behavior.

### Task 0.4: Foreground gating (ACTIVE-user mode)
- **Location**: `autocapture/runtime/governor.py`, `autocapture/runtime/conductor.py`, `autocapture_nx/processing/*`
- **Description**: Ensure when user is ACTIVE, only capture + kernel runs; all other processing is paused.
- **Complexity**: 5
- **Dependencies**: None
- **Acceptance Criteria**:
  - ACTIVE mode blocks non-capture jobs deterministically.
- **Validation**:
  - Tests that simulate activity and assert idle processing does not run.

### Task 0.5: Enforce idle CPU/RAM budgets
- **Location**: `autocapture/runtime/budgets.py`, `autocapture/runtime/governor.py`, `config/default.json`
- **Description**: Enforce CPU <= 50% and RAM <= 50% budget caps during idle processing; record in telemetry/audit.
- **Complexity**: 5
- **Dependencies**: None
- **Acceptance Criteria**:
  - Idle processing respects CPU/RAM caps.
- **Validation**:
  - Deterministic tests with mocked budget consumption.

### Task 0.6: Tray restrictions + PolicyGate enforcement
- **Location**: `autocapture/web/ui/*`, `autocapture/plugins/policy_gate.py`, `autocapture_nx/plugin_system/*`
- **Description**: Ensure tray does not expose capture pause or deletion actions; add NX-side PolicyGate for untrusted plugins and external inputs.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Tray UI lacks capture pause/delete controls.
  - PolicyGate blocks disallowed plugin actions.
- **Validation**:
  - UI tests for tray controls.
  - Negative tests for PolicyGate enforcement.

## Sprint 1: Isolation + Sandbox Baseline
**Goal**: All plugins run out-of-process; kernel remains healthy if any plugin dies; filesystem access is tightly scoped.
**Demo/Validation**:
- Start kernel in normal mode and confirm all plugins run in subprocess hosting.
- Kill a plugin process and confirm kernel continues with deterministic error handling.
- Run filesystem-policy tests ensuring plugins cannot access outside run dir + DB.

### Task 1.1: Deprecate legacy plugin manager and migrate PromptOps lookup
- **Location**: `autocapture/promptops/engine.py`, `autocapture/plugins/manager.py`, `autocapture_nx/kernel/query.py`, `docs/adr/ADR-0006-plugin-system-deprecation.md`
- **Description**: Mark the legacy YAML plugin manager as deprecated and migrate PromptOps bundle resolution to NX plugin capabilities (new `prompt.bundle` NX plugin). Add a visible warning when legacy is used.
- **Complexity**: 5
- **Dependencies**: None
- **Acceptance Criteria**:
  - PromptOps uses NX plugin registry for prompt bundles.
  - Legacy manager emits deprecation warning when invoked.
- **Validation**:
  - Unit test for PromptOps bundle resolution.
  - Log assertion test for deprecation warning.

### Task 1.2: Enforce subprocess hosting for all NX plugins
- **Location**: `config/default.json`, `contracts/config_schema.json`, `autocapture_nx/plugin_system/registry.py`, `autocapture_nx/kernel/loader.py`, `plugins/builtin/*/plugin.json`
- **Description**: Remove/empty `plugins.hosting.inproc_allowlist` by default and enforce subprocess hosting. Convert in-proc-only plugins (e.g., runtime governor/scheduler) into kernel-native components or subprocess-safe plugins.
- **Complexity**: 8
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - No plugin loads in-proc in normal mode.
  - Kernel still exposes required capabilities (runtime governor/scheduler) without in-proc plugins.
- **Validation**:
  - `tests/test_plugin_loader.py` asserts no in-proc plugins.
  - End-to-end boot in normal mode.

### Task 1.3: Add crash-safe plugin supervision
- **Location**: `autocapture_nx/plugin_system/host.py`, `autocapture_nx/plugin_system/host_runner.py`, `autocapture_nx/plugin_system/registry.py`
- **Description**: Detect plugin process exits; restart or mark provider as unhealthy; return deterministic error payloads instead of crashing kernel.
- **Complexity**: 6
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Plugin crash does not crash kernel.
  - Failure is recorded for audit and provider ordering.
  - Deterministic fallback/circuit-breaker prevents repeated crash loops.
- **Validation**:
  - New test with a crashing plugin; kernel keeps running.

### Task 1.4: Tighten filesystem sandbox to run dir + DB
- **Location**: `autocapture_nx/plugin_system/registry.py`, `autocapture_nx/plugin_system/runtime.py`, `config/default.json`, `contracts/config_schema.json`
- **Description**: Add template variables (`{run_dir}`, `{metadata_db_path}`, `{media_dir}`, `{audit_db_path}`) and update defaults so plugins only access the run-specific directory and DB paths unless explicitly allowlisted.
- **Complexity**: 7
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Default policies block reads/writes outside run dir + DB.
  - Exceptions exist only in explicit allowlists.
- **Validation**:
  - Extend `tests/test_plugin_filesystem_policy.py` with run-dir enforcement cases.

### Task 1.5: Add deterministic circuit-breaker fallback
- **Location**: `autocapture_nx/plugin_system/host.py`, `autocapture_nx/plugin_system/registry.py`, `autocapture_nx/kernel/loader.py`
- **Description**: When a plugin exceeds crash/timeout limits, switch to a deterministic no-op or stub provider that returns audited errors without taking down the kernel.
- **Complexity**: 5
- **Dependencies**: Task 1.3
- **Acceptance Criteria**:
  - Repeated plugin failures do not block kernel workflows.
- **Validation**:
  - Test with a failing plugin confirms deterministic fallback behavior.

### Task 1.6: Kernel-native runtime governor/scheduler replacement
- **Location**: `autocapture_nx/kernel/loader.py`, `autocapture/runtime/governor.py`, `autocapture/runtime/scheduler.py`, `docs/adr/ADR-0010-kernel-runtime-services.md`
- **Description**: Move runtime governor/scheduler into kernel-native services to avoid in-proc plugins while preserving capability interfaces.
- **Complexity**: 6
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - Kernel exposes `runtime.governor` and `runtime.scheduler` without in-proc plugins.
- **Validation**:
  - Tests validating scheduler/gov behavior without plugin hosting.

## Sprint 2: Full Schema Validation + I/O Contracts
**Goal**: Deterministic, self-documenting settings and output validation across plugins, with schema-backed contracts.
**Demo/Validation**:
- Load plugin with invalid settings and verify failure is deterministic.
- Stage-hook outputs rejected if schema-incompatible.

### Task 2.1: Add JSON Schema validator infrastructure
- **Location**: `pyproject.toml`, `autocapture_nx/kernel/schema_registry.py` (new), `contracts/` (new schema files)
- **Description**: Introduce `jsonschema` dependency and implement a schema registry for loading/validating settings and outputs with stable error messages.
- **Complexity**: 4
- **Dependencies**: None
- **Acceptance Criteria**:
  - Schema registry validates objects deterministically.
- **Validation**:
  - Unit tests for schema registry behavior.

### Task 2.2: Enforce per-plugin settings schema validation
- **Location**: `autocapture_nx/plugin_system/registry.py`, `contracts/plugin_manifest.schema.json`, `autocapture_nx/plugin_system/manifest.py`, `plugins/builtin/*/plugin.json`
- **Description**: Validate `settings_schema` (inline or `settings_schema_path`) after settings merge. Create schema files for critical plugins.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Invalid settings prevent plugin load with explicit error.
- **Validation**:
  - New test for invalid settings rejection.

### Task 2.3: Add plugin I/O contract schemas
- **Location**: `contracts/plugin_manifest.schema.json`, `autocapture_nx/plugin_system/manifest.py`, `autocapture_nx/plugin_system/registry.py`, `autocapture_nx/plugin_system/host.py`
- **Description**: Extend manifest to declare per-capability/method input/output schemas and validate in both in-proc and subprocess calls.
- **Complexity**: 7
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Input/output validation runs on every capability call.
  - Violations are deterministic and audited.
- **Validation**:
  - Tests for schema-violating outputs returning structured errors.

### Task 2.4: Enforce output schema validation for findings/artifacts
- **Location**: `autocapture_nx/processing/sst/pipeline.py`, `autocapture_nx/processing/sst/types.py`, `autocapture_nx/kernel/query.py`, `contracts/sst/*.schema.json` (new)
- **Description**: Define schemas for tokens/tables/charts/state outputs and validate all stage hook payloads before merge. Enforce answer-builder output schema and citations at the query/response boundary.
- **Complexity**: 6
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Invalid artifacts are dropped with diagnostics.
  - Answer outputs require citations by default in all response paths.
- **Validation**:
  - Unit tests for invalid stage hook outputs and missing citations.

### Task 2.5: Refresh plugin lockfile after manifest/schema updates
- **Location**: `config/plugin_locks.json`, `tools/hypervisor/scripts/update_plugin_locks.py`
- **Description**: Regenerate plugin manifest/artifact hashes to satisfy lock enforcement after schema or manifest changes.
- **Complexity**: 3
- **Dependencies**: Task 2.2, Task 2.3, Task 2.4
- **Acceptance Criteria**:
  - Plugin lockfile hashes match updated manifests and artifacts.
- **Validation**:
  - Plugin load succeeds with lock enforcement enabled.

## Sprint 3: Determinism + RNG Enforcement
**Goal**: All plugin randomness is seeded per run and audited; unseeded randomness is blocked or flagged.
**Demo/Validation**:
- Run the same input twice and confirm identical outputs.
- Plugin using random without seed triggers audit + error (strict mode).

### Task 3.1: Implement RNG service and seed derivation
- **Location**: `autocapture_nx/kernel/rng.py` (new), `autocapture_nx/plugin_system/api.py`, `autocapture_nx/plugin_system/host_runner.py`, `contracts/config_schema.json`
- **Description**: Provide deterministic RNG per run and per plugin; expose via `PluginContext` and config.
- **Complexity**: 5
- **Dependencies**: None
- **Acceptance Criteria**:
  - RNG seeds are deterministic and logged.
- **Validation**:
  - Tests verifying seed derivation stability.

### Task 3.2: Seed injection and unseeded randomness guard
- **Location**: `autocapture_nx/plugin_system/host_runner.py`, `autocapture_nx/plugin_system/runtime.py`, `config/default.json`
- **Description**: Seed Python random + optional numpy/torch; patch random usage to detect unseeded calls; add strict-mode config.
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Unseeded randomness is blocked (strict) or audited (warn).
- **Validation**:
  - Tests with a plugin that calls `random.random()` before seeding.

### Task 3.3: Determinism hardening beyond RNG
- **Location**: `autocapture_nx/kernel/query.py`, `autocapture_nx/processing/sst/pipeline.py`, `autocapture_nx/plugin_system/registry.py`
- **Description**: Enforce stable ordering, locale/time normalization, and deterministic file iteration. Add tests for deterministic outputs across identical inputs.
- **Complexity**: 6
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Outputs remain identical across runs for identical inputs.
- **Validation**:
  - Deterministic regression tests for ordering/time/locale impacts.

## Sprint 4: Execution Audit DB + Registry Metadata
**Goal**: Rich, append-only audit data for every plugin call, plus registry metadata and deterministic provider selection.
**Demo/Validation**:
- Run a pipeline stage and query audit DB for runtime + hashes.
- Simulate failure history and confirm deterministic provider ordering.

### Task 4.1: Create dedicated audit DB
- **Location**: `autocapture_nx/kernel/audit_db.py` (new), `autocapture_nx/kernel/loader.py`, `contracts/audit_schema.json` (new)
- **Description**: Add an append-only SQLite audit DB with tables for runs, plugin metadata, calls, IO stats, failures, RNG seeds, and template diffs.
- **Complexity**: 7
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Audit DB initializes on boot and records run header.
  - Tables are append-only (no delete paths) to satisfy audit requirements.
- **Validation**:
  - Unit tests for schema creation and insert-only behavior.

### Task 4.2: Instrument plugin calls and storage IO
- **Location**: `autocapture_nx/plugin_system/host.py`, `autocapture_nx/plugin_system/registry.py`, `plugins/builtin/storage_sqlcipher/plugin.py`, `autocapture_nx/kernel/metadata_store.py`
- **Description**: Wrap capability calls to capture runtime, input/output hashes, row counts, and memory estimates. Add helpers for IO metrics in storage plugins.
- **Complexity**: 8
- **Dependencies**: Task 4.1, Task 2.3
- **Acceptance Criteria**:
  - Every plugin call produces an audit row with hashes + timing.
- **Validation**:
  - Tests asserting audit rows after a known capability call.

### Task 4.3: Plugin registry metadata + failure history
- **Location**: `contracts/plugin_manifest.schema.json`, `autocapture_nx/plugin_system/manifest.py`, `autocapture_nx/plugin_system/registry.py`, `autocapture_nx/kernel/loader.py`
- **Description**: Add capability tags in manifests, persist to audit DB, and use deterministic failure history in provider ordering.
- **Complexity**: 6
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Capability tags stored in audit DB.
  - Provider ordering deterministically reflects failure history when enabled.
- **Validation**:
  - Tests for ordering stability given recorded failures.

## Sprint 5: Migration Fixtures + Template Diff/Eval + Documentation
**Goal**: Deterministic migrations, template diff/eval support, and full documentation/coverage updates.
**Demo/Validation**:
- Run migration tests against golden fixtures.
- Run template diff/eval CLI and confirm audit entries.

### Task 5.1: Golden migration fixtures and tests
- **Location**: `tests/fixtures/migrations/` (new), `tests/test_storage_migrations.py` (new), `autocapture_nx/cli.py`, `plugins/builtin/storage_sqlcipher/plugin.py`
- **Description**: Add versioned DB fixtures and tests for data dir + metadata migrations, verifying deterministic hashes and counts.
- **Complexity**: 6
- **Dependencies**: None
- **Acceptance Criteria**:
  - Migration tests pass with deterministic outputs.
- **Validation**:
  - `pytest -q tests/test_storage_migrations.py`

### Task 5.2: Template mapping diffing
- **Location**: `autocapture/promptops/sources.py`, `autocapture/promptops/engine.py`, `autocapture_nx/kernel/audit_db.py`
- **Description**: Treat PromptOps source snapshots as template mappings; record diffs between versions in audit DB. Provide hooks for future mapping sources.
- **Complexity**: 5
- **Dependencies**: Task 1.1, Task 4.1
- **Acceptance Criteria**:
  - Template diffs are recorded when prompt sources change.
- **Validation**:
  - Unit test for deterministic diff output.

### Task 5.3: Template-level evaluation harness
- **Location**: `autocapture/promptops/evaluate.py`, `autocapture_nx/kernel/audit_db.py`, `autocapture_nx/cli.py`
- **Description**: Add a template evaluation CLI that runs ground-truth checks at the template layer and stores results in audit DB.
- **Complexity**: 5
- **Dependencies**: Task 5.2, Task 4.1
- **Acceptance Criteria**:
  - Evaluation results stored with deterministic metrics.
- **Validation**:
  - CLI test invoking evaluation on sample fixtures.

### Task 5.4: Documentation, ADRs, and Coverage_Map updates
- **Location**: `docs/adr/ADR-0006-plugin-isolation.md` (new), `docs/adr/ADR-0007-audit-db.md` (new), `docs/adr/ADR-0008-rng-enforcement.md` (new), `docs/adr/ADR-0009-schema-validation.md` (new), `docs/reports/implementation_matrix.md`, `docs/spec/feature_completeness_spec.md`
- **Description**: Add ADRs for each major change and update coverage/implementation mappings to reference modules + tests for each of the 10 recommendations.
- **Complexity**: 4
- **Dependencies**: All prior sprints
- **Acceptance Criteria**:
  - Each recommendation is mapped to code + ADR + tests.
- **Validation**:
  - Manual doc review; optional doc lints if present.

## Testing Strategy
- Run targeted unit tests per sprint (new tests listed above).
- Run full suite: `poetry run pytest -q`.
- Add deterministic regression tests for RNG, schema validation, plugin crash handling, audit DB entries, and migration fixtures.

## Potential Risks & Gotchas
- Enforcing subprocess hosting may break latency-sensitive plugins; kernel-native replacements may be needed.
- RNG guards could break libraries that assume global randomness; keep strict/warn modes configurable.
- Schema validation can be expensive; keep schemas minimal and cache compiled validators.
- Memory stats differ across OSes; ensure Windows-friendly fallbacks.
- Filesystem sandbox tightening may block legitimate plugin access; require explicit allowlists.
- Failure-history-based provider ordering must be deterministic and configurable to avoid non-reproducible behavior.

## Rollback Plan
- Feature flags in config for: audit DB, schema validation strictness, RNG enforcement, and provider ordering penalties.
- Restore previous hosting mode via config if needed.
- Keep legacy PromptOps resolution path behind a temporary compatibility flag.
