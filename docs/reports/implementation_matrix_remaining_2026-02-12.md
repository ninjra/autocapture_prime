# Implementation Matrix: Remaining Work (Full Repo Exhaustive, 2026-02-12)

## Scope
This matrix is generated from the full-repo miss inventory and represents every currently detected miss marker across all scanned files.

## Scan Metadata
- Generated (matrix): `2026-02-13T19:28:30.959903+00:00`
- Inventory generated: `2026-02-13T19:28:25.195851+00:00`
- Scanned files: `1387`
- Miss rows: `0`
- Gate failures: `0`

## Canonical Full List
- Full row-by-row list: `docs/reports/full_repo_miss_inventory_2026-02-12.md`
- Raw machine-readable list: `artifacts/repo_miss_inventory/latest.json`

## Category Counts
| Category | Count |
| --- | ---: |

## Source Bucket Counts
| Bucket | Count |
| --- | ---: |

## Gate Failures
- None

## Source Files With Misses (Full List)
| SourceClass | Source | Total | Categories |
| --- | --- | ---: | --- |

## Actionable Implementation Sources
| SourceClass | Source | Rows |
| --- | --- | ---: |

## Non-Actionable Generated Sources
| SourceClass | Source | Rows |
| --- | --- | ---: |

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
| `A-CORE-01` | 56 | Frame → UI IR extraction pipeline (OmniParser adapter) | 4 | docs/reports/four_pillars_traceability_map.md:16:  - Superseded by: `A-CORE-01`, `A-GROUND-01`; docs/reports/four_pillars_traceability_map.md:22:  - Superseded by: `A-CORE-01`, `A-GROUND-01`; docs/reports/four_pillars_traceability_map.md:29:  - Superseded by: `A-CORE-01` |
| `A-GROUND-01` | 66 | Grounding stage with verifier (GUI-Actor style contract) | 5 | optimal-implementation-order-plan.md:167:### Task 4.2: Implement A-GROUND-01 on top of IR (not before); docs/reports/four_pillars_traceability_map.md:16:  - Superseded by: `A-CORE-01`, `A-GROUND-01`; docs/reports/four_pillars_traceability_map.md:22:  - Superseded by: `A-CORE-01`, `A-GROUND-01` |
| `A-RAG-01` | 75 | Multimodal RAG evaluation harness (RAG-Check / RAGAs style) | 5 | docs/reports/four_pillars_traceability_map.md:47:  - Superseded by: `A-RAG-01`; docs/reports/four_pillars_traceability_map.md:53:  - Superseded by: `A-RAG-01`; docs/reports/four_pillars_traceability_map.md:59:  - Superseded by: `A-RAG-01` |
| `A-INDEX-01` | 83 | Retrieval backend abstraction (dense + ColBERT optional) | 2 | optimal-implementation-order-plan.md:177:### Task 4.3: Implement A-INDEX-01 retrieval abstraction before A-RAG-01; docs/reports/four_pillars_traceability_map.md:65:  - Superseded by: `A-INDEX-01` |
| `A-PERF-01` | 91 | Background batch scheduler w/ budgets | 3 | docs/reports/four_pillars_traceability_map.md:72:  - Superseded by: `A-PERF-01`; optimal-implementation-order-plan.md:39:  - Resolution rule: no A-PERF-01 work before A-CORE/A-GROUND/A-INDEX/A-RAG contracts and tests are green.; optimal-implementation-order-plan.md:197:### Task 4.5: Implement A-PERF-01 scheduling/budget enforcement last |

## Regenerated Misses (Actionable Clusters)
| Cluster ID | Scope | Evidence | Required Closure |
| --- | --- | --- | --- |
| MX-000 | None | no actionable clusters detected | No remaining actionable misses from current inventory. |

## Notes
- This file is generated from inventory data and is intentionally exhaustive; use the actionable clusters above to prioritize implementation sequencing.
- Any regressions from this matrix should be treated as `DO_NOT_SHIP` until resolved or explicitly deferred.

