### 1) Pipeline stages (canonical order)

Use these stage names and output keys so plugins are composable.

| Stage                | Output keys (minimum)                |
| -------------------- | ------------------------------------ |
| ingest               | `frame`, `image_bytes`               |
| preprocess.normalize | `image_rgb`, `image_sha256`, `phash` |
| preprocess.tile      | `patches`                            |
| ocr.onnx             | `text_tokens`                        |
| ui.parse             | `element_graph_raw`                  |
| layout.assemble      | `text_lines`, `text_blocks`          |
| extract.table        | `tables`                             |
| extract.spreadsheet  | `spreadsheets`                       |
| extract.code         | `code_blocks`                        |
| extract.chart        | `charts`                             |
| track.cursor         | `cursor_track_point`                 |
| build.state          | `screen_state`                       |
| match.ids            | `screen_state_tracked`               |
| temporal.segment     | `state_boundary`                     |
| build.delta          | `delta_event`                        |
| infer.action         | `action_event`                       |
| compliance.redact    | `redacted_*` (in‑place or parallel)  |
| persist              | persisted artifacts                  |
| index                | indices updated                      |

### 2) Example pipeline config (YAML)

```yaml
pipeline:
  - id: ingest.frame
    required: true

  - id: preprocess.normalize
    required: true
    config:
      rgb: true
      strip_alpha: true

  - id: preprocess.tile
    required: true
    config:
      tile_max_px: 1024
      overlap_px: 64
      add_full_frame: true
      add_zoom_for_low_conf_ocr: true

  - id: ocr.onnx
    required: true
    config:
      min_conf: 0.35

  - id: ui.parse
    required: false
    config:
      mode: "vlm_json"
      json_schema_strict: true

  - id: extract.table
    required: false

  - id: extract.spreadsheet
    required: false

  - id: extract.code
    required: false

  - id: extract.chart
    required: false

  - id: track.cursor
    required: false

  - id: build.state
    required: true

  - id: match.ids
    required: true

  - id: temporal.segment
    required: true

  - id: build.delta
    required: true

  - id: infer.action
    required: false

  - id: compliance.redact
    required: true

  - id: persist
    required: true

  - id: index
    required: true
```

### 3) Heavy vs light passes

Implement two execution modes per frame:

* **Light pass**: normalize + phash + cursor + cheap diffs
* **Heavy pass**: full extractors (OCR/UI/table/code/chart) only on **state boundaries** or when confidence is low

This reduces compute and stabilizes outputs.

---
