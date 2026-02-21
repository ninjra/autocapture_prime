# User Surface (Pinned Contract)

**Core runtime**: `autocapture_nx` (the `autocapture` CLI is the pinned user-facing entrypoint that bootstraps NX).

## CLI
The baseline user-visible interface is the `autocapture` CLI.

Commands:
- `autocapture doctor`
  - Runs invariant checks and exits non-zero on failure.
- `autocapture config show`
  - Prints effective config (defaults merged with user overrides).
- `autocapture config reset`
  - Resets user config to defaults and backs up the prior file.
- `autocapture config restore`
  - Restores the last backed-up user config.
- `autocapture plugins list`
  - Lists discovered plugins with allowlist and enabled status.
- `autocapture plugins approve`
  - Updates `config/plugin_locks.json` hashes from current plugin artifacts.
- `autocapture tray`
  - Starts the native Windows tray host and local settings/plugin manager UI.
- `autocapture run`
  - Deprecated in this repo: live capture is expected to run in a Windows sidecar repo.
  - When enabled explicitly, starts capture/audio/input/window pipelines (Windows-only).
- `autocapture backup create --out <path> [--include-data] [--keys]`
  - Creates a portable backup bundle zip for sidecar -> processor handoff.
- `autocapture backup restore --bundle <path> [--restore-keys]`
  - Restores a backup bundle zip (archives conflicts; no deletion).
- `autocapture query "<text>"`
  - Runs deterministic time parsing, retrieval, optional on-demand extraction, and claim-level citations.
- `autocapture devtools diffusion --axis <name> [-k N] [--dry-run]`
  - Delegates diffusion execution to Hypervisor API (`/v1/autocapture/devtools/diffusion`).
  - In dry-run mode, writes deterministic local stub artifacts under `artifacts/devtools/diffusion_runs/<run_id>/`.
- `autocapture devtools ast-ir [--scan-root <path>]`
  - Runs AST/IR analysis and writes artifacts under `<data_dir>/runs/<run_id>/devtools_ast_ir/`.
- `autocapture keys rotate`
  - Rotates root keys, rewraps storage, and writes a ledger + anchor entry.
- `autocapture keys export --out <path> [--passphrase <pass>] [--data-dir <dir>] [--config-dir <dir>]`
  - Exports an encrypted keyring bundle for backup/transfer between machines.
- `autocapture keys import --bundle <path> [--passphrase <pass>] [--data-dir <dir>] [--config-dir <dir>]`
  - Imports an encrypted keyring bundle into the local keyring.

## Exit codes
- 0: success
- 1: configuration or runtime error
- 2: invariant check failure
