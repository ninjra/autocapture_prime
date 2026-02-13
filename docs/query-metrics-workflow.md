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
- Per-workflow-sequence accuracy and latency.
- Recommendation rows (for example: missing feedback, low-accuracy/high-latency providers).

## 4) Export Workflow Tree Diagram

```bash
/mnt/d/projects/autocapture_prime/.venv/bin/python /mnt/d/projects/autocapture_prime/tools/export_run_workflow_tree.py --input /mnt/d/projects/autocapture_prime/artifacts/single_image_runs/single_20260211T182049Z/report.json --out /mnt/d/projects/autocapture_prime/artifacts/single_image_runs/single_20260211T182049Z/workflow_tree.md
```

Tree output includes:
- Node/edge graph for the query pipeline.
- Provider contribution table.
- Mermaid diagram block for visual inspection.
