# Configuration

## Format
- JSON (`config/default.json` + optional `config/user.json`).
- Effective config = defaults merged with user overrides.

## Schema
- `contracts/config_schema.json` is authoritative.
- Validation is enforced at boot.

## Reset/restore
- `autocapture config reset` backs up `config/user.json` to `config/backup/user.json` and restores defaults.
- `autocapture config restore` restores the backup.

## Plugins
- `plugins.allowlist` controls which plugins can load.
- `plugins.enabled` toggles plugins without code changes.
- `plugins.locks` enforces `config/plugin_locks.json`.
- `plugins.hosting` controls in-proc vs subprocess hosting.

## Network
- `privacy.cloud.enabled` controls any outbound usage.
- `privacy.egress.*` controls sanitization behavior.

## Encryption
- `storage.encryption_required` enforces encrypted-at-rest stores.
- `storage.crypto.root_key_path` points to the legacy root key (migration source).
- `storage.crypto.keyring_path` points to the DPAPI-protected keyring file.
- `storage.anchor.path` controls the anchor store location (defaults to `data_anchor/`).
- `storage.anchor.use_dpapi` toggles DPAPI protection for anchor entries on Windows.
