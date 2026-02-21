# autocapture_prime — Running Under `hypervisor`

## Purpose in the harness
`autocapture_prime` is executed as a **child job** under `hypervisor`. Its responsibilities should be:
- capture / ingest artifacts (exact modalities are project-specific)
- write deterministic outputs into a run directory owned by `hypervisor`
- avoid global mutable state that would collide across concurrent runs

## External vLLM ownership (required)
- `autocapture_prime` no longer launches or manages vLLM.
- vLLM must be provided by sidecar/hypervisor at `http://127.0.0.1:8000`.
- If `/health` or `/v1/models` is unavailable, `autocapture_prime` must fail closed with actionable diagnostics.
- Local vLLM launch/install scripts in this repo are deprecated.

## Contract with hypervisor (required surface)
`autocapture_prime` should support either CLI flags or environment variables that allow `hypervisor` to control:

| Category | Requirement | Why it matters for concurrent orchestration |
|---|---|---|
| Run identity | `--run-id` or `AP_RUN_ID` | prevents collisions across runs |
| Output root | `--out` or `AP_OUT_DIR` | isolates per-run outputs |
| Data root | `--data-root` or `AP_DATA_ROOT` | standardizes shared storage |
| Offline mode | `--no-network` or `AP_NO_NETWORK=1` | reproducibility and containment |
| Resource caps | `AP_CPU_LIMIT`, `AP_MEM_LIMIT_MB` | prevents contention and runaway usage |
| Logging | `--log-json` / `AP_LOG_JSON=1` | structured logs for the harness |
| Health/ready | `--ready-file` | enables hypervisor to detect readiness |

### Recommended minimal CLI (current repo)
```bash
python3 tools/run_fixture_pipeline.py --manifest "$HYPERVISOR_MANIFEST" --out "$HYPERVISOR_RUN_DIR/autocapture_prime" --run-id "$AP_RUN_ID" --data-root "$AP_DATA_ROOT" --no-network --ready-file "$HYPERVISOR_RUN_DIR/autocapture_prime/ready.json" --log-json --config-template tools/fixture_config_template.json --force-idle
```

## Directory & file conventions
Hypervisor will allocate:
- `RUN_DIR/autocapture_prime/` (write outputs here)
- `RUN_DIR/tmp/autocapture_prime/` (temp space; should be safe to delete)

**Do not write** to:
- a global `/tmp` without namespacing
- shared caches without a run-id suffix
- the repo working tree (unless explicitly permitted)

## Concurrency readiness requirements

### 1) File and cache isolation
- Any cache must include `run-id` in its key or directory path.
- All temp files must be under `${RUN_DIR}/tmp/autocapture_prime`.

### 2) Device contention (if capture devices exist)
If autocapture uses:
- webcams
- microphones
- screen capture
- OS-level event hooks

then it must support one of:
- **exclusive device mode** (only one AP job allowed) — hypervisor schedules AP as exclusive
- **explicit lock file** provided by hypervisor — AP respects it

**Lock path example:**
`$HYPERVISOR_RUN_DIR/shared/locks/screen_capture.lock`

### 3) Network denial compliance
If `AP_NO_NETWORK=1`:
- AP should refuse outbound HTTP calls
- any plugin needing network should be disabled or fail fast with a clear error

## Resource behavior under hypervisor budgets
AP must treat the budgets as hard operational constraints:
- cap thread pools (don’t spawn threads equal to host CPU if allocated 2 cores)
- cap in-memory buffering (stream to disk when possible)
- avoid loading entire corpora into memory

## Plugin policy
If AP supports plugins:
- hypervisor should provide a plugin allowlist / lockfile path
- AP should refuse unpinned plugins for harness runs

Example env vars:
- `AP_PLUGIN_LOCK=/path/to/plugins.lock`
- `AP_PLUGINS_ALLOWLIST=/path/to/allowlist.txt`

## Outputs expected by downstream stats
AP should write a stable output manifest at:
- `$AP_OUT_DIR/manifest.json` (recommended)

Include:
- artifact list with relative paths
- capture timestamps
- schema/version
- content hashes (optional)

## Harness tests (should live in autocapture_prime)
1. **Smoke run** under a tiny budget (e.g., 1 CPU / 512MB) that still completes.
2. **Offline mode test**: ensure `AP_NO_NETWORK=1` prevents any egress.
3. **Concurrency test**: two AP runs with different `run-id` in parallel do not collide on outputs.

## Resolved contract values
- Entrypoint used in this repo for harness runs: `python3 tools/run_fixture_pipeline.py`.
- Capture devices for this repo path: sidecar/hypervisor owns capture; this repo consumes persisted artifacts and performs processing/query.
- Statistics-harness-facing output artifact: `artifacts/fixture_runs/<run>/fixture_report.json` produced by fixture pipeline execution.
