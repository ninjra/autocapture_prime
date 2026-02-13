# Dev Harness

## Purpose
Provide a repo-agnostic, single-command developer harness for local use and CI.

## Principles
- Fail closed: do **not** guess commands. If a command cannot be inferred from repo evidence, the harness must stop with a clear action item.
- Additive only: existing scripts and workflows remain intact.
- Idempotent lifecycle: `dev up` and `dev down` are safe to run repeatedly.
- Stable state: logs, PIDs, and state live under `.dev/`.
- CI parity: when CI exists, prefer running the same `dev test` plan.
- No network, no sudo, no global installs.

## Repo evidence
- Stack: Python (`pyproject.toml`).
- Tests (Linux/WSL): `python3 tools/run_all_tests.py` (`README.md`).
- Tests (Windows): `tools/run_all_tests.ps1` (`README.md`).
- No UI folder or `package.json` detected.
- No CI workflows detected.

## Verb contract
All verbs are available in `dev.sh` (POSIX/WSL) and `dev.ps1` (Windows):

- `doctor`: validate repo assumptions, required tools, and port availability.
- `up`: start backend service (requires explicit command).
- `down`: stop backend service; safe if nothing is running.
- `logs [service]`: print logs for a service (default: backend).
- `test`: run the repo's test plan (here: `tools/run_all_tests.py`).
- `fmt`: optional; fails closed if formatter is unknown.
- `reset`: stop services and clear `.dev/` state.
- `ui`: optional UI launch; fails closed if UI command is unknown.

## Configuration files
Optional local config (ignored by git):
- `ops/dev/common.env`
- `ops/dev/ports.env`

Examples:
- `ops/dev/common.env.example`
- `ops/dev/ports.env.example`

### Supported keys (repo-agnostic)
- `DEV_BACKEND_CMD`: shell command to start the backend service.
- `DEV_BACKEND_PORT`: TCP port used by the backend.
- `DEV_BACKEND_HEALTH_URL`: optional health URL (HTTP GET).
- `DEV_UI_CMD`: shell command to start UI.
- `DEV_UI_PORT`: TCP port used by the UI.
- `DEV_UI_BACKEND_URL`: optional UI-to-backend base URL (if supported by the UI).

If any required command is missing, the harness exits non-zero with a clear action item.

## .dev layout
`.dev/` is harness-local state and is ignored by git:
- `.dev/logs/`: per-service logs
- `.dev/pids/`: per-service PID files
- `.dev/state/`: small state markers
- `.dev/cache/`: scratch cache

## Health and readiness
- If `DEV_BACKEND_HEALTH_URL` is set, `dev up` will poll it.
- Otherwise readiness is "process alive + port open" (if a port is configured).
- No health endpoints are added by the harness.

## Optional Windows UI split
Default behavior (Windows):
- Backend verbs run in WSL by delegating to `./dev.sh`.
- UI (`dev ui`) runs on Windows (if detected).

Override:
- Set `DEV_USE_WSL=0` to force local execution where possible.

## Done criteria
- `dev.sh` and `dev.ps1` implement all verbs.
- `.dev/` state is created and ignored.
- Existing scripts remain usable.
- CI is not modified unless equivalence can be proven.
