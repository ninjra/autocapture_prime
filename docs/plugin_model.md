# Plugin Model

## Summary
Autocapture NX is plugin-forward: all functionality is delivered by plugins. The kernel only:
- loads config (defaults + user overrides)
- enforces allowlist + permissions
- composes capabilities into a running system

## Plugins
Plugins live under `plugins/` and declare a manifest `plugin.json` (see `contracts/plugin_sdk.md`).
Plugins are loaded only if:
- their `plugin_id` is in `plugins.allowlist`
- they are enabled (explicitly or via manifest)
- their hashes match `config/plugin_locks.json`

Default pack includes encrypted storage and egress sanitization plugins.

## Capabilities
Plugins expose capabilities (string keys). The kernel composes the system by capability name.

## Allowlist and locks
- Allowlist is enforced by config.
- Lockfile hashes are enforced by default (fail closed).

## Safe mode
When `plugins.safe_mode` is true, only the `plugins.default_pack` list loads.
