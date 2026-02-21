# Implementation Authority Map

## Purpose
Prevent overwrite/rework by defining which files are authoritative for implementation decisions versus generated/historical artifacts.

## Authority Classes

| Class | Description | Implementation Authority | Examples |
| --- | --- | --- | --- |
| `authoritative_doc` | Normative requirements/specifications that drive implementation scope and acceptance. | High | `docs/blueprints/autocapture_nx_blueprint.md`, `docs/spec/autocapture_nx_blueprint_2026-01-24.md`, `docs/spec/feature_completeness_spec.md`, `AGENTS.md` |
| `code_or_tooling` | Executable source of truth (kernel/plugins/tests/gates/scripts). | High | `autocapture_nx/**`, `plugins/**`, `tests/**`, `tools/**` |
| `other_doc` | Supporting docs/plans/runbooks that may guide but cannot close acceptance by themselves. | Medium | `docs/roadmap.md`, `docs/runbook.md`, `docs/plans/**` |
| `derived_report` | Generated analysis/report outputs; informative snapshots only. | Low (do not hand-edit for closure) | `docs/reports/*gap*.md`, `docs/reports/*grep*.txt`, `docs/reports/adversarial-redesign-gap-*.md` |
| `generated_artifact` | Machine-generated artifacts/logs/outputs. | Low (no direct closure authority) | `artifacts/**`, generated JSON/NDJSON reports |

## Closure Rules

1. Requirement closure must be backed by executable evidence:
   - tests (`tests/**`) and/or gate scripts (`tools/gate_*.py`, `tools/run_*`).
2. Documentation-only evidence is insufficient for closure:
   - docs may describe status, but cannot be the sole validator.
3. Generated reports cannot be edited to claim completion:
   - they must be regenerated from tools after code/test changes.
4. If authoritative docs and executable behavior conflict:
   - executable behavior must be fixed, then docs updated to match reality.

## Supersedence Rules

1. Never implement from historical snapshots when a newer authoritative spec exists.
2. Never tune performance paths before correctness gates are green.
3. Never implement downstream features against unstable contracts:
   - establish IR/retrieval/schema contracts first, then dependent plugins/evals.

## Workflow

1. Implement in `code_or_tooling`.
2. Prove with tests/gates.
3. Regenerate inventory/matrix artifacts:
   - `tools/run_full_repo_miss_refresh.sh`
4. Update supporting docs if needed.

## Do-Not-Implement-Directly List

- `docs/reports/*gap*.md`
- `docs/reports/*grep*.txt`
- `docs/reports/adversarial-redesign-gap-*.md`
- `docs/reports/full_repo_miss_inventory_*.md`
- `artifacts/**`

These are outputs of tooling; modify generators/executable logic instead.
