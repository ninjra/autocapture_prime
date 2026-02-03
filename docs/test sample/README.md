# Fixture: test sample screenshot

This fixture drives the CLI pipeline harness for deterministic, lossless processing of a known screenshot. It is used to validate capture → processing → query accuracy with citations.

Contents
- `Screenshot 2026-02-02 113519.png`: the single input frame.
- `fixture_manifest.json`: fixture metadata and query expectations.

Query expectations
- `queries.mode` controls how the runner builds query tests:
  - `auto`: queries are generated from OCR/SST tokens + visible app/window metadata (if available).
  - `explicit`: use `queries.explicit` entries only.
  - `auto` + `explicit`: both sets run when `mode` is `auto`.
- `queries.require_citations` and `queries.require_state` enforce citeability and answer quality.
- `match_mode` defaults to `exact_word` with `casefold=true` and whitespace normalization.

Updating this fixture
1. Replace the screenshot file (keep it lossless).
2. Update `fixture_manifest.json`:
   - Ensure the path matches the file.
   - Add explicit queries if needed for expected text, windows, or program names.
3. Run:
   - `python tools/run_fixture_pipeline.py --manifest "docs/test sample/fixture_manifest.json"`

Notes
- The runner archives outputs under `artifacts/fixture_runs/<timestamp>/`.
- No deletion occurs; results are append-only.
