# Repo tooling summary

Source root: `/mnt/d/projects/autocapture_prime`

## Top-level layout (selected)
- Python packaging: `pyproject.toml`, `autocapture/`, `autocapture_nx/`, `tests/`
- Dev harness: `dev.sh`, `dev.ps1`, `DEV_HARNESS.md`
- Config/contracts: `config/`, `contracts/`
- Plugins: `plugins/`, `autocapture_plugins/`
- Docs: `docs/`
- Tools: `tools/` (includes `run_all_tests.py`)
- Node artifacts present: `package.json`, `package-lock.json`, `node_modules/`
- No `.github/workflows/` directory detected

## Python stack
- Build system: setuptools (`pyproject.toml`)
- Python requirement: `>=3.10`
- CLI entrypoint: `autocapture = autocapture_nx.cli:main`
- Optional extras: `sqlcipher` -> `pysqlcipher3-binary`

## Declared Python dependencies (pyproject)
- Core deps include: `cryptography`, `fastapi`, `httpx`, `mss`, `Pillow`, `pynput`, `sounddevice`, `PyYAML`, `PyPDF2`, `pytesseract`, `sentence-transformers`, `transformers`, `torch`, `tzdata`

## Tests / harness
- Test runner (Linux/WSL): `python3 tools/run_all_tests.py`
- Test runner (Windows): `tools/run_all_tests.ps1`
- `tools/run_all_tests.py` runs `autocapture_nx doctor`, `autocapture_nx --safe-mode doctor`, and unittest discovery.
- `DEV_HARNESS.md` indicates no CI workflows detected and requires fail-closed commands.

## Node / UI
- `package.json` exists with a single dependency (`npc`). No UI framework detected in repo structure.

