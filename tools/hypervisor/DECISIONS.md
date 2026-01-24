# Decisions

## 2026-01-24: Python baseline
- Decision: Use Python 3.10+ for kernel + plugins.
- Rationale: fast scaffolding, stdlib AST support, minimal deps.
- Alternatives: TS/Node, Go, Rust.
- Rollback: re-implement kernel and plugin SDK in selected runtime.

## 2026-01-24: JSON config + schema-lite validator
- Decision: JSON config with strict schema and a minimal validator.
- Rationale: deterministic parsing and easy hashing for contracts.
- Alternatives: YAML (more ergonomic), TOML (mid-ground).
- Rollback: swap config loader and schema validator; update contracts.

## 2026-01-24: Allowlist + lockfile enforcement
- Decision: enforce plugin allowlist and hash lockfile by default.
- Rationale: fail-closed and deterministic plugin loading.
- Alternatives: trust-based loading without hashes.
- Rollback: disable `plugins.locks.enforce` (not recommended).

## 2026-01-24: AES-GCM encrypted storage baseline
- Decision: implement AES-GCM encrypted metadata/media stores using a local root key.
- Rationale: meet encrypted-at-rest invariant with stdlib-compatible dependency.
- Alternatives: SQLCipher or OS-native vault-backed stores.
- Rollback: switch storage plugin and update config + locks.

## 2026-01-24: Keyring + rotation workflow
- Decision: store root keys in a DPAPI-protected keyring file and rotate via `autocapture keys rotate`.
- Rationale: satisfies key hierarchy + rotation invariants with auditable ledger entries.
- Alternatives: OS credential manager, hardware-backed vault.
- Rollback: revert to single root key file and disable rotation command.

## 2026-01-24: Reasoning packet schema v1
- Decision: enforce `reasoning_packet_v1` schema with sanitized query + facts + glossary.
- Rationale: deterministic egress payloads and leak-prevention gating.
- Alternatives: free-form payloads or model-specific schemas.
- Rollback: relax schema validation in egress gateway (not recommended).

## 2026-01-24: Anchor store separation
- Decision: default anchor store to `data_anchor/` with optional DPAPI protection.
- Rationale: separate trust domain for tamper-evident anchoring.
- Alternatives: registry/credential manager anchors.
- Rollback: place anchors under `storage.data_dir` (not recommended).
