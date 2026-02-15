# Implementation Matrix: Remaining Work (Full Repo Exhaustive, 2026-02-12)

## Scope
This matrix is generated from the full-repo miss inventory and represents every currently detected miss marker across all scanned files.

## Scan Metadata
- Generated (matrix): `2026-02-15T22:10:10.339039+00:00`
- Inventory generated: `2026-02-15T22:10:00.891633+00:00`
- Scanned files: `1452`
- Miss rows: `1`
- Gate failures: `1`

## Canonical Full List
- Full row-by-row list: `docs/reports/full_repo_miss_inventory_2026-02-12.md`
- Raw machine-readable list: `artifacts/repo_miss_inventory/latest.json`

## Category Counts
| Category | Count |
| --- | ---: |
| `doc_table_status` | 1 |

## Source Bucket Counts
| Bucket | Count |
| --- | ---: |
| `derived_report` | 1 |

## Gate Failures
| Gate | Status | Failed Step | Exit Code |
| --- | --- | --- | --- |
| `tools/run_all_tests_report.json` | `failed` | `tools/gate_static.py` | `1` |

## Source Files With Misses (Full List)
| SourceClass | Source | Total | Categories |
| --- | --- | ---: | --- |
| `derived_report` | `docs/reports/autocapture_prime_codex_implementation_matrix.md` | 1 | `doc_table_status:1` |

## Actionable Implementation Sources
| SourceClass | Source | Rows |
| --- | --- | ---: |

## Non-Actionable Generated Sources
| SourceClass | Source | Rows |
| --- | --- | ---: |
| `derived_report` | `docs/reports/autocapture_prime_codex_implementation_matrix.md` | 1 |

## Secondary Documentation Sources
| SourceClass | Source | Rows |
| --- | --- | ---: |

## Unique Requirement/Item IDs Seen In Miss Rows
- Unique IDs (all files): `0`
- Unique IDs (authoritative docs only): `0`

### IDs (Authoritative Docs)
```text
```

## Code Placeholder/TODO Misses
- Total placeholder/TODO rows: `0`
| File | Rows |
| --- | ---: |

## 4Pillars Upgrade Plan Coverage Check
- Source doc: `docs/AutocapturePrime_4Pillars_Upgrade_Plan.md`
- Method: count repo references to each `A*` / `A-*` item outside that source document.
| Item | Line | Title | External Refs | Example Refs |
| --- | ---: | --- | ---: | --- |
| `A1` | 12 | ScreenSpot-Pro benchmark + dataset patterns for high-resolution GUI grounding | 1 | docs/reports/four_pillars_traceability_map.md:12:- A1) mapped to UI grounding benchmark parity via retrieval/grounding validation harness: |
| `A2` | 16 | ScreenSpot/OSWorld-G style UI decomposition + synthesis grounding methods | 1 | docs/reports/four_pillars_traceability_map.md:18:- A2) mapped to decomposition + candidate region extraction path: |
| `A3` | 20 | OmniParser V2 for UI parsing / interactable element detection | 1 | docs/reports/four_pillars_traceability_map.md:24:- A3) mapped to structured UI IR extraction contract: |
| `A4` | 24 | GUI-Actor for coordinate-free grounding + verifier | 1 | docs/reports/four_pillars_traceability_map.md:31:- A4) mapped to verifier-style grounded answer construction: |
| `A5` | 28 | UGround (CVPR 2025) for unified grounding / segmentation | 1 | docs/reports/four_pillars_traceability_map.md:37:- A5) mapped to object/region extraction for fine-grained visual entities: |
| `A6` | 32 | UI-E2I-Synth / UI-I2E-Bench (instruction synthesis for grounding) | 1 | docs/reports/four_pillars_traceability_map.md:42:- A6) mapped to instruction-variant query evaluation coverage: |
| `A7` | 36 | Multimodal RAG reliability evaluation (RAG-Check) | 1 | docs/reports/four_pillars_traceability_map.md:49:- A7) mapped to retrieval-vs-answer separation metrics: |
| `A8` | 40 | RAG evaluation + benchmark kit (RAGAs + RAGBench) | 1 | docs/reports/four_pillars_traceability_map.md:55:- A8) mapped to deterministic RAG-style regression harness: |
| `A9` | 44 | Late-interaction retrieval (ColBERT) for higher-precision span retrieval | 1 | docs/reports/four_pillars_traceability_map.md:61:- A9) mapped to late-interaction retrieval pathway: |
| `A10` | 48 | Local serving performance: vLLM V1 + optional FlashInfer backend | 1 | docs/reports/four_pillars_traceability_map.md:67:- A10) mapped to localhost vLLM integration and throughput-safe routing: |
| `A-CORE-01` | 56 | Frame → UI IR extraction pipeline (OmniParser adapter) | 3 | docs/reports/four_pillars_traceability_map.md:16:  - Superseded by: `A-CORE-01`, `A-GROUND-01`; docs/reports/four_pillars_traceability_map.md:22:  - Superseded by: `A-CORE-01`, `A-GROUND-01`; docs/reports/four_pillars_traceability_map.md:29:  - Superseded by: `A-CORE-01` |
| `A-GROUND-01` | 66 | Grounding stage with verifier (GUI-Actor style contract) | 4 | docs/reports/four_pillars_traceability_map.md:16:  - Superseded by: `A-CORE-01`, `A-GROUND-01`; docs/reports/four_pillars_traceability_map.md:22:  - Superseded by: `A-CORE-01`, `A-GROUND-01`; docs/reports/four_pillars_traceability_map.md:35:  - Superseded by: `A-GROUND-01` |
| `A-RAG-01` | 75 | Multimodal RAG evaluation harness (RAG-Check / RAGAs style) | 3 | docs/reports/four_pillars_traceability_map.md:47:  - Superseded by: `A-RAG-01`; docs/reports/four_pillars_traceability_map.md:53:  - Superseded by: `A-RAG-01`; docs/reports/four_pillars_traceability_map.md:59:  - Superseded by: `A-RAG-01` |
| `A-INDEX-01` | 83 | Retrieval backend abstraction (dense + ColBERT optional) | 1 | docs/reports/four_pillars_traceability_map.md:65:  - Superseded by: `A-INDEX-01` |
| `A-PERF-01` | 91 | Background batch scheduler w/ budgets | 1 | docs/reports/four_pillars_traceability_map.md:72:  - Superseded by: `A-PERF-01` |

## Regenerated Misses (Actionable Clusters)
| Cluster ID | Scope | Evidence | Required Closure |
| --- | --- | --- | --- |
| MX-001 | Deterministic gates | tools/run_all_tests_report.json:tools/gate_static.py | Restore all failed gate steps to green with deterministic pass artifacts. |
| MX-006 | Report/document drift | 1 rows from generated report docs | Mark archival snapshots as informational and keep generated reports out of actionable closure criteria. |

## Notes
- This file is generated from inventory data and is intentionally exhaustive; use the actionable clusters above to prioritize implementation sequencing.
- Any regressions from this matrix should be treated as `DO_NOT_SHIP` until resolved or explicitly deferred.

