# Roadmap (Adversarial Redesign Phases)

This roadmap mirrors the phased plan outlined in `docs/autocapture_prime_adversarial_redesign.md`.

## Phase 0 (2026-02-06 to 2026-02-20)

Goal: Harden boot + state safety and reduce footguns that can silently corrupt provenance.

- Instance lock for `data_dir` (FND-01).
- Atomic writes for critical JSON state/config (FND-02).
- Provenance headers everywhere (META-03) and safe-mode visibility (FND-10).
- Misclick-resistant dangerous toggles (UX-06).
- Contract pinning and doctor gates (RD-05).

## Phase 1 (2026-02-21 to 2026-03-31)

Goal: Operator-grade plugin management with explicit policies, diffs, and rollback.

- Plugin lifecycle states and UI/CLI flows (EXT-01..03).
- Compatibility gating and dry-run plan/apply (EXT-04..05).
- Permission diffs and sandbox policy surfacing (EXT-06..07).
- Health checks, last-error visibility (EXT-08..09).
- Plugin lock SBOM metadata + signatures (EXT-10..11).
- Capabilities matrix page (EXT-12).

## Phase 2 (2026-04-01 to 2026-05-31)

Goal: Deterministic, citeable replay and exports; privacy boundaries for egress/export.

- Pipeline DAG + replay + proof bundles and verification (EXEC-04, QA-08).
- Signed proof bundles and tamper detection (SEC-07).
- Export redaction maps at explicit boundaries (SEC-05).
- Key rotation hardening and staged rewrap (SEC-06).

## Phase 3 (2026-06-01 to 2026-07-31)

Goal: Make the system fast under real workloads without sacrificing provenance.

- Incremental indexing + derived-step caching (PERF-02..03).
- WSL2 worker round-trip (PERF-04) + optional GPU routing (PERF-05).
- Streaming I/O for large exports (PERF-06).
- Resource usage visibility and deterministic throttling (PERF-08).

