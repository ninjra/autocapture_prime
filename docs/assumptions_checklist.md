# ASSUMPTIONS CHECKLIST (Expanded, 4-Pillar Optimized)

This document expands `docs/assumptions.md` into an actionable checklist with explicit 4-pillar mapping.
It also consolidates *all* current TODO / stub / placeholder markers found in the repo so nothing is
left undocumented.

Pillars (from `docs/autocapture_mx_blueprint.md`):
- P1 Performant
- P2 Accurate
- P3 Secure
- P4 Citable

---

## A) Expanded assumptions checklist (source: `docs/assumptions.md`)

Each item below is expanded with: current state, pillar risk, recommended work, and acceptance criteria.

1) Desktop Duplication + NVENC capture backend not implemented; Windows capture uses mss + JPEG fallback.
   - Source: `docs/assumptions.md:3-5`
   - Pillars at risk: P1 (performance/overhead), P2 (accuracy/quality), P4 (citable evidence quality)
   - Current state: capture uses `plugins/builtin/capture_windows/plugin.py` + `autocapture_nx/windows/win_capture.py` (mss + JPEG)
   - Recommended work:
     - Implement Desktop Duplication + NVENC pipeline with fallback to current mss/JPEG path.
     - Add capture backend selection in config to honor `capture.video.backend`.
     - Add Windows integration benchmarks for capture throughput and encoding quality.
   - Acceptance criteria:
     - Desktop Duplication + NVENC path selectable and works on supported GPUs.
     - Capture continues when NVENC unavailable via fallback.
     - Benchmarks recorded and regressions tracked.

2) Root keys stored in DPAPI-protected keyring file; non-Windows uses raw files.
   - Source: `docs/assumptions.md:7-9`
   - Pillars at risk: P3 (secure key handling), P4 (provenance integrity if keys compromised)
   - Current state: `plugins/builtin/storage_encrypted/plugin.py` uses file-backed keyring; Windows uses DPAPI.
   - Recommended work:
     - Integrate Windows Credential Manager or hardware-backed vault for root key storage.
     - Document migration/rollback path for existing keys.
   - Acceptance criteria:
     - Root key material never stored unprotected on Windows.
     - Key migration path tested and documented.

3) Key rotation is user-invoked and assumed to run during IDLE_DRAIN or explicit intent.
   - Source: `docs/assumptions.md:11-13`
   - Pillars at risk: P1 (runtime impact), P3 (key hygiene), P4 (ledger continuity)
   - Current state: `autocapture_nx/kernel/key_rotation.py` + CLI `autocapture keys rotate`.
   - Recommended work:
     - Add scheduler gating to enforce runtime mode (IDLE_DRAIN only) unless user overrides.
     - Add background rekey job with explicit rate limits and progress reporting.
   - Acceptance criteria:
     - Rotation is blocked during ACTIVE_CAPTURE_ONLY unless explicitly overridden.
     - Ledger and metadata remain consistent across rotations.

4) Name detection uses heuristic regex (capitalized multi-word sequences).
   - Source: `docs/assumptions.md:15-17`
   - Pillars at risk: P2 (accuracy of redaction/sanitization), P3 (privacy leakage), P4 (citation correctness)
   - Current state: name detection in sanitizer is regex-based.
   - Recommended work:
     - Upgrade to local NER model or hybrid rule+model recognizer.
     - Add evaluation suite with known PII cases.
   - Acceptance criteria:
     - False-negative rate reduced on benchmark set.
     - Sanitization remains deterministic and reversible where required.

5) Anchor store is separate path by default but remains on same machine unless configured otherwise.
   - Source: `docs/assumptions.md:19-21`
   - Pillars at risk: P4 (provenance tamper resistance), P3 (trust domain separation)
   - Current state: anchor path configured in `config/default.json` and checked in `Kernel.doctor`.
   - Recommended work:
     - Support second trust domain (registry / credential manager / remote drive).
     - Add verification that anchor storage is on distinct trust boundary.
   - Acceptance criteria:
     - Anchor store can be configured to a distinct trust domain.
     - Doctor checks fail if anchor storage is co-located with data store.

6) Plugin sandboxing is Python-level + Windows JobObject; no full OS sandbox yet.
   - Source: `docs/assumptions.md:23-25`
   - Pillars at risk: P3 (secure isolation), P1 (overhead controls)
   - Current state: network guard enforced; no OS-level sandboxing.
   - Recommended work:
     - Add OS sandbox / process isolation for plugin hosts (Windows JobObject + restricted tokens).
     - Harden subprocess host permissions and IPC boundaries.
   - Acceptance criteria:
     - Plugin hosts run with reduced privileges and explicit deny lists.
     - Documented escape paths eliminated or mitigated.

7) Windows capture/audio/input plugins rely on optional third-party dependencies.
   - Source: `docs/assumptions.md:27-29`
   - Pillars at risk: P1 (performance variability), P2 (processing coverage), P3 (supply-chain risk)
   - Current state: optional deps are imported at runtime; tests are Windows-only.
   - Recommended work:
     - Pin dependency versions and add a Windows integration test suite.
     - Provide deterministic dependency checks in doctor output.
   - Acceptance criteria:
     - Windows CI/bench suite validates dependency presence and behavior.
     - Failure modes surface clear diagnostics.

8) SQLCipher metadata store requires `pysqlcipher3` and is not exercised in non-Windows tests.
   - Source: `docs/assumptions.md:31-33`
   - Pillars at risk: P3 (encryption at rest), P4 (ledger evidence storage)
   - Current state: SQLCipher path optional; non-Windows tests tolerate missing dep.
   - Recommended work:
     - Add Windows DB integration tests and verify encrypted store on real SQLCipher.
     - Provide fallback path with explicit warnings when SQLCipher missing.
   - Acceptance criteria:
     - SQLCipher path verified in Windows integration tests.
     - Non-Windows test output documents skip rationale.

9) Subprocess plugin host implemented but most built-ins allowlisted in-proc.
   - Source: `docs/assumptions.md:35-37`
   - Pillars at risk: P3 (isolation), P1 (resource containment)
   - Current state: in-proc allowlist exists in `config/default.json`.
   - Recommended work:
     - Expand RPC bridging so more plugins can run out-of-proc.
     - Add performance budget checks for cross-proc calls.
   - Acceptance criteria:
     - More built-ins can run out-of-proc without capability loss.
     - Measured overhead fits P1 targets.

10) Runtime governor only selects modes; worker suspension and VRAM release not enforced.
    - Source: `docs/assumptions.md:39-41`
    - Pillars at risk: P1 (overhead), P3 (safe mode), P2 (predictable operation)
    - Current state: `plugins/builtin/runtime_governor/plugin.py` selects modes only.
    - Recommended work:
      - Implement worker group suspension and VRAM release policies.
      - Tie enforcement to runtime mode transitions with deadlines.
    - Acceptance criteria:
      - Active user input triggers immediate suspend/release.
      - Idle window resumes processing within configured budgets.

11) UI plugins (loopback web/overlay) are not implemented.
    - Source: `docs/assumptions.md:43-45`
    - Pillars at risk: P2 (operator visibility), P3 (secure UI), P4 (citation UI fidelity)
    - Current state: no UI plugins present.
    - Recommended work:
      - Implement loopback web/overlay plugins with CSRF + origin pinning tests.
      - Ensure UI/CLI parity through UX facade.
    - Acceptance criteria:
      - UI plugins available with security checks and test coverage.
      - UI displays citable spans and provenance metadata.

12) Retrieval uses lexical matching; vector indices and reranker integration not wired in.
    - Source: `docs/assumptions.md:47-49`
    - Pillars at risk: P2 (accuracy), P4 (citation relevance), P1 (efficiency)
    - Current state: `plugins/builtin/retrieval_basic/plugin.py` uses lexical matching.
    - Recommended work:
      - Implement vector index builder and integrate embedder + reranker.
      - Add golden query suite to validate recall/precision.
    - Acceptance criteria:
      - Retrieval supports lexical + vector + rerank with deterministic scoring.
      - Golden query suite passes with documented thresholds.

13) Windows permission matrix and degraded-mode policy checks are not implemented.
    - Source: `docs/assumptions.md:51-53`
    - Pillars at risk: P3 (secure operation), P1 (safe degradation)
    - Current state: doctor checks exist but no permission matrix.
    - Recommended work:
      - Add doctor checks for Windows permission matrix and degraded-mode policy.
      - Add Windows integration tests for permission failure scenarios.
    - Acceptance criteria:
      - Doctor report surfaces permission gaps with actionable remediation.
      - Degraded-mode policy verified with tests.

---

## B) Repo-wide TODO / stub / placeholder registry

This section consolidates *all* TODOs, placeholders, and stubs currently present in the repo.
Each entry references its source file.

### B1) Explicit TODOs
- YAML parsing decision without new deps. `docs/autocapture_mx_implementation_plan.md:240`
- CLI wiring in `pyproject.toml` (new console script vs reuse). `docs/autocapture_mx_implementation_plan.md:241`
- Windows-only functionality safely skipped or mocked in tests. `docs/autocapture_mx_implementation_plan.md:242`

### B2) Spec placeholders / missing values
- Spec placeholder file with `[MISSING_VALUE]` entries. `docs/spec/README.md:5` + `docs/spec/autocapture_nx_blueprint_2026-01-24.md`.

### B3) Stub or placeholder plugin implementations
- Capture stub raises `NotImplementedError`. `plugins/builtin/capture_stub/plugin.py:17-18`
- VLM stub labeled placeholder; requires local model files. `plugins/builtin/vlm_stub/plugin.py:1`
- Embedder/OCR/Reranker stubs are minimal local implementations with optional deps and fixed model paths.
  - `plugins/builtin/embedder_stub/plugin.py`
  - `plugins/builtin/ocr_stub/plugin.py`
  - `plugins/builtin/reranker_stub/plugin.py`

### B4) Stubbed behavior in non-plugin logic
- Egress gateway returns a stub response (no real network I/O). `plugins/builtin/egress_gateway/plugin.py:74-76`
- MX implementation plan explicitly permits placeholder citation overlay images. `docs/autocapture_mx_implementation_plan.md:192`

### B5) Configured stub plugin IDs
- Stub plugin IDs included in default pack and enabled list. `config/default.json:168-226`
- Stub plugin IDs pinned in lockfile. `config/plugin_locks.json`
- Stub plugin IDs listed in IR pins. `contracts/ir_pins.json`

---

## C) Follow-up notes (documentation only)

- This checklist is deliberately additive and does not change any code paths.
- For any future implementation steps, follow the "fail closed" rule (add TODOs rather than guessing commands).
- Align all remediation work with the four pillars and update this checklist as tasks are completed.

