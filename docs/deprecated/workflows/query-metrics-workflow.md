# Query Metrics Workflow

This workflow runs natural-language queries against the latest processed single-image run, stores per-query trace metrics, captures reviewer feedback, and generates chartable plugin effectiveness reports.

## 1) Ask A Query (Single Short Command)

```bash
/mnt/d/projects/autocapture_prime/tools/query_latest_single.sh "how many inboxes do i have open"
```

Output includes:
- `answer`: one-line answer summary.
- `breakdown`: short supporting bullets.
- `query_run_id`: stable id for feedback and metrics joins.
- `artifact`: saved query session JSON under `artifacts/query_sessions/`.

Append-only records written:
- `DataRoot/facts/query_eval.ndjson` (`derived.query.eval`)
- `DataRoot/facts/query_trace.ndjson` (`derived.query.trace`)

## 2) Capture Reviewer Feedback

You can run interactive mode (default in TTY), or pass verdict flags inline:

```bash
/mnt/d/projects/autocapture_prime/tools/query_latest_single.sh "what song is playing" --interactive off --verdict agree --notes "verified"
```

Feedback record written:
- `DataRoot/facts/query_feedback.ndjson` (`derived.eval.feedback`)

Key feedback fields:
- `query_run_id`
- `verdict` (`agree`/`disagree`/`partial`)
- `score_bp`
- `expected_answer`, `actual_answer`
- `plugin_fix_summary`, `plugin_ids`, `plugin_fix_files`

## 3) Generate Effectiveness Metrics

```bash
/mnt/d/projects/autocapture_prime/.venv/bin/python /mnt/d/projects/autocapture_prime/tools/query_effectiveness_report.py --data-dir /mnt/d/projects/autocapture_prime/artifacts/single_image_runs/single_20260211T182049Z/data --out-dir /mnt/d/projects/autocapture_prime/artifacts/query_metrics/latest
```

Outputs:
- `report.json`
- `runs.csv`
- `providers.csv`
- `sequences.csv`

Metrics include:
- Per-run latency + handoff counts + provider path.
- Per-provider accuracy from reviewer feedback.
- Per-provider `helped`/`hurt`/`neutral` counts and confidence delta.
- Per-workflow-sequence accuracy and latency.
- Recommendation rows (for example: missing feedback, low-accuracy/high-latency providers).

## 4) Generate Q/H Plugin Validation Trace

```bash
/mnt/d/projects/autocapture_prime/.venv/bin/python /mnt/d/projects/autocapture_prime/tools/generate_qh_plugin_validation_report.py
```

Outputs:
- `docs/reports/question-validation-plugin-trace-2026-02-13.md`
- `artifacts/advanced10/question_validation_plugin_trace_latest.json`

Includes:
- Full plugin inventory (`loaded/failed/skipped`) vs in-path/out-of-path.
- Strict pass/fail contribution counts per plugin.
- Confidence deltas and decision classification (`keep`/`tune`/`fix_required`/`remove_or_rewire`).

## 5) Export Workflow Tree Diagram

```bash
/mnt/d/projects/autocapture_prime/.venv/bin/python /mnt/d/projects/autocapture_prime/tools/export_run_workflow_tree.py --input /mnt/d/projects/autocapture_prime/artifacts/single_image_runs/single_20260211T182049Z/report.json --out /mnt/d/projects/autocapture_prime/artifacts/single_image_runs/single_20260211T182049Z/workflow_tree.md
```

Tree output includes:
- Node/edge graph for the query pipeline.
- Provider contribution table.
- Mermaid diagram block for visual inspection.

Advanced eval bundle mode (per-answer trees):

```bash
/mnt/d/projects/autocapture_prime/.venv/bin/python /mnt/d/projects/autocapture_prime/tools/export_run_workflow_tree.py --input /mnt/d/projects/autocapture_prime/artifacts/advanced10/advanced10_20260213T215430Z.json --out /mnt/d/projects/autocapture_prime/artifacts/advanced10/workflow_trees_latest
```

Bundle output includes:
- `index.md`
- `workflow_tree_<QID>.md` for each Q/H case

## 6) Fail-Closed Golden Eval Gate

```bash
/mnt/d/projects/autocapture_prime/.venv/bin/python /mnt/d/projects/autocapture_prime/tools/gate_advanced_eval.py --artifact /mnt/d/projects/autocapture_prime/artifacts/advanced10/advanced10_20260213T215430Z.json --require-total 20 --require-evaluated 20 --max-failed 0
```

Exit codes:
- `0`: gate passed
- `1`: gate failed (do not ship)

## 7) Embedder Endpoint Readiness

```bash
/mnt/d/projects/autocapture_prime/.venv/bin/python /mnt/d/projects/autocapture_prime/tools/check_embedder_endpoint.py --config /mnt/d/projects/autocapture_prime/artifacts/single_image_runs/single_20260213T232507Z/config/user.json --require-live
```

Checks:
- `GET /health`
- `GET /v1/models`
- `POST /v1/embeddings`

Expected:
- `ok=true`
- `checks.embeddings.embedding_dim > 0`

## 8) Degraded Eval Mode (When vLLM Is Down)

```bash
/mnt/d/projects/autocapture_prime/.venv/bin/python /mnt/d/projects/autocapture_prime/tools/run_advanced10_queries.py --report /mnt/d/projects/autocapture_prime/artifacts/single_image_runs/single_20260213T232507Z/report.json --cases /mnt/d/projects/autocapture_prime/docs/query_eval_cases_advanced20.json --allow-vllm-unavailable --output /mnt/d/projects/autocapture_prime/artifacts/advanced10/advanced20_degraded_latest.json
```

Notes:
- This mode is for pipeline/metrics validation only.
- Final Q/H quality closure still requires live vLLM.

## 9) One-Command Golden Cycle

```bash
/mnt/d/projects/autocapture_prime/tools/run_golden_qh_cycle.sh
```

Behavior:
- Preflights `127.0.0.1:8000` (`/v1/models`).
- Runs single-image golden processing.
- Runs strict advanced20 evaluation.
- Regenerates plugin validation trace.
- Emits one JSON summary with report paths and pass/fail counts.
