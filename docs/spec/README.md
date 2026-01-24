# Spec Artifacts

This folder contains versioned spec snapshots used for deterministic validation gates.

- `autocapture_nx_blueprint_2026-01-24.md`: minimal structured spec placeholder (all unspecified values remain `[MISSING_VALUE]`).

Validation:
```bash
PYTHONPATH=. python3 -m unittest tests/test_blueprint_spec_validation.py -q
```
