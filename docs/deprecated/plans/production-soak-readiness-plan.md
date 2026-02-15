# Plan: Production Soak Readiness (Full Repo To Green + 24h Soak)

**Generated**: 2026-02-09
**Estimated Complexity**: High

## Overview
Bring the repository to a “ship/soak” state:
- `origin/main` fully updated with all current local changes (committed, merged, pushed).
- Repo-wide “unfinished work” eliminated (TODO/FIXME/NotImplemented/unimplemented stubs), or explicitly justified and gated.
- All adversarial redesign items closed: `tools/run_adversarial_redesign_coverage.sh` reports `issues=0`.
- Blueprint traceability and acceptance coverage refreshed and passing.
- Full pipeline (capture ingest -> raw stores -> idle processing -> query w/ citations) is stable on WSL without process explosions or RAM spikes.
- Provide a one-line command that runs a **full 24h soak** of the whole system (capture + orchestrator + idle processing + query readiness), with metrics and audit artifacts.

Key non-negotiables to preserve throughout:
- Localhost-only.
- No deletion endpoints; archive/migrate only.
- Raw-first local store; sanitization only on explicit export.
- Foreground gating: when user ACTIVE, only capture+kernel runs; no heavy processing.
- Idle budgets enforced: CPU <= 50%, RAM <= 50% (enforced), GPU may saturate.
- Answers require citations by default.
- WSL stability: avoid spawning many Python plugin-host processes; cap concurrency deterministically.

## Clarifications (Assumptions If Unanswered)
These were answered or I will use best judgment:
- Git: push directly to `origin/main` only after gates are green; if branch protection blocks, use a temporary branch and merge via PR/fast-forward.
- Soak runs in WSL; Windows capture UI/tray lives in another repo. This repo must support ingesting full-fidelity screenshots reliably and processing/querying them.
- “Never miss” means: every capture event is recorded durably; pixel blobs are deduped by content-hash (full-fidelity stored for each unique image).
- Soak runs “normal full processing” during idle: OCR + SST + VLM (if configured) within budgets; when active, processing pauses.

## Prerequisites
- `.venv` created and usable in WSL.
- `ffmpeg` in PATH for any mp4/ffmpeg container fixtures (even if video is disabled by default).
- Git remotes configured; network access to GitHub.

## Sprint 1: Git Hygiene + Lockfiles + Safe Main Update
**Goal**: Clean, reviewable commits; `origin/main` updated safely without losing history.
**Demo/Validation**:
- `git status -sb` clean on `main`.
- `git log -1` on local `main` equals `origin/main`.

### Task 1.1: Sync + Branch Safety Guard
- **Location**: repo root
- **Description**:
  - `git fetch origin`
  - If `main` is protected or requires PR, create `soak-ready/<date>` branch and push it.
  - Otherwise, update `main` directly.
- **Complexity**: 3
- **Acceptance Criteria**:
  - No uncommitted changes prior to push (except ignored artifacts).
  - No force-push.
- **Validation**:
  - `git status -sb`
  - `git branch -vv`

### Task 1.2: Commit In Logical Chunks
- **Location**: multiple files (see `git status`)
- **Description**:
  - Split changes into a small set of commits:
    - Fixture correctness + OCR reliability + QA extraction schema.
    - WSL stability caps / plugin-host control.
    - Overflow spool + capture durability.
    - Contract/schema lock updates.
    - Docs/plans updates.
  - Update plugin lockfile and contract lockfile after each schema/plugin change.
- **Complexity**: 6
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Each commit passes targeted tests relevant to its scope.
  - Lockfiles updated deterministically.
- **Validation**:
  - `tools/hypervisor/scripts/update_contract_lock.py`
  - `tools/hypervisor/scripts/update_plugin_locks.py`
  - `pytest -q` targeted tests per commit

### Task 1.3: Merge/Push To `origin/main`
- **Location**: git
- **Description**:
  - If using a branch: merge to main via PR/fast-forward once gates are green.
  - Push `main` to origin.
- **Complexity**: 4
- **Dependencies**: Tasks 1.1-1.2 + Sprints 2-4 gates green
- **Acceptance Criteria**:
  - `origin/main` reflects all changes.
- **Validation**:
  - `git fetch origin && git rev-parse main origin/main`

## Sprint 2: Blueprint + Traceability + Coverage Matrix To Current Reality
**Goal**: Ensure the “130 items” blueprint system is runnable and refreshed from any CWD.
**Demo/Validation**:
- Running blueprint refresh from anywhere succeeds.
- A canonical `BLUEPRINT.md` exists (pointer if needed).

### Task 2.1: Create/Repair Canonical `BLUEPRINT.md`
- **Location**: `BLUEPRINT.md`
- **Description**:
  - Add `BLUEPRINT.md` at repo root (if missing) that points to the canonical blueprint spec (currently `docs/spec/autocapture_nx_blueprint_2026-01-24.md`).
  - Ensure toolchain references are consistent.
- **Complexity**: 2
- **Acceptance Criteria**:
  - Repo has a stable “entrypoint” blueprint file for humans and automation.
- **Validation**:
  - `test -f BLUEPRINT.md`

### Task 2.2: Make Refresh Scripts Resilient
- **Location**: `tools/refresh_blueprint_traceability.sh`
- **Description**:
  - Verify `$REPO_ROOT` resolution works even when invoked from non-repo CWD.
  - Ensure Python entrypoints are invoked via absolute repo paths (already intended).
- **Complexity**: 2
- **Acceptance Criteria**:
  - No path leakage to the caller’s CWD (e.g., `/mnt/c/Users/.../tools/...`).
- **Validation**:
  - Run from outside repo: `/mnt/d/projects/autocapture_prime/tools/refresh_blueprint_traceability.sh`

### Task 2.3: Update Coverage Map + Gap Report
- **Location**: `tools/update_blueprint_coverage_map.py`, `tools/list_blueprint_gaps.py`
- **Description**:
  - Ensure the latest `docs/reports/blueprint-gap-*.md` is used.
  - Ensure Coverage_Map updates are deterministic.
- **Complexity**: 3
- **Validation**:
  - `tools/refresh_blueprint_traceability.sh`

## Sprint 3: Repo-Wide “Unfinished Work” Scan And Closure
**Goal**: Remove or explicitly gate unfinished code paths. User wants “no TODOs etc”.
**Demo/Validation**:
- Scan script produces either empty results or an explicitly approved allowlist.

### Task 3.1: Add Deterministic Scan Tool
- **Location**: `tools/`
- **Description**:
  - Create `tools/scan_unfinished.py` that scans tracked files for:
    - `TODO`, `FIXME`, `NOT_IMPLEMENTED`, `NotImplementedError`, `pass  # TODO`, `raise AssertionError("TODO")`, etc.
  - Output a stable JSON + Markdown report with file:line references.
  - Fail non-zero if any found, unless they match an explicit allowlist file committed in repo.
- **Complexity**: 5
- **Acceptance Criteria**:
  - Deterministic output ordering; no repo-wide heavy parsing.
- **Validation**:
  - `PYTHONPATH=. .venv/bin/python tools/scan_unfinished.py --format=md`

### Task 3.2: Fix Or Gate All Findings
- **Location**: wherever scan reports
- **Description**:
  - Implement missing pieces, remove dead code, or add explicit “future” gating with tests.
- **Complexity**: 8
- **Dependencies**: Task 3.1
- **Validation**:
  - Scan returns empty or allowlisted.

## Sprint 4: Adversarial Gate To Zero (issues=0)
**Goal**: Close all remaining adversarial redesign issues and make the gate authoritative.
**Demo/Validation**:
- `tools/run_adversarial_redesign_coverage.sh` passes with `issues=0`.

### Task 4.1: Run Gate And Capture Baseline
- **Location**: `tools/run_adversarial_redesign_coverage.sh`
- **Description**:
  - Run gate in WSL-stable mode (cap plugin hosts, thread pools).
  - Persist output as a dated report in `docs/reports/`.
- **Complexity**: 3
- **Validation**:
  - `bash tools/run_adversarial_redesign_coverage.sh`

### Task 4.2: Burn Down Remaining IDs With Traceability Updates
- **Location**: `tools/traceability/adversarial_redesign_traceability.json`, module code, tests
- **Description**:
  - For each `missing` or `partial` item:
    - Implement code change.
    - Add/adjust deterministic tests.
    - Update traceability evidence pointers (module/test/ADR).
  - Keep changes in small commits.
- **Complexity**: 10
- **Dependencies**: Task 4.1
- **Validation**:
  - Gate shows decreasing issues, ends at 0.

## Sprint 5: Full Pipeline Soak Stability (WSL Non-Crash, Ultralight Active)
**Goal**: Make “whole system soak” viable: capture ingest always durable, idle orchestrator batches heavy work, and WSL stays stable.
**Demo/Validation**:
- A 1h “mini-soak” runs without WSL crash and without spawning many python host processes.
- Full 24h soak script exists and is one-line to run.

### Task 5.1: Capture Ingest Durability Model
- **Location**: `autocapture_nx/capture/`, storage plugins
- **Description**:
  - Ensure every capture event is persisted (timestamp + metadata).
  - Pixel blobs stored full fidelity on first unique hash; duplicates reference existing blob (no loss of fidelity for unique frames).
  - Overflow spool to secondary drive when primary is pressured; auto-drain; keep empty when idle.
- **Complexity**: 8
- **Validation**:
  - Unit tests for event-vs-blob dedupe.
  - Disk pressure simulation tests.

### Task 5.2: Orchestrator Ramp-Up After 5m Idle
- **Location**: runtime governor/scheduler plugins + `autocapture_nx/runtime/`
- **Description**:
  - When user is active: capture only, no heavy processing.
  - When idle >= 300s: ramp up, batch by model (VLM/OCR), reuse loaded model weights, saturate GPU but keep CPU/RAM budgets.
  - Persist per-stage timing metrics for learning/ordering (no LLM needed; pure telemetry aggregation).
- **Complexity**: 10
- **Validation**:
  - Deterministic scheduling tests (given a fixed evidence backlog).
  - Resource budget tests (CPU/RAM <= 50% under idle processing).

### Task 5.3: WSL Process Explosion Prevention (Hard Caps + Cleanup)
- **Location**: `autocapture_nx/plugin_system/host.py`, `autocapture_nx/plugin_system/registry.py`, configs
- **Description**:
  - Default to in-proc hosting on WSL for non-network plugins.
  - Enforce a low, configurable subprocess host cap; ensure reaper kills orphans.
  - Add a CLI “doctor” check and a cleanup command to terminate stale host_runner processes.
- **Complexity**: 7
- **Validation**:
  - Integration test that plugin count does not spawn >N processes.

### Task 5.4: Produce Soak Script + One-Line Command
- **Location**: `tools/wsl/`, `ops/dev/`
- **Description**:
  - Create `tools/wsl/run_full_soak_24h.sh` that:
    - Starts kernel in soak mode.
    - Emits metrics snapshots periodically.
    - Runs capture ingest, scheduler, idle processing, and periodic query self-checks.
  - Keep the user-facing command one line.
- **Complexity**: 6
- **Validation**:
  - Dry-run mode (5 minutes) works.
  - 1-hour soak works locally.

## Testing Strategy
- Use deterministic fixtures:
  - Screenshot fixture: `docs/test sample/fixture_manifest.json` via `tools/run_fixture_pipeline.py`.
  - Optional mp4 fixture kept available but video disabled by default.
- Gate set:
  - `tools/run_adversarial_redesign_coverage.sh` (must reach 0 issues).
  - Blueprint refresh + acceptance coverage.
  - Targeted pytest/unittest suites only during iteration; full suite before merge to main.

## Potential Risks & Gotchas
- Branch protection may block direct pushes to `origin/main`; must be handled via a merge workflow.
- Adding new record types requires contract + lock updates and can break existing validators.
- “Never miss” at 0.5s active cadence can overwhelm disk if not deduping blobs; event-vs-blob dedupe must be correct and tested.
- WSL GPU stacks can crash on model reload churn; batching by model and reusing warm weights is mandatory.

## Rollback Plan
- Keep changes in small commits so regressions can be reverted without rewriting history.
- If a gate regression occurs late: revert the offending commit and re-run gate set before pushing main.

