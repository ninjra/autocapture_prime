# Security Contract (Pinned)

## Fail-closed defaults
- Network access is denied by default.
- Only `builtin.egress.gateway` may request network permission.
- Plugins must be allowlisted; unlisted plugins do not load.
- Plugin hashes must match `config/plugin_locks.json`.
- `storage.encryption_required` enforces encryption-at-rest.
- `plugins.hosting.mode` defaults to subprocess with an explicit in-proc allowlist.

## Egress sanitization
- All outbound payloads must pass `privacy.egress_sanitizer` unless `privacy.egress.allow_raw_egress` is true.
- Sanitized payloads use typed tokens `⟦ENT:<TYPE>:<TOKEN>⟧` and a glossary.
- Egress is blocked if leak checks fail.

## Safe mode
- When `plugins.safe_mode` is true, only `plugins.default_pack` loads.
- User overrides are ignored in safe mode.

## Auditability
- Journal and ledger writers are append-only.
- Ledger entries are hash-chained with canonical JSON.
- Anchor writer records ledger head hashes in a separate anchor store.

## Key hierarchy
- Root keys live in `storage.crypto.keyring_path` (DPAPI-protected on Windows).
- Derived keys are separated for metadata, media, and entity tokens.
- `autocapture keys rotate` records a ledger entry and rewraps stores.
