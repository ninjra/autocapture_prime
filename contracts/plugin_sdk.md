# Plugin SDK (Pinned Contract)

## Overview
Autocapture NX is plugin-forward. The kernel only loads config, enforces policy, and composes capabilities.
All functional behavior is provided by plugins.

## Manifest schema
Each plugin ships a `plugin.json` with fields:
- `plugin_id` (string)
- `version` (string)
- `enabled` (bool)
- `entrypoints[]`: `{ kind, id, path, callable }`
- `permissions`: `{ filesystem, gpu, raw_input, network }`
- `required_capabilities[]` (capability strings)
- `filesystem_policy` (optional): `{ read[], readwrite[] }`
- `settings_paths` (optional): list of dot-paths into the effective config to expose as plugin settings
- `settings_schema` (optional): JSON schema describing plugin-specific settings UI
- `default_settings` (optional): default settings merged before config slices and user overrides
- `compat`: `{ requires_kernel, requires_schema_versions[] }`
- `depends_on[]` (plugin_id strings)
- `hash_lock`: `{ manifest_sha256, artifact_sha256 }`

## Entry points
Each entrypoint uses a relative `path` to a Python file and a `callable` factory.
The factory signature is:
```
create_plugin(plugin_id: str, context: PluginContext) -> Plugin
```

## Plugin interface
A plugin must provide:
- `capabilities() -> dict[str, Any]`
- optional `close()`

## Capability model
Capabilities are namespaced strings (examples):
- `egress.gateway`
- `privacy.egress_sanitizer`
- `storage.metadata`
- `storage.media`
- `storage.entity_map`
- `storage.keyring`
- `capture.source`
- `capture.audio`
- `tracking.input`
- `window.metadata`
- `retrieval.strategy`
- `time.intent_parser`
- `journal.writer`
- `ledger.writer`
- `anchor.writer`
- `runtime.governor`
- `capture.backpressure`
- `answer.builder`
- `citation.validator`
- `observability.logger`
- `devtools.diffusion`
- `devtools.ast_ir`
- `meta.configurator`
- `meta.policy`

## Permissions
- Network is denied by default.
- Only `builtin.egress.gateway` may request `network: true`.
- Filesystem/gpu/raw_input are declared and enforced by policy + host sandbox.
- `filesystem_policy` supports templated roots: `{data_dir}`, `{cache_dir}`, `{config_dir}`, `{plugin_dir}`, `{repo_root}`.

## Safe mode
If `plugins.safe_mode` is true, only `plugins.default_pack` may load.
Any user overrides are ignored.

## Hosting
`plugins.hosting.mode` controls default hosting (`subprocess` or `inproc`).
`plugins.hosting.inproc_allowlist` enumerates audited in-proc plugins.

## Plugin settings
Plugins receive a settings subtree derived from:
1) `default_settings` from the manifest
2) config slices listed in `settings_paths`
3) user overrides under `plugins.settings.<plugin_id>`

Only the derived settings subtree is passed to plugins as `context.config`.

## Hash locking
`config/plugin_locks.json` is the authoritative lockfile.
A manifest or artifact hash mismatch fails closed.

## Meta-plugins
- `meta.configurator` may propose config changes when explicitly allowed by `plugins.meta.configurator_allowed`.
- `meta.policy` may propose permission changes when explicitly allowed by `plugins.meta.policy_allowed`.
