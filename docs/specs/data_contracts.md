### 1) Coordinate system

* Pixel coordinates with origin at **top‑left**.
* Bounding box format: `[x1, y1, x2, y2]` inclusive‑exclusive (`x2`, `y2` are one‑past).
* All bboxes are integers.

### 2) Canonical IDs

* `frame_id`: stable unique id for each screenshot (content addressable or external).
* `state_id`: stable id for a stable UI state (post segmentation).
* `element_id`: stable id for a UI element tracked across states (best‑effort).
* `table_id`, `code_id`, `chart_id`: stable ids tracked across states (best‑effort).

### 3) Artifact envelope (all persisted objects)

```json
{
  "artifact_id": "uuid-or-hash",
  "kind": "ScreenState|DeltaEvent|ActionEvent|TextTokens|ElementGraph|Table|CodeBlock|Chart|...",
  "schema_version": 1,
  "created_ts_ms": 0,
  "extractor": {
    "id": "plugin.id",
    "version": "1.0.0",
    "config_hash": "sha256hex"
  },
  "provenance": {
    "frame_ids": ["..."],
    "state_ids": ["..."],
    "bboxes": [[0,0,1,1]],
    "input_image_sha256": ["..."]
  },
  "confidence": 0.0,
  "payload": {}
}
```

### 4) Core schemas (JSON-like)

#### Frame

```json
{
  "frame_id": "string",
  "ts_ms": 0,
  "width": 0,
  "height": 0,
  "image_sha256": "hex",
  "source": { "monitor": "string", "session": "string" }
}
```

#### TextToken

```json
{
  "token_id": "string",
  "text": "string",
  "norm_text": "string",
  "bbox": [0,0,0,0],
  "confidence": 0.0,
  "line_id": "string|null",
  "block_id": "string|null",
  "source": "ocr|vlm",
  "flags": { "monospace_likely": false, "is_number": false }
}
```

#### UIElement

```json
{
  "element_id": "string",
  "type": "button|textbox|checkbox|radio|dropdown|tab|menu|icon|table|grid|chart|code|window|scrollbar|cell|unknown",
  "bbox": [0,0,0,0],
  "text_refs": ["token_id"],
  "label": "string|null",
  "interactable": true,
  "state": { "enabled": true, "selected": false, "focused": false, "expanded": false },
  "parent_id": "string|null",
  "children_ids": ["string"],
  "z": 0,
  "app_hint": "string|null"
}
```

#### ElementGraph

```json
{
  "state_id": "string",
  "elements": ["UIElement"],
  "edges": [{ "src": "element_id", "dst": "element_id", "kind": "contains|aligned_with|label_for" }]
}
```

#### Table (generic)

```json
{
  "table_id": "string",
  "state_id": "string",
  "bbox": [0,0,0,0],
  "grid": {
    "rows": 0,
    "cols": 0,
    "row_y": [0,0],
    "col_x": [0,0],
    "merges": [{ "r1":0,"c1":0,"r2":0,"c2":0 }]
  },
  "cells": [
    {
      "cell_id": "string",
      "r": 0,
      "c": 0,
      "bbox": [0,0,0,0],
      "text": "string",
      "norm_text": "string",
      "confidence": 0.0,
      "is_header": false
    }
  ],
  "exports": { "csv": "string", "tsv": "string" }
}
```

#### Spreadsheet extras

```json
{
  "sheet": {
    "active_cell": { "r":0,"c":0, "a1":"A1", "bbox":[0,0,0,0] },
    "formula_bar": { "text":"string", "bbox":[0,0,0,0], "confidence":0.0 },
    "headers": {
      "col_letters": [{ "c":0, "text":"A", "bbox":[0,0,0,0] }],
      "row_numbers": [{ "r":0, "text":"1", "bbox":[0,0,0,0] }]
    }
  }
}
```

#### CodeBlock

```json
{
  "code_id": "string",
  "state_id": "string",
  "bbox": [0,0,0,0],
  "language_guess": "sql|python|js|text|unknown",
  "lines": [{ "n": 1, "text": "string" }],
  "caret": { "line": 1, "col": 1, "bbox": [0,0,0,0], "confidence": 0.0 },
  "selection": [{ "start": {"line":1,"col":1}, "end": {"line":1,"col":2} }],
  "exports": { "text": "string" }
}
```

#### Chart (with derendered series)

```json
{
  "chart_id": "string",
  "state_id": "string",
  "bbox": [0,0,0,0],
  "chart_type": "bar|line|scatter|pie|unknown",
  "axes": {
    "x": { "label":"string|null", "ticks":[{"px":0,"text":"string","value":0.0|null}] },
    "y": { "label":"string|null", "ticks":[{"px":0,"text":"string","value":0.0|null}] }
  },
  "series": [
    { "name":"string|null", "points":[{"x":0.0,"y":0.0}], "confidence":0.0 }
  ],
  "exports": { "table_csv": "string" }
}
```

#### DeltaEvent

```json
{
  "delta_id": "string",
  "from_state_id": "string",
  "to_state_id": "string",
  "ts_ms": 0,
  "changes": [
    {
      "kind": "element_added|element_removed|element_changed|text_changed|table_cell_changed|table_shape_changed|code_changed|chart_changed|focus_changed|scroll_changed",
      "target_id": "string",
      "bbox": [0,0,0,0],
      "before": {},
      "after": {},
      "confidence": 0.0
    }
  ],
  "summary": { "adds":0, "removes":0, "edits":0 }
}
```

#### ActionEvent (probabilistic)

```json
{
  "action_id": "string",
  "ts_ms": 0,
  "from_state_id": "string",
  "to_state_id": "string",
  "primary": {
    "kind": "click|double_click|right_click|type|scroll|drag|key_shortcut|unknown",
    "target_element_id": "string|null",
    "target_bbox": [0,0,0,0],
    "details": { "typed_text":"string|null", "scroll_px":0, "drag_to":[0,0] },
    "confidence": 0.0
  },
  "alternatives": [
    { "kind":"click", "target_element_id":"...", "confidence":0.0 }
  ],
  "evidence": {
    "cursor_track": [{ "frame_id":"...", "bbox":[0,0,0,0], "confidence":0.0 }],
    "focus_before": "element_id|null",
    "focus_after": "element_id|null",
    "delta_kinds": ["..."]
  },
  "impact": { "deleted": false, "created": false, "modified": false, "notes": "string" }
}
```

---
