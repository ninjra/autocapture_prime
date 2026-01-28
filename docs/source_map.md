### Proposed repository layout

```text
src/
  core/
    types.py                 # dataclasses for Frame/State/Artifacts
    plugin_base.py           # Plugin, PluginInput/Output, RunContext
    validate.py              # schema + bbox + provenance validators
    hashcanon.py             # canonical json + config hashing
    diff.py                  # deterministic diffs (text/table/code)
    match.py                 # Hungarian matching + cost functions
    phash.py                 # perceptual hash
  pipeline/
    orchestrator.py          # executes configured plugin chain
    registry.py              # plugin discovery/registration
    config.py                # config parsing + validation
  stores/
    artifact_store.py        # derived artifact persistence
    image_store.py           # TTL image store interface (optional)
    index_store.py           # inverted/time/structure indices
  plugins/
    preprocess_normalize/plugin.py
    preprocess_tile/plugin.py
    ocr_onnx/plugin.py
    ui_parse/plugin.py
    layout_assemble/plugin.py
    extract_table/plugin.py
    extract_spreadsheet/plugin.py
    extract_code/plugin.py
    extract_chart/plugin.py
    track_cursor/plugin.py
    build_state/plugin.py
    match_ids/plugin.py
    temporal_segment/plugin.py
    build_delta/plugin.py
    infer_action/plugin.py
    compliance_redact/plugin.py
    persist/plugin.py
    index/plugin.py
tests/
  fixtures/
  golden/
  test_determinism.py
  test_tables.py
  test_code.py
  test_deltas_actions.py
docs/
  blueprint.md
  specs/
  adr/
```

---
