# Autocapture Prime

Plugin-forward kernel and baseline plugins for Autocapture NX.

## Getting started (local only)
```bash
python3 -m autocapture_nx doctor
python3 -m autocapture_nx config show
```

## Tests
Linux/WSL:
```bash
python3 tools/run_all_tests.py
```

Windows (PowerShell):
```powershell
\tools\run_all_tests.ps1
```

Notes:
- The script creates a local `.venv` and installs deps.
- For offline installs, place wheels in `tools\..\wheels` or set `AUTO_CAPTURE_WHEELHOUSE`.
- By default it allows pip downloads; to disable, set `AUTO_CAPTURE_ALLOW_NETWORK=0`.

## Docs
- `docs/plugin_model.md`
- `docs/configuration.md`
- `docs/safe_mode.md`
- `docs/devtools.md`
- `docs/windows_setup.md`
