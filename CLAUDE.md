# CLAUDE.md — Autocapture Prime

## Project Overview

Autocapture Prime is the plugin-forward kernel and baseline plugin set for **Autocapture NX**, a local-first screen/audio capture, indexing, and retrieval system. The kernel loads configuration, enforces security policy, and composes capabilities — all functional behavior is provided by plugins.

- **Language**: Python 3.10+
- **License**: Proprietary
- **Package name**: `autocapture_nx`
- **CLI entry point**: `autocapture` (via `autocapture_nx.cli:main`)

## Repository Structure

```
autocapture_prime/
├── autocapture_nx/          # Main package
│   ├── kernel/              # Core kernel: config, loader, crypto, hashing, errors
│   │   ├── config.py        # Config loading, merging (default + user), schema validation
│   │   ├── loader.py        # Kernel bootstrap, doctor checks, meta-plugin application
│   │   ├── crypto.py        # AES-GCM encryption, HKDF key derivation, root key management
│   │   ├── hashing.py       # SHA-256 helpers for files, directories, contracts
│   │   ├── canonical_json.py # Deterministic JSON serialization
│   │   ├── key_rotation.py  # Key rotation with ledger/anchor auditing
│   │   ├── keyring.py       # Key storage and versioning
│   │   ├── query.py         # Query pipeline: intent parsing → retrieval → answer building
│   │   ├── system.py        # System dataclass (config + plugins + capabilities)
│   │   └── errors.py        # Error hierarchy (AutocaptureError base)
│   ├── plugin_system/       # Plugin discovery, loading, hosting, permissions
│   │   ├── registry.py      # PluginRegistry, CapabilityRegistry, manifest/lock validation
│   │   ├── api.py           # PluginContext, PluginBase
│   │   ├── host.py          # SubprocessPlugin hosting
│   │   ├── host_runner.py   # Subprocess entry point
│   │   └── runtime.py       # network_guard context manager
│   ├── windows/             # Windows-specific: DPAPI, capture, input, sandbox
│   └── cli.py               # CLI: doctor, config, plugins, run, query, keys, devtools
├── plugins/builtin/         # ~29 built-in plugins (each has plugin.json + plugin.py)
├── config/
│   ├── default.json         # Default configuration (authoritative)
│   └── plugin_locks.json    # Plugin hash lockfile
├── contracts/               # Pinned contracts and schemas (hash-locked in lock.json)
│   ├── config_schema.json   # JSON Schema for configuration
│   ├── plugin_manifest.schema.json
│   ├── plugin_sdk.md        # Plugin SDK contract
│   ├── security.md          # Security contract
│   ├── lock.json            # Contract file hash lock
│   └── *.schema.json        # Ledger, journal, reasoning packet, time intent schemas
├── tests/                   # Unit tests (stdlib unittest)
├── tools/
│   ├── run_all_tests.py     # Test runner (Linux/WSL)
│   ├── run_all_tests.ps1    # Test runner (Windows/PowerShell)
│   ├── validate_blueprint_spec.py
│   └── hypervisor/          # Plugin lock updater, contract lock updater
├── docs/                    # Design docs, blueprints, specs, gap analysis
├── ops/dev/                 # Dev harness config (common.env, ports.env)
├── dev.sh                   # Dev harness (POSIX/WSL)
├── dev.ps1                  # Dev harness (Windows)
├── pyproject.toml           # Build config (setuptools)
└── AGENTS.md                # AI agent instructions (Codex-compatible)
```

## Quick Start Commands

### Run tests (primary verification command)

```bash
# Linux/WSL — preferred
python3 tools/run_all_tests.py

# Windows PowerShell
.\tools\run_all_tests.ps1
```

The test runner:
1. Runs `autocapture doctor` (normal + safe mode)
2. Runs blueprint spec validation
3. Discovers and runs all tests in `tests/`
4. Sets `PYTHONPATH=.` automatically

### Run tests directly with unittest

```bash
python3 -m unittest discover -s tests -q
```

### Dev harness

```bash
./dev.sh test     # Run tests via dev harness
./dev.sh doctor   # Validate repo assumptions
./dev.sh up       # Start backend (requires DEV_BACKEND_CMD in ops/dev/common.env)
./dev.sh down     # Stop backend
./dev.sh reset    # Clear .dev/ state
```

### CLI

```bash
python3 -m autocapture_nx doctor           # Health checks
python3 -m autocapture_nx config show      # Dump merged config
python3 -m autocapture_nx plugins list     # List discovered plugins
python3 -m autocapture_nx query "text"     # Run a query
python3 -m autocapture_nx keys rotate      # Rotate encryption keys
```

## Architecture

### Kernel + Plugin Model

The kernel is deliberately thin. It:
1. Loads and merges config (`config/default.json` + optional `config/user.json`)
2. Validates config against `contracts/config_schema.json`
3. Discovers, validates, and loads plugins via `PluginRegistry`
4. Composes a `System` object mapping capability names to plugin implementations
5. Applies meta-plugins (configurators, policy) if explicitly allowed

All functional behavior (storage, capture, retrieval, privacy, etc.) is provided by plugins that register **capabilities** — namespaced strings like `storage.metadata`, `capture.source`, `retrieval.strategy`, etc.

### Plugin Lifecycle

1. Plugins live in `plugins/builtin/<name>/` with a `plugin.json` manifest and `plugin.py` entry point
2. Each manifest declares: `plugin_id`, `version`, `entrypoints`, `permissions`, `depends_on`, `compat`
3. Plugins must be in the config `allowlist` to load
4. Plugin hashes are verified against `config/plugin_locks.json`
5. Factory signature: `create_plugin(plugin_id: str, context: PluginContext) -> Plugin`
6. Plugins must implement `capabilities() -> dict[str, Any]`

### Capability Names

Key capabilities (from `contracts/plugin_sdk.md`):
`egress.gateway`, `privacy.egress_sanitizer`, `storage.metadata`, `storage.media`, `storage.entity_map`, `storage.keyring`, `capture.source`, `capture.audio`, `tracking.input`, `window.metadata`, `retrieval.strategy`, `time.intent_parser`, `journal.writer`, `ledger.writer`, `anchor.writer`, `runtime.governor`, `capture.backpressure`, `answer.builder`, `citation.validator`, `observability.logger`, `devtools.diffusion`, `devtools.ast_ir`, `meta.configurator`, `meta.policy`

### Security Model

- **Fail-closed**: Network denied by default; only `builtin.egress.gateway` may request network
- **Allowlist-only**: Unlisted plugins do not load
- **Hash-locked**: Plugin manifest + artifact hashes verified against lockfile
- **Encryption-at-rest**: Enforced via `storage.encryption_required`
- **Subprocess isolation**: Default hosting mode with explicit in-proc allowlist
- **Network guard**: `runtime.network_guard` patches socket APIs to block unauthorized access
- **Safe mode**: Only `plugins.default_pack` loads; user config overrides ignored
- **Egress sanitization**: All outbound payloads pass through `privacy.egress_sanitizer`
- **Audit trail**: Ledger entries are hash-chained; anchors record ledger head hashes

### Configuration

- `config/default.json` — authoritative defaults (committed)
- `config/user.json` — user overrides (gitignored), deep-merged over defaults
- Safe mode ignores user overrides entirely
- Validated against `contracts/config_schema.json` on every load

## Key Conventions

### Code Style

- Python 3.10+ with `from __future__ import annotations`
- Type hints used throughout (native `dict`, `list`, `|` union syntax)
- Dataclasses for data structures (`@dataclass`, `@dataclass(frozen=True)`)
- No external linter/formatter configured — follow existing code style
- Module docstrings at the top of every file
- Errors use the `AutocaptureError` hierarchy from `kernel/errors.py`

### Testing

- **Framework**: `unittest` (stdlib) — no pytest
- **Pattern**: `tests/test_<module>.py` with `class <Name>Tests(unittest.TestCase)`
- **Temp files**: Use `tempfile.TemporaryDirectory()` for isolated test state
- **Config fixtures**: Copy `config/default.json` and `contracts/config_schema.json` into temp dirs
- Tests run from the repo root with `PYTHONPATH=.`

### Contracts

Files in `contracts/` are **pinned** — their SHA-256 hashes are tracked in `contracts/lock.json`. If you modify a contract file, you must update the lock:

```bash
python3 tools/hypervisor/scripts/update_contract_lock.py
```

Similarly, plugin changes require updating `config/plugin_locks.json`:

```bash
python3 -m autocapture_nx plugins approve
```

### Error Hierarchy

```
AutocaptureError (base)
├── ConfigError        — config loading/validation failures
├── PluginError        — plugin loading/validation failures
├── PermissionError    — permission check failures
├── SafeModeError      — safe-mode invariant violations
└── NetworkDisabledError — unauthorized network access
```

## Development Rules

These rules come from `AGENTS.md` and the project conventions:

1. **No network access** — do not make outbound requests during development/testing
2. **No sudo/admin** — no elevated privilege commands
3. **No global installs** — use local venvs only
4. **Fail closed** — never guess commands; add TODOs if uncertain
5. **Additive changes** — do not remove existing behavior unless equivalence is proven
6. **Prefer the dev harness** — use `dev.sh`/`dev.ps1` and keep CI parity
7. **Update locks after changes** — run contract and plugin lock updaters when modifying pinned files
8. **Plugin changes require hash update** — any edit to a plugin's `plugin.json` or `plugin.py` requires updating `config/plugin_locks.json`

## Environment Notes

- The test runner creates a local `.venv` and installs deps automatically
- SQLCipher support is optional: set `AUTO_CAPTURE_EXTRAS=sqlcipher` to include it
- For offline installs, place wheels in `wheels/` or set `AUTO_CAPTURE_WHEELHOUSE`
- Set `AUTO_CAPTURE_ALLOW_NETWORK=0` to disable pip downloads during test setup
- Logs go to `tools/run_all_tests.log`; reports to `tools/run_all_tests_report.json`
- `.dev/` directory stores dev harness state (logs, PIDs, cache) — gitignored

## File Change Checklist

When making changes, verify:

- [ ] Tests pass: `python3 tools/run_all_tests.py`
- [ ] Doctor passes: `python3 -m autocapture_nx doctor`
- [ ] If contract files changed: update `contracts/lock.json`
- [ ] If plugin files changed: update `config/plugin_locks.json`
- [ ] If config schema changed: validate against `contracts/config_schema.json`
- [ ] New plugins are added to the allowlist in `config/default.json`
