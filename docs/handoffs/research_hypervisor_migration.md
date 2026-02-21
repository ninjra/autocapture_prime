# Research Migration: autocapture_prime -> hypervisor

## Scope
Move the research/watchlist subsystem out of `autocapture_prime` and make `hypervisor` the sole owner.

## Extracted components
- `autocapture/research/cache.py`
- `autocapture/research/diff.py`
- `autocapture/research/scout.py`
- `autocapture/research/runner.py`
- `plugins/builtin/research_default/plugin.py`
- `plugins/builtin/research_default/plugin.json`

## Runtime behavior to preserve
- Research runs in idle windows, not foreground.
- Inputs:
  - `research.sources`
  - `research.watchlist.tags`
  - `research.threshold_pct`
- Outputs:
  - cache under `data/research/cache`
  - reports under `data/research/reports`
- Report contract:
  - `ok`
  - `reports[]` with `source_id`, `items`, `diff`, `cache_hit`, `report_hash`
  - `ran_at`

## Hypervisor integration targets
1. Add a `ResearchRunner` service under Hypervisor scheduler/orchestrator.
2. Bind research cadence to idle policy gate.
3. Persist reports to Hypervisor-owned data root.
4. Expose health/metrics counters:
   - runs_total
   - last_run_utc
   - changed_items_total
   - cache_hit_ratio
5. Keep this path local-only (no remote fetch by default).

## Autocapture_prime status
- `research` is deprecated in `autocapture_prime` runtime path:
  - disabled in `config/default.json`
  - plugin default enabled flag set false
  - `autocapture_nx research run` returns `deprecated_moved_to_hypervisor`

## Acceptance checks in hypervisor
- Research job appears in scheduler and runs only when idle.
- Report files are emitted and stable schema is preserved.
- Watchlist filtering + diff threshold behavior matches extracted implementation.
