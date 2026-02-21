# Autocapture Prime 4 Pillars Optimization Matrix

Source: `docs/autocapture_prime_4pillars_optimization.md`

| ID | Status | Evidence | Notes |
| --- | --- | --- | --- |
| QRY-001 | complete | `autocapture_nx/kernel/query.py`; `tests/test_query_intent_routing.py` | Keyword marker routing replaced with capability/schema-token planner and paraphrase-stability coverage tests. |
| QRY-002 | complete | `autocapture_nx/kernel/query.py`; `tests/test_query_arbitration.py` | Query path now runs primary first, executes secondary only when groundedness thresholds fail, and records arbitration reason. |
| EVAL-001 | complete | `tools/run_golden_qh_cycle.sh`; `tools/q40.sh`; `tools/eval_q40_matrix.py`; `tests/test_eval_q40_matrix.py` | Strict matrix semantics now fail closed: `matrix_evaluated==0` always fails, strict mode rejects skipped rows, and machine-readable `failure_reasons[]` are emitted. |
| EVAL-002 | complete | `tools/release_gate.py`; `tests/test_release_gate.py` | Release-gate strict marker scan now treats matrix artifacts with `matrix_evaluated<=0`, `matrix_skipped>0`, or `matrix_failed>0` as non-pass. |
| PIPE-001 | complete | `tools/run_advanced10_queries.py`; `config/profiles/golden_full.json`; `config/profiles/golden_qh.json`; `tests/test_run_advanced10_expected_eval.py`; `tests/test_golden_full_profile_lock.py` | Option A contract is enforced: metadata-only query runs do not pass screenshot paths, query-time hard-VLM is forced off, and golden retention is nightly + processed-image-only with 6-day horizon. |
| ATTR-001 | complete | `autocapture_nx/kernel/derived_records.py`; `autocapture_nx/kernel/query.py`; `tests/test_derived_records.py` | Producer/stage/input provenance metadata is now attached to derived records and query-derived artifacts. |
| WSL-001 | complete | `autocapture/runtime/wsl2_queue.py`; `autocapture/runtime/scheduler.py`; `tests/test_wsl2_job_roundtrip.py` | WSL queue now enforces token semaphore, idempotent dispatch by job key, and deterministic token release on response ingest. |
| SEC-001 | complete | `autocapture_nx/kernel/loader.py`; `autocapture_nx/plugin_system/runtime.py`; `tests/test_kernel_network_deny.py`; `tests/test_plugin_network_block.py` | Network guard is enforced and fail-closed outside allowed gateway scopes. |
| SEC-002 | complete | `plugins/builtin/egress_sanitizer/plugin.py`; `tests/test_export_sanitization.py`; `tests/test_egress_requires_approval_by_default.py` | Raw evidence egress is blocked/sanitized by policy gate + sanitizer path. |
| CAP-001 | complete | `config/profiles/personal_4090.json`; `autocapture_nx/cli.py` (`setup`) | 4090-oriented profile + setup command implemented. |
| AUD-001 | complete | `plugins/builtin/audio_windows/plugin.py`; `tests/test_audio_fingerprint.py` | Audio capture now emits deterministic `derived.audio.fingerprint` records with provenance and stable feature hashes. |
| INP-001 | complete | `plugins/builtin/input_windows/plugin.py`; `plugins/builtin/cursor_windows/plugin.py`; `tests/test_input_batching.py`; `tests/test_cursor_timeline_plugin.py` | Canonical activity timeline records are persisted (input batch + cursor timeline). |

Observation-graph gate: `builtin.observation.graph` is required in golden profiles and enforced fail-closed when required plugin gates run.
