# 4Pillars Traceability Map

Purpose: provide deterministic closure mapping for `docs/AutocapturePrime_4Pillars_Upgrade_Plan.md` source items (`A1..A10`) to concrete NX implementation paths and tests.

Scope rules:
- This map is traceability-only and does not change the authoritative source document.
- When an item is superseded by the NX blueprint path, this file records the supersedence explicitly.
- Every row must include executable evidence (`tests/**`, `tools/gate_*`, or implementation module paths).

## Source Item Mapping

- A1) mapped to UI grounding benchmark parity via retrieval/grounding validation harness:
  - `tests/test_query_golden.py`
  - `tests/test_retrieval_golden.py`
  - `tools/query_eval_suite.py`
  - Superseded by: `A-CORE-01`, `A-GROUND-01`

- A2) mapped to decomposition + candidate region extraction path:
  - `plugins/builtin/processing_sst_vlm_ui/plugin.py`
  - `autocapture_nx/processing/sst/stage_plugins.py`
  - `tests/test_sst_stage_plugins_ui_parse_vlm.py`
  - Superseded by: `A-CORE-01`, `A-GROUND-01`

- A3) mapped to structured UI IR extraction contract:
  - `plugins/builtin/processing_sst_vlm_ui/plugin.py`
  - `autocapture_nx/processing/sst/pipeline.py`
  - `tests/test_sst_pipeline_merge_semantics.py`
  - `tests/test_sst_vlm_ui_hook.py`
  - Superseded by: `A-CORE-01`

- A4) mapped to verifier-style grounded answer construction:
  - `plugins/builtin/observation_graph/plugin.py`
  - `tests/test_observation_graph_vlm_grounding.py`
  - `tests/test_query_source_class_guards.py`
  - Superseded by: `A-GROUND-01`

- A5) mapped to object/region extraction for fine-grained visual entities:
  - `plugins/builtin/sst_nemotron_objects/plugin.py`
  - `tests/test_sst_nemotron_objects_plugin.py`
  - Superseded by: `A-GROUND-01`

- A6) mapped to instruction-variant query evaluation coverage:
  - `docs/query_eval_cases_advanced20.json`
  - `docs/query_eval_cases_hard10.json`
  - `tools/run_advanced10_queries.py`
  - `tests/test_query_eval_suite_exact.py`
  - Superseded by: `A-RAG-01`

- A7) mapped to retrieval-vs-answer separation metrics:
  - `tools/query_eval_suite.py`
  - `tools/query_effectiveness_report.py`
  - `tests/test_query_effectiveness_report.py`
  - Superseded by: `A-RAG-01`

- A8) mapped to deterministic RAG-style regression harness:
  - `tests/test_query_golden.py`
  - `tests/test_retrieval_golden.py`
  - `tools/gate_pillars.py`
  - Superseded by: `A-RAG-01`

- A9) mapped to late-interaction retrieval pathway:
  - `autocapture_nx/indexing/colbert.py`
  - `tests/test_state_vector_hnsw.py`
  - `tests/test_retrieval_indexed_hits.py`
  - Superseded by: `A-INDEX-01`

- A10) mapped to localhost vLLM integration and throughput-safe routing:
  - `plugins/builtin/vlm_vllm_localhost/plugin.py`
  - `tests/test_vlm_vllm_localhost_plugin.py`
  - `autocapture/runtime/scheduler.py`
  - `autocapture/runtime/wsl2_queue.py`
  - Superseded by: `A-PERF-01`

## Determinism
- All mappings use repo-local evidence only.
- Any unmapped `A*` item is a `DO_NOT_SHIP` condition until this file is updated with executable evidence.
