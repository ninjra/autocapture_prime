# Full Repo Miss Inventory

- Generated: `2026-02-15T22:10:00.891633+00:00`
- Scanned files: `1452`
- Miss rows: `1`
- Gate failures: `1`

## Source Classes
| Source Class | Count |
| --- | ---: |
| `derived_report` | 1 |

## Gate Failures
| Gate | Status | Failed Step | Exit Code |
| --- | --- | --- | --- |
| `tools/run_all_tests_report.json` | `failed` | `tools/gate_static.py` | `1` |

## Miss Rows
| Category | Item | SourceClass | Source | Line | Reason | Snippet |
| --- | --- | --- | --- | ---: | --- | --- |
| `doc_table_status` | `-` | `derived_report` | `docs/reports/autocapture_prime_codex_implementation_matrix.md` | 24 | table row contains open/partial/missing marker | \| 6. Definition of done gates \| partial \| Core surfaces are implemented and test-covered; full end-to-end run with live sidecar zstd+protobuf payloads and live vLLM latency benchmarks remains an operational validation step. \| |

