# STATE

Date: 2026-01-24

## Repository inventory
- Files: README.md, pyproject.toml, config/default.json, config/plugin_locks.json, contracts/*, docs/*
- Directories: .git, autocapture_nx/, plugins/, tools/, tests/, config/, contracts/, docs/
- Detected stack: Python 3.10+ (stdlib-only)
- Crypto dependency: cryptography (AES-GCM) + optional SQLCipher (pysqlcipher3)
- Entrypoints: `autocapture` CLI (via `autocapture_nx.cli`)
- Tests: `python -m unittest discover -s tests -q`
- Configs: `config/default.json` (+ optional `config/user.json`)
- Requirements source: docs/autocapture_nx_blueprint_final.md

## Current behavior surface
- CLI commands defined in `contracts/user_surface.md` (includes `autocapture keys rotate`)

## Blueprint-derived constraints (implementation status)
- Plugin-forward kernel + plugins; safe mode; allowlisted plugins; network denied by default except egress gateway. (implemented baseline)
- Windows 11 capture/audio/input/window metadata plugins implemented, but not validated in this environment. (Windows tests pending)
- SQLCipher metadata store and DPAPI key protection require Windows validation.
- Keyring + rotation implemented via `autocapture keys rotate` with ledger + anchor entries.
- Anchor store defaults to `data_anchor/` path to separate from `storage.data_dir`.
- Default config format now JSON for determinism and contract hashing.
- Contract surfaces pinned: plugin SDK, config schema, user surface, security, journal/ledger, reasoning packet, time intent.

## Initial risks
- Model plugins require local weights at `D:\\autocapture\\models` and optional dependencies.
- OS-specific capture and vault integration not validated in this environment.
- Sanitizer heuristics need evaluation for recall/precision tradeoffs.

## ASSUMPTION (testable/configurable)
- ASSUMPTION: The project is starting from an empty scaffold and needs a full baseline implementation inside this repo. This will be validated by the presence of new source files and passing tests after scaffolding.
