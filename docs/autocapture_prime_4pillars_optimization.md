# Autocapture Prime --- 4 Pillars Full Optimization Plan

Target Machine: Windows 11 \| 64GB RAM \| RTX 4090 \| Single User \|
Offline-First

------------------------------------------------------------------------

# Executive Summary

This document defines a complete optimization strategy for Autocapture
Prime, strictly aligned to the 4 Pillars:

P1 Performant --- Fast ingestion + fast query on 4090-class hardware\
P2 Accurate --- Deterministic, schema-driven, fail-closed answers\
P3 Secure --- Offline-first, least-privilege, hardened boundaries\
P4 Citable --- Every answer claim traceable to immutable derived
evidence

Primary Backbone: WSL processing + Query engine\
Capture & UI are supporting layers.

------------------------------------------------------------------------

# Current Architecture Summary

Core: - autocapture_nx kernel - plugin-forward system - WSL2 queue for
GPU-heavy work - Derived evidence storage - Query arbitration (state +
classic)

Sidecar: - Windows capture (screenshots, audio, HID) - Local VLM
endpoint (localhost)

------------------------------------------------------------------------

# Pillar Optimization Plan

## P1 --- Performant

### 1. Replace Dual Query Execution

Current: Always run both state and classic paths. Upgrade: - Run primary
path first. - Compute deterministic groundedness score. - Only run
secondary path if required.

Acceptance: - Median latency decreases. - No regression in strict
evaluation suite.

### 2. WSL Queue Optimization

Replace directory scanning with: - Token semaphore model - Idempotent
job protocol - Batch dispatch of GPU tasks

Acceptance: - Sustained ingest without dropped jobs. - Stable memory and
queue depth.

### 3. Hardware-Aware Defaults

Create profile: personal_windows_4090 - Default GPU-heavy tasks to WSL -
Auto-benchmark capture backend - Validate vLLM endpoint on setup

Acceptance: - One-command setup succeeds. - Capture FPS meets target
without UI lag.

------------------------------------------------------------------------

## P2 --- Accurate

### 1. Remove Keyword-Based Query Routing

Replace query-text routing with: - Schema/capability-based planner -
Evidence-driven path selection

Acceptance: - Paraphrase tests produce identical plans + results.

### 2. Strict Evaluation Gate

Convert all advanced tests to strict deterministic mode. Add N=3
deterministic rerun gate with drift detection.

Acceptance: - 20/20 strict passes - Zero drift across 3 consecutive runs

### 3. Observation Graph Required

Fail closed if observation graph plugin unavailable.

Acceptance: - Missing plugin blocks golden profile.

------------------------------------------------------------------------

## P3 --- Secure

### 1. Enforced Network Guard

Wrap all plugins in network_guard. Only gateway plugin may egress with
approvals.

### 2. Raw Evidence Egress Ban

Explicit validator preventing raw screenshots/audio/HID leaving system.

### 3. WSL Queue Hardening

-   Restricted directory permissions
-   Content hash validation for all jobs

### 4. Optional Firewall Lockdown Mode

Block all outbound except localhost + WSL bridge.

Acceptance: - Non-gateway plugins cannot egress. - Policy violations
fail closed.

------------------------------------------------------------------------

## P4 --- Citable

### 1. Producer Metadata on All Derived Records

Persist: - plugin id - stage id - timestamp - input hashes

### 2. Claim-Level Citation Format

Every answer must contain: - Claim list - Record references - Producer
attribution

### 3. Attribution Coverage Report

Add effectiveness report: - % of answer derived from each plugin stage

Acceptance: - All non-trivial answers traceable. - Missing provenance
causes failure.

------------------------------------------------------------------------

# TTFS (Time to First Success)

Add command:

    autocapture setup --profile personal_4090

Performs: - Sidecar wiring - Endpoint health check - Fixture ingest -
Sample query

Success defined as: - Deterministic answer returned - Citation payload
present - Trace artifact stored

------------------------------------------------------------------------

# Golden Version Quality Gates

Golden Gate Command:

    autocapture gate --profile golden_qh

Runs: - Plugin lock validation - Endpoint health checks - Strict
advanced suite - Deterministic reruns - Drift detection

Definition of Done: - All strict tests pass - No drift - Performance
within SLO - No network violations

------------------------------------------------------------------------

# Master Backlog (Condensed)

  ID         Category                              Pillars   Priority
  ---------- ------------------------------------- --------- ----------
  QRY-001    Replace keyword routing               P2,P4     P0
  QRY-002    Conditional dual-path execution       P1,P2     P0
  EVAL-001   Strict evaluation suite               P2,P4     P0
  ATTR-001   Per-plugin provenance metadata        P4        P0
  WSL-001    Semaphore queue refactor              P1        P0
  SEC-001    Enforced network guard                P3        P0
  SEC-002    Raw evidence egress validator         P3,P4     P0
  CAP-001    4090 optimized profile                P1        P1
  AUD-001    Audio fingerprint extraction          P2,P4     P1
  INP-001    Canonical activity timeline records   P2,P4     P1

------------------------------------------------------------------------

# Final State Vision

Autocapture Prime becomes:

-   Deterministic
-   Schema-driven
-   Fully citable
-   Offline-first
-   GPU-optimized
-   Drift-gated
-   Fail-closed

Every question is either: 100% correct and provably grounded OR
Explicitly indeterminate

No shortcuts. No hidden routing heuristics. No silent regressions.
