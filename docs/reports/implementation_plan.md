# Implementation plan (phase-ordered)

Source of truth: `docs/reports/implementation_matrix.md` (mapped to `docs/blueprints/autocapture_nx_blueprint.md`).

## Guiding constraints
- Plugin-first kernel; heavy work is always in plugins.
- Invisibility while ACTIVE: no OCR/VLM/embeddings/indexing/conversion while user is active.
- Evidence is append-only and immutable; derived artifacts are separate records.
- Deterministic, verifiable provenance: ledger hash chain + anchors + verify CLI.
- Offline-by-default; network only via policy-approved subprocess plugins.
- Cross-platform: Windows features are real; non-Windows uses mocks/skips to validate policy and serialization.

## Gating strategy (Pattern F)
- Add deterministic gates under `tools/` and wire them into `doctor`/`verify` so both local CLI and CI can enforce them.
- For each phase, add a single phase gate that fails if any item in the phase is incomplete.
- Gate outputs are captured under `docs/reports/gate_runs/` when run locally.
- Gate entrypoints: `python -m autocapture_nx doctor` and `python -m autocapture_nx verify <ledger|anchors|evidence>`, with `tools/run_all_tests.py` invoking doctor checks; CI can call the same entrypoints.

## Dependency strategy
- Python has no lockfile today. Adopt a single hash-locked `requirements.lock.json` generated from `pyproject.toml` constraints.
- Lock updates are explicit and documented; CI verifies lock drift.
- Heavy ML deps (torch/transformers/sentence-transformers) move to optional extras with lazy imports inside plugins.
- Offline constraints: any feature requiring missing deps must be optional and reported by doctor; the base system remains functional.
- Lock tooling: `python tools/generate_dep_lock.py` writes `requirements.lock.json`; `python tools/gate_deps_lock.py` verifies the lock against `pyproject.toml`.

## Data migration strategy
- Introduce explicit storage versioning and migrations for metadata/media layout changes.
- Provide a migration command that is copy+verify only (no automatic delete).
- Preserve append-only evidence; derived artifacts may be compacted in a separate process.
- Add a startup recovery scanner that reconciles partial segment writes and journal/ledger state.

## Phase plan

### Phase 0 (I084–I095, I126): Scaffolding and gates
- I084/I087/I088: split heavy ML deps into extras; package builtin plugins as data; add deterministic lockfile.
- I085/I086/I126: package-safe paths; platformdirs defaults; deterministic directory hashing across OS.
- I089/I090/I091: canonical JSON gate; concurrency gate; golden ledger+anchor gate.
- I092/I093/I094/I095: perf/security/static analysis gates; expand doctor checks.
- Phase 0 gate: `tools/gate_phase0.py` (fails if any Phase 0 item lacks tests/gates).

### Phase 1 (I001–I015, I096–I100, I123–I125): Correctness + immutability blockers
- I006/I099/I100: run_id propagation and cached policy hash.
- I001/I010/I097/I098: canonical JSON enforcement and EventBuilder; add record_type everywhere.
- I007/I008: thread-safe ledger/journal with centralized sequencing.
- I009/I096: fail-closed DPAPI / decrypt errors when encryption_required.
- I012/I013/I014/I015: config alignment, portability, plugin compat checks, contract lock verification.
- I005/I123/I124/I125: immutability enforcement and lifecycle ledger entries.
- Phase 1 gate: `tools/gate_phase1.py` (includes immutability + run_id + DPAPI fail-closed tests).

### Phase 2 (I016–I025, I105–I113): Capture pipeline refactor
- I016/I017/I003/I002: split grab→encode→write pipeline; bounded queues; backpressure affects capture.
- I018/I105/I106: replace zip-of-JPEG with real container; if legacy zip stays, use ZIP_STORED + streaming writes.
- I019: GPU backend detection and safe fallback.
- I020/I021/I011: segment timestamps, capture parameters, monotonic timing.
- I022/I023/I112/I113/I107/I111: window/input/cursor correlation and batching.
- I024/I025: disk pressure degrades quality before stop; atomic segment writes.
- I004/I109/I110: move audio writes off realtime callbacks; derived audio artifacts; WASAPI loopback.
- Phase 2 gate: `tools/gate_phase2.py` (capture pipeline bounded memory + timing determinism).

### Phase 3 (I026–I034, I101–I104, I108, I128–I130): Storage scaling + durability
- I026/I027: SQLCipher default when available; indexes on ts_utc/record_type/run_id.
- I028/I029/I101: binary encrypted media + streaming encryption + content_hash on put.
- I030/I031/I032/I033/I034: immutability primitives; reversible ID encoding; sharding; per-run manifests; fsync policy.
- I102/I103/I104: explicit partial failure tracking; segment sealing ledger entry; startup recovery scan.
- I108: compact binary input log (derived) + JSON summary.
- I128/I129/I130: migration tooling; disk forecasting and alerts; compaction for derived only.
- Phase 3 gate: `tools/gate_phase3.py` (durability, recovery, content_hash, immutability).

### Phase 4 (I035–I043, I065–I077, I118, I127): Retrieval + provenance + citations
- I035/I036/I037/I118: tiered indexed retrieval with deterministic ordering and versioned indices.
- I065/I066/I067/I068/I069/I127: canonical evidence model, hash everything, ledger state transitions, anchors, per-run manifests with env fingerprint.
- I038/I039/I040/I072/I073/I074/I075: derived artifacts; ledger query/extraction; derivation graphs; model identity; text normalization.
- I041/I042/I043/I070/I071: citations point to immutable evidence spans; resolver validates hashes/anchors; fail closed.
- I076/I077: proof bundles export and replay mode.
- Phase 4 gate: `tools/gate_phase4.py` (citation resolution + proof bundle verification).

### Phase 5 (I044–I048, I116–I117): Scheduler / governor
- I044/I045/I046/I047/I048: scheduler plugin honors activity signals; capture telemetry feeds backpressure; immediate ramp-down.
- I116/I117: model execution budgets per idle window + preemption/chunking.
- Phase 5 gate: `tools/gate_phase5.py` (ACTIVE mode blocks heavy jobs deterministically).

### Phase 6 (I049–I064, I119–I120): Security + egress hardening
- I049/I050: kernel network denied by default; egress via subprocess gateway.
- I051/I052/I053/I054/I055/I056/I057: real capability bridging; least privilege; filesystem policy; job object limits; env sanitization; RPC timeouts + size limits.
- I058/I059/I060/I061/I062/I063/I064: hardened hashing; vault ACLs; key separation; anchor signing; verify commands; security audit events; dep pin/hash checks.
- I119/I120: tokenizer versioning + ledgered sanitized egress packets.
- Phase 6 gate: `tools/gate_phase6.py` (network guard, DPAPI fail-closed, egress policy).

### Phase 7 (I078–I083, I121): FastAPI UX facade + Web Console
- I078/I079: UX facade is canonical; CLI calls shared facade logic.
- I080/I081/I082/I083: web console UI; alerts panel; local-only auth boundary; websocket telemetry.
- I121: egress approval workflow in UI.
- Phase 7 gate: `tools/gate_phase7.py` (API parity + auth boundary + websocket smoke test).

### Phase 8 (I114–I115, I122): Optional expansion plugins
- I114/I115: clipboard + file activity plugins as subprocess-hosted, disabled by default.
- I122: plugin hot-reload with hash verification + safe swap.
- Phase 8 gate: `tools/gate_phase8.py` (hot-reload verification + plugin hash checks).

## Cross-platform strategy
- Windows-specific features (DPAPI, job objects, desktop duplication) remain real.
- Linux/CI uses mocks for Windows APIs but fully validates policy, canonical JSON, and determinism.
- Tests should be OS-conditional with explicit skips and mock coverage.

## Risk register
See `docs/reports/risk_register.md`.
