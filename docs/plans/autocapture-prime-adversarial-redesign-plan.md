# Plan: Implement Adversarial Redesign Recommendations (FND/META/EXEC/EXT/UX/OPS/SEC/PERF/QA/RD)

**Generated**: 2026-02-06
**Estimated Complexity**: Very High

## Overview
`docs/autocapture_prime_adversarial_redesign.md` defines 92 recommendation IDs across Foundation/Metadata/Execution/Extensions/UI/UX/Ops/Security/Performance/QA/Roadmap. The goal is to turn those recommendations into:
- concrete, versioned behavior in code
- deterministic validators (unit/integration tests and gates)
- traceability: every recommendation maps to code + tests + gates + evidence paths

This plan is optimized for the 4 pillars:
- **Performance**: reduce query/capture latency via budgets/caching/throttling/regression gates
- **Accuracy**: explicit pipeline DAG + idempotent jobs + deterministic ordering and tie-break rules
- **Security**: fail-closed local-only defaults + hardened plugin sandbox + signed artifacts
- **Citeability**: provenance objects + content-addressed manifests + verifiable proof bundles

## Scope
- In scope:
  - All recommendation headings `### <ID>` in `docs/autocapture_prime_adversarial_redesign.md`:
    - FND-01..10, META-01..10, EXEC-01..10, EXT-01..12, UX-01..10, OPS-01..08,
      SEC-01..10, PERF-01..08, QA-01..08, RD-01..06 (92 total).
  - Any supporting UX/spec material included in that doc sections (“Extension manager redesign”, dashboards, etc.).
  - Deterministic tests and gates for every shipped behavior change.
- Out of scope:
  - Anything not required by the doc.

## Constraints / Non-Negotiables (From Operating Manual + Doc)
- Localhost-only: never bind beyond 127.0.0.1; fail closed.
- No deletion endpoints; archive/migrate only.
- Raw-first local store; sanitization only on explicit export.
- Foreground gating: when user ACTIVE, only capture+kernel runs; pause other processing.
- Idle budgets CPU<=50% RAM<=50% enforced.
- Answers require citations by default (never fabricate).
- Media retention <= 60 days; queries must use metadata only.
- WSL stability: avoid runaway subprocess fan-out; prefer sharded tests and low-resource runner.

## Definition Of Done
- Every recommendation ID has:
  - a written acceptance checklist
  - at least one deterministic validator (test and/or gate)
  - traceability entry pointing to code paths + validator paths
- `tools/run_mod021_low_resource.sh` passes on WSL.
- Pillar gates remain green and include new gates where necessary.

## Prerequisites
- Track the redesign doc in git (it is currently untracked in the repo state).
- Baseline deterministic harness exists:
  - `tools/run_mod021_low_resource.sh`
  - `tools/run_unittest_sharded.py`
  - `tools/run_all_tests.py`
  - traceability tooling under `tools/traceability/`

## Sprint 0: Inventory + Coverage Baseline (Traceability First)
**Goal**: Make “implemented vs missing” measurable for the adversarial redesign items (not vibes).
**Demo/Validation**:
- A deterministic report exists listing each ID and its status: implemented/partial/missing, with code/test/gate links.
- A gate exists that fails if any ID is marked implemented without validators.

### Task 0.1: Add Adversarial Redesign Items To Traceability
- **Location**: `tools/traceability/` (new files), `docs/reports/` (generated report)
- **Description**:
  - Create a second traceability manifest dedicated to adversarial redesign IDs:
    - `tools/traceability/adversarial_redesign.json`
    - `tools/traceability/adversarial_redesign.schema.json`
  - Write a generator that parses `docs/autocapture_prime_adversarial_redesign.md` for all `### <ID>` headings and seeds the manifest with:
    - `id`, `title` (first line after heading), and `acceptance_bullets[]` (from doc “Acceptance Criteria” sections if present; otherwise seed placeholder bullets)
  - Write a validator that enforces:
    - every ID exists once
    - if `status=implemented`, at least one deterministic validator is listed
- **Complexity**: 7/10
- **Dependencies**: None
- **Acceptance Criteria**:
  - 92 IDs discovered and present in manifest.
  - Validator fails on missing IDs or invalid status/validators.
- **Validation**:
  - `python3 tools/traceability/generate_adversarial_redesign_traceability.py`
  - `python3 tools/traceability/validate_adversarial_redesign_traceability.py`

### Task 0.2: Add “Adversarial Redesign Coverage” Gate
- **Location**: `tools/gate_adversarial_redesign_coverage.py` (new), `tools/run_all_tests.py`
- **Description**:
  - Wire a gate into the standard test runner:
    - fails if any ID is marked `implemented` without validators
    - emits a coverage summary and a deterministic report:
      - `docs/reports/adversarial-redesign-gap-YYYY-MM-DD.md`
- **Complexity**: 5/10
- **Dependencies**: Task 0.1
- **Acceptance Criteria**:
  - Gate runs in < 2s and is deterministic.
  - Report includes per-ID status and references.
- **Validation**:
  - Run via `tools/run_all_tests.py` (low-resource wrapper used in all sprints).

## Sprint 1: Foundation Safety (FND-01..10)
**Goal**: Eliminate crash/power-loss footguns and operator confusion; make system fail-safe and explain itself.
**IDs**: FND-01, FND-02, FND-03, FND-04, FND-05, FND-06, FND-07, FND-08, FND-09, FND-10
**Demo/Validation**:
- New CLI subcommands or flags exist where required (integrity scan, backup, etc.).
- Deterministic tests cover atomicity, lock behavior, timestamps, safe-mode reason surfacing.

### Task 1.1: Integrity Scan Command
- **Location**: `autocapture/cli.py` (or canonical CLI entry), `autocapture_nx/kernel/` + storage plugins
- **Description**:
  - Implement `autocapture integrity scan` per FND-03.
  - Validate: ledger hash chain, journal structure, anchor references, metadata references to blobs/artifacts.
  - Must be read-only (no deletion, no “repair” without explicit operator command).
- **Complexity**: 7/10
- **Dependencies**: Sprint 0
- **Validation**:
  - Unit tests with fixture ledgers/journals (corrupt/valid).

### Task 1.2: Central Atomic Write Utilities
- **Location**: `autocapture_nx/util/atomic_write.py` (new), call sites across loader/manager/state writers
- **Description**:
  - Provide temp+fsync+rename for JSON/NDJSON state writes (FND-02).
  - Replace ad-hoc writes for config/run_state/approvals/audit state.
  - Add deterministic crash-simulation tests (write interrupted leaves previous file intact).
- **Complexity**: 8/10

### Task 1.3: Exclusive Instance Lock + Crash-Loop UX Surface
- **Location**: `autocapture_nx/kernel/loader.py`, web UI surfaces in `autocapture/web/`
- **Description**:
  - Add lock on `(config_dir,data_dir)` to prevent concurrent writers (FND-01).
  - Surface crash-loop/safe-mode reason codes + next steps via CLI and web UI (FND-10).
- **Complexity**: 6/10

### Task 1.4: Disk Pressure Fail-Safe + Timestamp Standardization
- **Location**: capture + processing scheduler modules, `autocapture_nx/util/time.py` (new)
- **Description**:
  - Preflight free space; throttle/pause capture/processing; ledgered “paused due to disk” state (FND-06).
  - Store UTC timestamps, tz_offset, monotonic durations (FND-09).
- **Complexity**: 6/10

### Task 1.5: Content-Addressed Ingest IDs + Backup/Migration Framework
- **Location**: ingest pipeline, metadata store, tools under `autocapture_nx/migrations/`
- **Description**:
  - Add input_id=sha256 dedupe at ingest boundary (FND-05).
  - Implement backup create/restore for config + locks + anchors (+ optional data) with integrity checks (FND-07).
  - Establish explicit DB migration framework + version pinning + rollback plan (FND-08).
- **Complexity**: 9/10

## Sprint 2: Provenance + Metadata Contract (META-01..10)
**Goal**: Make every answer and artifact provably tied to exact inputs/config/policy/plugins and addressable spans.
**IDs**: META-01..10
**Demo/Validation**:
- Query outputs include a standard `provenance` object.
- Derived artifacts have a content-addressed manifest with lineage pointers.

### Task 2.1: Effective Config + Policy Snapshots + Plugin Provenance
- **Location**: `autocapture_nx/kernel/loader.py`, `autocapture_nx/kernel/run_manifest.py` (or equivalent)
- **Description**:
  - Persist canonical effective-config snapshot per run (META-01).
  - Persist full policy snapshots by hash (META-06).
  - Record plugin provenance (manifest/artifact hashes + permissions) (META-02).
- **Complexity**: 7/10

### Task 2.2: Schema Versioning + Determinism Inputs Record
- **Location**: write boundaries for records, ledger/journal schema modules
- **Description**:
  - Add explicit schema_version fields and enforce validation (META-04).
  - Record determinism inputs: RNG seeds, locale/TZ, model versions, sampling params (META-09).
- **Complexity**: 6/10

### Task 2.3: Citation Addressing + Provenance Object Everywhere
- **Location**: answer layer + query API + exports
- **Description**:
  - Normalize citations to `(evidence_id, span_id, offsets/time_range, stable_locator)` (META-05).
  - Add standard `provenance` object to all user-visible outputs (META-03).
- **Complexity**: 8/10

### Task 2.4: Derived Artifact Manifest + Eval/Diagnostics Schema
- **Location**: OCR/VLM/indexing outputs, `autocapture_nx/kernel/proof_bundle.py`
- **Description**:
  - Content-addressed artifact manifest for derived artifacts with lineage pointers (META-07).
  - Minimal evaluation-result records surfaced in query/UI (META-08).
  - Canonical diagnostics bundle manifest schema (META-10).
- **Complexity**: 8/10

## Sprint 3: Execution Determinism + Idempotent Job Engine (EXEC-01..10)
**Goal**: Make execution explicit, replayable, and deterministic; make on-query extraction a scheduled job.
**IDs**: EXEC-01..10
**Demo/Validation**:
- Pipeline DAG is persisted and query never “mysteriously reprocesses media”.
- Deterministic scheduling and tie-break rules are contractually enforced by tests/gates.

### Task 3.1: Persisted Pipeline DAG + Replay Command
- **Location**: `autocapture_nx/kernel/state_tape.py` (or equivalent), CLI
- **Description**:
  - Persist pipeline DAG (stages+deps) (EXEC-01).
  - Implement `autocapture replay` for re-running processing/indexing without mutating original artifacts (EXEC-04).
- **Complexity**: 8/10

### Task 3.2: Idempotent Job Runner + Retry Policy + Audit Records
- **Location**: job runner / scheduler, ledger/audit hooks
- **Description**:
  - Bounded retries + backoff; attempt records in ledger (EXEC-02).
  - Deterministic scheduling + concurrency controls aligned with idle budgets (EXEC-03).
- **Complexity**: 8/10

### Task 3.3: Determinism Hardening + Retrieval Tie-Break Contract
- **Location**: critical pipelines + retrieval/rerank stages
- **Description**:
  - Stable sorts everywhere; eliminate nondeterminism sources (EXEC-05).
  - Deterministic retrieval tie-breaking: score→evidence_id→span_id ordering (EXEC-10).
- **Complexity**: 6/10

### Task 3.4: Subprocess Plugin Runtime Limits + Health Checks + Scheduled Extraction
- **Location**: `autocapture_nx/plugin_system/`, query scheduling, health endpoints
- **Description**:
  - Enforce RPC timeouts, kill-on-timeout, record terminations (EXEC-09).
  - Capability health checks (EXEC-08).
  - Replace on-query extraction with explicit scheduled job + blocked reasons + “schedule now” (EXEC-07).
- **Complexity**: 7/10

## Sprint 4: Extensions + Policy-Locked Plugin Lifecycle (EXT-01..12)
**Goal**: Make extensions manageable under stress: explicit lifecycle, compatibility, rollback, signed approvals/locks, permission diffs.
**IDs**: EXT-01..12
**Demo/Validation**:
- Extension manager spec is implemented minimally, with deterministic validations for permissions and lifecycle transitions.

### Task 4.1: Extension Lifecycle States + Permission Diff UX Model
- **Location**: plugin registry/manager + web UI API models
- **Description**:
  - Lifecycle states (installed/allowed/blocked/quarantined) (EXT-01).
  - Permission diff model and explanation surfaces (EXT-06).
- **Complexity**: 8/10

### Task 4.2: Compatibility Contracts + Rollback Path
- **Location**: plugin manifest schema/validator, loader boot gates
- **Description**:
  - Compatibility contracts and refusal reasons (EXT-04).
  - Rollback procedure + tooling (EXT-03).
- **Complexity**: 7/10

### Task 4.3: Signed Lockfile + Approval Workflow
- **Location**: `contracts/lock.json` handling, approval storage
- **Description**:
  - Signed lockfile / lock update hardening (EXT-11).
  - Approval_required default path aligning with SEC-04 (ties into Sprint 6).
- **Complexity**: 8/10

### Task 4.4: Extension Manager Redesign (Minimal Spec v2)
- **Location**: `autocapture/web/ui/` and web API backing
- **Description**:
  - Implement the “minimal viable spec (v2)” screens and flows from the doc.
- **Complexity**: 9/10

## Sprint 5: UI/UX Surfaces That Prevent Operator Error (UX-01..10)
**Goal**: Make the safe state obvious and mistakes hard.
**IDs**: UX-01..10
**Demo/Validation**:
- Web UI shows: data_dir/run_id, capture state, completeness/coverage, and proof/citation explorer.

### Task 5.1: Provenance-First UI Elements
- **Location**: `autocapture/web/ui/`
- **Description**:
  - Activity dashboard, ingest/status panel, run/job detail view, citation explorer, completeness UI.
  - Typed confirmation for enabling egress/unsafe toggles (ties SEC-04/UX-06).
- **Complexity**: 9/10

### Task 5.2: Deterministic UI State Model + Tests
- **Location**: web API models and UI tests (DOM snapshot tests where possible)
- **Description**:
  - Ensure UI state is derived from metadata only and deterministic for a given dataset snapshot.
- **Complexity**: 6/10

## Sprint 6: Ops + Security Hardening (OPS-01..08, SEC-01..10)
**Goal**: Operability without leaking secrets; enforce local-only posture; harden sandbox edge cases.
**IDs**: OPS-01..08, SEC-01..10
**Demo/Validation**:
- Diagnostics bundles are redacted and schema-pinned.
- Web console refuses non-loopback binds by default and emits clear operator warnings.

### Task 6.1: Metrics + Diagnostics Bundles + Operator Commands
- **Location**: `autocapture/web/`, `autocapture/cli.py`, `docs/`
- **Description**:
  - Metrics exposure aligned with OPS-02.
  - Redacted diagnostics bundle aligned with OPS-03 + META-10.
  - Operator commands/procedures aligned with OPS-05 and RD-06.
- **Complexity**: 7/10

### Task 6.2: Harden Filesystem/Network Guards + Secret Hygiene
- **Location**: `autocapture_nx/plugin_system/runtime.py`, Windows sandbox utilities
- **Description**:
  - Harden filesystem guard (SEC-01).
  - Early guard (SEC-02).
  - Loopback-only enforcement and tray behavior (SEC-03).
  - Secret hygiene / redaction enforcement (SEC-09/SEC-05).
- **Complexity**: 8/10

### Task 6.3: Proof Bundle Signing + Key Rotation Safety
- **Location**: `autocapture_nx/kernel/proof_bundle.py`, anchor/crypto plugins
- **Description**:
  - Signed proof bundles (SEC-07) and verification report.
  - Staged rewrap/key rotation (SEC-06) with deterministic migration tests.
- **Complexity**: 9/10

## Sprint 7: Performance + QA + Roadmap Gates (PERF-01..08, QA-01..08, RD-01..06)
**Goal**: Prevent regressions and prove behavior under adversarial conditions.
**Demo/Validation**:
- Perf regression gates exist and are WSL-stable.
- QA suites cover security/determinism/migrations as deterministic tests.

### Task 7.1: Perf Budgets + Throttling + WSL2 Queue Protocol
- **Location**: scheduler + WSL2 queue + perf gates
- **Description**:
  - Implement PERF items: caching, round-trip protocol, regression gates, auto-throttle.
  - Ensure idle budgets are enforced deterministically.
- **Complexity**: 8/10

### Task 7.2: QA Suites + Release/Runbook Discipline
- **Location**: `tests/`, `tools/gate_*.py`, `docs/`
- **Description**:
  - Add QA suites for security regression (QA-04), migrations (QA-05), determinism (QA-01/QA-02), etc.
  - RD gates: contract lock drift prevention, perf gates, rollback/runbook docs.
- **Complexity**: 7/10

## Testing Strategy (Low-Resource / Deterministic)
- Default: `tools/run_mod021_low_resource.sh` (serializes and clamps resources).
- For new tests: prefer pure unit tests; when integration is needed, use deterministic stub plugins and sharded execution via `tools/run_unittest_sharded.py`.
- Add gates for:
  - adversarial redesign coverage (Sprint 0)
  - determinism invariants (stable ordering, tie-breaks)
  - security invariants (loopback-only, no unexpected egress)
  - proof bundle verifiability

## Potential Risks & Gotchas
- “Implement everything” is too broad without traceability first; Sprint 0 is mandatory to prevent endless partial work.
- Some items overlap with existing blueprint/implementation-matrix work; avoid duplicate gates by reusing `tools/traceability/` patterns.
- UI work can become non-deterministic; require UI state to be derived from persisted metadata snapshots, not live inference.
- WSL stability: keep subprocess plugin fan-out bounded and ensure plugin hosts are closed deterministically after tests.

## Rollback Plan
- Every sprint lands behind explicit config flags where behavior is user-visible or risk-bearing.
- Keep old formats readable; migrations must be forward-only with explicit restore-from-backup path (archive/restore, not delete).
