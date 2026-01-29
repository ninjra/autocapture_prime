# User Surface (Pinned Contract)

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
  - Starts capture, audio, input, and window metadata pipelines.
- `autocapture query "<text>"`
  - Runs deterministic time parsing, retrieval, optional on-demand extraction, and claim-level citations.
- `autocapture devtools diffusion --axis <name> [-k N] [--dry-run]`
  - Runs the diffusion harness and writes artifacts under `tools/hypervisor/runs/<run_id>/`.
- `autocapture devtools ast-ir [--scan-root <path>]`
  - Runs AST/IR analysis and writes artifacts under `tools/hypervisor/runs/<run_id>/`.
- `autocapture keys rotate`
  - Rotates root keys, rewraps storage, and writes a ledger + anchor entry.

## Exit codes
- 0: success
- 1: configuration or runtime error
- 2: invariant check failure
