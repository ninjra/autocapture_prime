# Plan: `codex_work_order_autocapture_prime_memory.md` Implementation

Generated: 2026-02-17  
Source: `docs/codex_work_order_autocapture_prime_memory.md`  
Status: Design complete, implementation-ready

## 1) Skill Usage By Section (explicit)

| Work-order section | Skills | Why these skills | Design output |
|---|---|---|---|
| `0) Goals and non-goals` | `plan-harder` | Enforces strict scope boundaries and implementation sequencing. | Scope guardrails, explicit non-goals, phase gates. |
| `1) Output contract` | `evidence-trace-auditor`, `config-matrix-validator` | Contract must be deterministic, hash-verifiable, and config-driven. | Canonical NDJSON schema, hash-chain rules, export-root resolution matrix. |
| `2) Exporter approach` | `ccpm-debugging`, `logging-best-practices` | Fail-soft behavior depends on robust fault handling and actionable telemetry. | Deterministic selection heuristics, fail-soft flow, error taxonomy. |
| `3.1) Export module` | `plan-harder`, `python-testing-patterns` | Module structure must be testable and decomposed into deterministic units. | File/function design + dependency graph + unit-test seams. |
| `3.2) CLI command` | `plan-harder`, `shell-lint-ps-wsl` | CLI UX must be stable and cross-shell runbooks must be correct. | Command surface, options, exit-code contract, follow-loop behavior. |
| `3.3) Unit tests` | `python-testing-patterns`, `deterministic-tests-marshal` | Requires deterministic fixtures and flake prevention. | Test matrix for schema/hash/fail-soft/idempotency behavior. |
| `3.4) Documentation` | `doc` | Handoff quality and operator clarity matter for Hypervisor integration. | `docs/chatgpt_export.md` structure and required sections. |
| `4) No new external requirements` | `config-matrix-validator` | Must prove optional OCR and no new mandatory services. | Dependency matrix and expected runtime behavior per environment. |
| `5) Run instructions` | `shell-lint-ps-wsl`, `golden-answer-harness` | Commands must be correct and acceptance checks reproducible. | Exact run/verify commands + artifact inspection steps. |
| `6) Deliverables checklist` | `golden-answer-harness`, `evidence-trace-auditor` | Every checklist item needs objective evidence. | Checklist-to-test mapping with pass criteria. |

## 2) Architecture Design

### 2.1 New module
- File: `autocapture_nx/kernel/export_chatgpt.py`
- Responsibility: read capture evidence + metadata + journal, extract transcript text, sanitize, append hash-chained NDJSON.
- No network IO, no process lifecycle management, no capture-loop coupling.

### 2.2 Data flow
1. Resolve export root and output file path.
2. Stream `journal.ndjson` and keep `event_type == "capture.segment"` entries.
3. Build/query window metadata index from `storage.metadata` (`record_type == "evidence.window.meta"`).
4. For candidate segments:
- load media blob from `storage.media.get(segment_id)`.
- open zip container and select `frame_0`, `frame_mid`, `frame_last`.
5. OCR extraction (if `ocr.engine` exists), then text normalization/filtering.
6. Sanitization and leak-check via `privacy.egress_sanitizer`.
7. Append canonical line to `chatgpt_transcripts.ndjson` with `prev_hash`/`entry_hash`.
8. Write idempotency marker to metadata store: `export.chatgpt.<segment_id>`.

### 2.3 Deterministic selection policy
- Segment accepted when nearest prior window meta within lookback window (default 10s) indicates Edge (`msedge` in `process_path`).
- High confidence if title contains `chatgpt`/`openai` (case-insensitive).
- Otherwise accepted only if OCR text contains `chatgpt` token.
- Frame selection is always index-based (`0`, `mid`, `last`) to stay reproducible.

## 3) File-Level Implementation Plan

### 3.1 `autocapture_nx/kernel/export_chatgpt.py` (new)
- `resolve_export_root(config: dict[str, Any]) -> Path`
- `iter_capture_segments(journal_path: Path, since_ts: str | None) -> Iterator[dict[str, Any]]`
- `load_window_index(metadata_store: Any) -> list[dict[str, Any]]`
- `match_window_for_segment(window_index: list[dict[str, Any]], segment_ts_utc: str, lookback_s: int) -> dict[str, Any] | None`
- `iter_selected_frames(zip_bytes: bytes, frame_count: int) -> Iterator[tuple[str, bytes]]`
- `extract_text(system: Any, image_bytes: bytes) -> str`
- `sanitize_text(system: Any, text: str) -> tuple[str, list[dict[str, Any]], bool, str | None]`
- `read_prev_hash(export_path: Path) -> str | None`
- `append_export_line(export_path: Path, obj: dict[str, Any], prev_hash: str | None) -> str`
- `run_export_pass(system: Any, *, max_segments: int | None, since_ts: str | None) -> dict[str, Any]`

### 3.2 `autocapture_nx/cli.py` (edit)
- Add command group: `export`
- Add subcommand: `chatgpt`
- Flags:
  - `--max-segments N`
  - `--since-ts ISO`
  - `--follow`
- Runtime behavior:
  - boot system once;
  - execute `run_export_pass`;
  - in follow mode, sleep 2s loop and continue fail-soft.

### 3.3 `tests/test_export_chatgpt.py` (new)
- Deterministic fixtures:
  - synthetic journal lines (`capture.segment`)
  - fake metadata store with `evidence.window.meta`
  - zip blob with 3 image frames
  - OCR stub and sanitizer stub
- Assertions:
  - schema required fields
  - hash-chain correctness (`prev_hash`, `entry_hash`)
  - idempotency marker behavior
  - OCR missing/failure remains non-fatal
  - leak-check failure emits empty `text` + notice

### 3.4 `docs/chatgpt_export.md` (new)
- Purpose and scope
- command usage
- output location and schema
- hash-chain semantics
- fail-soft behavior and troubleshooting
- Hypervisor ingest contract link

## 4) Section-by-Section Acceptance Design

### Section 0 acceptance
- No new remote dependencies.
- Capture path unaffected when exporter fails.

### Section 1 acceptance
- Every NDJSON line has required keys:
  - `schema_version`, `entry_id`, `ts_utc`, `source`, `segment_id`, `frame_name`, `text`, `glossary`, `prev_hash`, `entry_hash`
- `entry_hash = sha256(canonical_json_without_entry_hash + (prev_hash or ""))`

### Section 2 acceptance
- Deterministic segment/frame selection.
- OCR unavailable path produces non-crashing partial export.
- Sanitizer applied with scope `"chatgpt"` for all exported text.

### Section 3 acceptance
- CLI command available and functional.
- Export pass supports idempotent reruns.
- Unit tests cover success + negative paths.
- Operator doc exists and matches behavior.

### Section 4 acceptance
- Exporter runs with OCR present or absent.
- No network calls introduced.

### Section 5 acceptance
- One-shot and follow modes documented and executable.
- Output artifacts validated via test/inspection steps.

### Section 6 acceptance
- Work-order checklist mapped to tests/docs with objective evidence.

## 5) Phased Delivery Plan

### Phase A: Contract-first scaffolding
- Add module with hash-chain primitives and export-root resolver.
- Add tests for contract and hashing only.

### Phase B: Extraction and sanitization
- Implement journal scan, window matching, frame extraction, OCR/sanitize pipeline.
- Add deterministic tests for heuristics and fail-soft behavior.

### Phase C: CLI and idempotency
- Wire `export chatgpt` command and follow loop.
- Add marker persistence and rerun-skip tests.

### Phase D: Documentation and release gate
- Author `docs/chatgpt_export.md`.
- Run focused tests and checklist verification.

## 6) Risks and Mitigations

- OCR variability:
  - mitigation: deterministic filtering and optional OCR path.
- Large journals:
  - mitigation: stream parse, no full-load.
- Metadata sparsity:
  - mitigation: explicit skip reasons, fail-soft counters.
- Hash-chain corruption from manual edits:
  - mitigation: explicit integrity check in tests and diagnostics output.

## 7) Verification Matrix

| Requirement | Evidence |
|---|---|
| append-only NDJSON export | `tests/test_export_chatgpt.py::test_append_only_lines` |
| hash chain correctness | `tests/test_export_chatgpt.py::test_hash_chain` |
| sanitizer integration + glossary | `tests/test_export_chatgpt.py::test_sanitized_text_and_glossary` |
| leak-check fail-safe | `tests/test_export_chatgpt.py::test_leak_check_failure_empties_text` |
| fail-soft OCR missing | `tests/test_export_chatgpt.py::test_missing_ocr_is_nonfatal` |
| CLI command exists | `python -m autocapture_nx.cli export chatgpt --help` |
| follow mode loops safely | `tests/test_export_chatgpt.py::test_follow_mode_nonfatal_loop_step` |

## 8) Definition of Done

- `autocapture export chatgpt` implemented.
- `chatgpt_transcripts.ndjson` generated as append-only canonical NDJSON with valid hash chain.
- Sanitization + glossary present on all lines.
- Export failures are fail-soft and do not impact capture pipeline.
- Deterministic tests added and passing for schema/hash/fail-soft/idempotency paths.
- Operator documentation complete (`docs/chatgpt_export.md`).
