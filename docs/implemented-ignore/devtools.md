# Devtools

## Diffusion harness
The diffusion harness produces iterative variants and records artifacts.
- Command: `autocapture devtools diffusion --axis <name> -k N`
- Artifacts: `tools/hypervisor/runs/<run_id>/run.json` and scorecards

The default is `dry_run=true` to avoid modifying the repo.

Noise schedule is recorded in `run.json` with scoped edit stages.

## AST/IR guided mode
The AST/IR tool:
- Parses Python code using `ast` (no external deps)
- Builds a design IR from config + plugin declarations
- Diffs against pinned IR in `contracts/ir_pins.json`

Artifacts are stored under `tools/hypervisor/runs/<run_id>/ast_ir.json`.
