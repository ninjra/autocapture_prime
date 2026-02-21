This section defines each recommended capability as an implementable plugin (I/O + algorithm + config + acceptance checks).

### Plugin 1: preprocess.normalize

**ID:** `preprocess.normalize`
**Inputs:** `image_bytes`
**Outputs:** `image_rgb`, `image_sha256`, `phash`, `width`, `height`

**Algorithm (deterministic)**

1. Decode bytes to RGB array (fail if decode fails).
2. Strip alpha; convert to sRGB 8‑bit.
3. Compute `sha256(image_bytes)` as `image_sha256`.
4. Compute perceptual hash `phash`:

   * Downscale to 32×32 grayscale
   * DCT
   * Use top‑left 8×8 excluding DC
   * Median threshold to 64‑bit bitstring

**Config**

* `strip_alpha: bool`
* `phash_size: int` (fixed default 8)
* `phash_downscale: int` (default 32)

**Acceptance checks**

* `width > 0`, `height > 0`
* `len(phash) == 64`

---

### Plugin 2: preprocess.tile

**ID:** `preprocess.tile`
**Inputs:** `image_rgb`
**Outputs:** `patches` (list of `{patch_id, bbox, image_rgb}`)

**Algorithm**

* Always include `full_frame` patch if configured.
* Add grid tiles:

  * tile size `tile_max_px` (default 1024)
  * overlap `overlap_px` (default 64)
* Ensure all bboxes within bounds.
* Stable ordering: sort patches by `(y1, x1, area_desc, patch_id)`.

**Optional refinement**

* If provided `text_tokens` from a prior run, add zoom patches around low confidence clusters.

**Acceptance checks**

* Coverage check: union of tiles covers full frame (when `add_full_frame=false`)
* No duplicate `patch_id`

---

### Plugin 3: ocr.onnx

**ID:** `ocr.onnx`
**Inputs:** `patches`
**Outputs:** `text_tokens`

**Algorithm**

1. Run ONNX OCR model per patch.
2. Map patch-local bboxes back to frame coordinates.
3. Merge duplicates across overlaps:

   * NMS by IoU≥0.7 and same normalized text
   * Keep highest confidence
4. Normalize:

   * `norm_text = normalize_unicode(text).strip()`
   * collapse internal whitespace

**Config**

* `min_conf: float` default 0.35
* `nms_iou: float` default 0.7
* `max_tokens: int` safety cap

**Acceptance checks**

* Tokens sorted by `(y1, x1, x2, token_id)`
* All bboxes inside frame bounds

---

### Plugin 4: ui.parse (DOM-like element graph)

**ID:** `ui.parse`
**Inputs:** `image_rgb`, `text_tokens`
**Outputs:** `element_graph_raw`

**Two supported modes**

* `mode = detector`: uses an object detector for UI elements (if available).
* `mode = vlm_json`: uses your VLM to emit strict JSON.

**VLM JSON contract**
Return a JSON object:

```json
{
  "elements": [
    {
      "type": "button",
      "bbox": [0,0,0,0],
      "text": "optional label",
      "interactable": true,
      "state": {"enabled": true, "selected": false, "focused": false, "expanded": false},
      "children": [ ... nested ... ]
    }
  ]
}
```

**Deterministic VLM settings**

* temperature = 0
* top_p = 1
* max_tokens fixed
* response must validate against schema; otherwise output diagnostics and empty graph

**Post-processing**

* Flatten nested children into a list with parent/child ids.
* Attach nearest OCR tokens to elements by bbox overlap (IoU≥0.1) and proximity.
* Infer `z` by containment depth, then top-to-bottom order.

**Acceptance checks**

* Schema validation
* All bboxes valid
* Stable sort by `(z, y1, x1)`

---

### Plugin 5: layout.assemble (text lines/blocks)

**ID:** `layout.assemble`
**Inputs:** `text_tokens`
**Outputs:** `text_lines`, `text_blocks`

**Algorithm**

* Group tokens into lines:

  * cluster by y-overlap (token midlines within threshold)
  * within each line sort by x1
* Group lines into blocks by vertical proximity and left alignment.

**Acceptance checks**

* Reading order is stable
* Block bounding boxes contain member tokens

---

### Plugin 6: extract.table (generic table TSR)

**ID:** `extract.table`
**Inputs:** `image_rgb`, `text_tokens`, `element_graph_raw` (optional)
**Outputs:** `tables`

**Algorithm (structure-first)**

1. **Detect table regions**:

   * candidate bboxes from element types `table|grid`
   * OR heuristic: dense rectangular alignment of tokens with multiple columns
2. For each region, infer grid:

   * Attempt line-based grid:

     * edge detect → morphological close/open → Hough lines
     * find dominant vertical and horizontal lines
     * compute intersections → row/col boundaries
   * Fallback token-alignment grid:

     * cluster tokens into rows by y
     * within each row, cluster into columns by x (global column centers)
3. Build cells:

   * for each grid cell bbox, gather tokens inside → join in reading order
   * compute `confidence = mean(token_conf)`
4. Merges:

   * if a cell bbox contains tokens spanning multiple adjacent grid slots, mark merge.
5. Export CSV/TSV with escaping rules.

**Config**

* `min_rows: 2`, `min_cols: 2`
* `line_grid_min_conf: 0.6`
* `token_grid_max_col_gap_px: 24` (scaled by DPI if known)

**Acceptance checks**

* `rows*cols` bounded (cap to prevent runaway)
* Each cell has deterministic address `(r,c)`
* Export round-trip: `cells -> csv -> parse -> same dims` (for non-merged)

---

### Plugin 7: extract.spreadsheet (spreadsheet-specialized)

**ID:** `extract.spreadsheet`
**Inputs:** `image_rgb`, `text_tokens`, `tables` (optional)
**Outputs:** `spreadsheets` (list of Table-like with extras)

**Detection heuristics**

* Column letters strip near top (A,B,C…)
* Row numbers strip near left (1,2,3…)
* Dense gridlines OR consistent cell spacing

**Extraction outputs**

* Active cell bbox (thick border highlight heuristic)
* Formula bar bbox/text (search near top for “fx” or long textbox)
* Header mappings: map pixel columns to column letters when visible

**Acceptance checks**

* If headers detected, active cell’s A1 must be consistent with pixel position
* Persist “top-of-sheet” region values explicitly:

  * store first visible row (header-adjacent) cell values and bboxes even if partial
  * this directly supports “constant value at top” queries post‑TTL

---

### Plugin 8: extract.code (SQL/editor panes)

**ID:** `extract.code`
**Inputs:** `image_rgb`, `text_tokens`, `element_graph_raw` (optional)
**Outputs:** `code_blocks`

**Algorithm**

1. Detect code regions:

   * high ratio of monospace-like tokens (uniform char widths) OR
   * keywords density (“SELECT”, “FROM”, “WHERE”, braces) OR
   * element type `code`
2. Reconstruct lines:

   * cluster tokens by y
   * preserve indentation by measuring left padding in pixels and converting to spaces using median character width
3. Detect caret/selection:

   * caret: thin vertical bright line inside code region
   * selection: uniform highlight rectangles behind text
4. Language guess:

   * rule-based: if contains `SELECT` and `FROM` → `sql`
5. Validation (non-fatal):

   * If sql: ensure parentheses/quotes balanced (heuristic)
   * If imbalance likely due to OCR, flag diagnostics and lower confidence

**Acceptance checks**

* Indentation is stable between runs
* Line numbers (if present) are excluded from code text but captured as metadata

---

### Plugin 9: extract.chart (chart derendering)

**ID:** `extract.chart`
**Inputs:** `image_rgb`, `text_tokens`
**Outputs:** `charts`

**Algorithm**

1. Detect chart region:

   * rectangular plot area with axes-like lines
   * legend-like text clusters
2. Determine chart type:

   * bar: repeated filled rectangles aligned on baseline
   * line: thin continuous curves
   * scatter: many small point blobs
3. Extract axes labels/ticks via OCR tokens near axes.
4. Convert pixel → value mapping:

   * derive y-scale from tick labels when numeric and at least 2 ticks readable
   * same for x when numeric/time-like
5. Extract series:

   * bar: contour detect rectangles; compute heights → values
   * line: skeletonize and sample points; map to values
6. If mapping cannot be established, still emit chart bbox + labels, but leave series empty.

**Guardrails**

* Never invent numeric values without readable ticks or explicit labels.
* If confidence < threshold, emit only structural chart metadata.

**Acceptance checks**

* If `series` populated, must include mapping evidence (ticks count ≥ 2)

---

### Plugin 10: track.cursor

**ID:** `track.cursor`
**Inputs:** `image_rgb`
**Outputs:** `cursor_track_point` `{bbox, type, confidence}`

**Algorithm**

* Template-match against a built-in set of cursor templates (arrow, I‑beam, hand, resize).
* Multi-scale search within bounded scales (e.g., 0.75×, 1.0×, 1.25×).
* Choose best score above threshold.

**Acceptance checks**

* If below threshold, output `type="unknown"` with low confidence (do not guess)

---

### Plugin 11: build.state

**ID:** `build.state`
**Inputs:** `frame`, `text_tokens`, `element_graph_raw` (optional), `tables`, `spreadsheets`, `code_blocks`, `charts`, `cursor_track_point`
**Outputs:** `screen_state`

**Algorithm**

* Create `ScreenState`:

  * attach all artifacts
  * compute state-level summary fields:

    * `visible_apps` (heuristic from window title tokens)
    * `focus_element_id` (if detectable)
* Compute `state_confidence` from weighted confidences.

**Acceptance checks**

* All referenced ids exist (no dangling references)

---

### Plugin 12: match.ids (stable element ids across states)

**ID:** `match.ids`
**Inputs:** `screen_state`, `prev_screen_state`
**Outputs:** `screen_state_tracked`

**Algorithm**

1. For each new element, compute signature:

   * `type`
   * normalized bbox (relative coords rounded to 1e‑4)
   * text hash of attached tokens
   * parent signature (if any)
2. Build cost matrix between prev and new:

   * `cost = 1 - IoU`
   * * `0.5` if type mismatch
   * * `0.3 * text_distance` (0..1)
   * * `0.2` if parent mismatch
3. Solve assignment deterministically:

   * Hungarian algorithm
   * accept matches with `cost <= 0.7`
4. Preserve old `element_id` for matches; mint new ids otherwise.

**Acceptance checks**

* No duplicate element ids
* Stable sort of elements post-match

---

### Plugin 13: temporal.segment (stable state boundaries)

**ID:** `temporal.segment`
**Inputs:** `phash`, `prev_phash`, (optional) `volatile_regions_model`
**Outputs:** `state_boundary: bool`, `boundary_reason`

**Algorithm**

* Compute Hamming distance `d` between current and previous phash.
* If `d <= d_stable` → not a boundary.
* If `d >= d_boundary` → boundary.
* If between: defer to cheap visual diff on a downscaled frame and ignore volatile boxes (clocks/spinners) if available.

**Config**

* `d_stable: 4`
* `d_boundary: 12`

**Acceptance checks**

* Boundary decision is deterministic given inputs

---

### Plugin 14: build.delta

**ID:** `build.delta`
**Inputs:** `prev_screen_state_tracked`, `screen_state_tracked`
**Outputs:** `delta_event`

**Algorithm**

* Element diff:

  * added/removed by element_id sets
  * changed if bbox shift > threshold, text hash changed, or state flags changed
* Table diff:

  * match tables by IoU + region overlap
  * diff by `(r,c)->norm_text`
* Code diff:

  * line-based diff (deterministic Myers or LCS)
* Chart diff:

  * series/ticks changes

**Acceptance checks**

* Change list sorted by `(kind, target_id)`
* Summary counts equal computed changes

---

### Plugin 15: infer.action (pixels-only action inference)

**ID:** `infer.action`
**Inputs:** `delta_event`, `cursor_track_point`, `prev_screen_state_tracked`, `screen_state_tracked`
**Outputs:** `action_event`

**Primary action kinds (fixed set)**
`click, double_click, right_click, type, scroll, drag, key_shortcut, unknown`

**Heuristic inference (deterministic scoring)**
Compute candidate scores in [0,1]:

* **Type** candidate:

  * focus stable on textbox/code region AND `text_changed` delta inside focused region
  * score boosts by amount of inserted characters and caret movement evidence

* **Click** candidate:

  * cursor bbox overlaps an interactable element in prev state
  * AND delta includes `expanded/menu_open/focus_changed/element_state_changed`
  * score boosts if element shows pressed/hover state (if detectable)

* **Scroll** candidate:

  * large content shift in a scrollable region
  * AND scrollbar thumb moved (if detectable) OR repeated vertical translation of token bboxes

* **Drag** candidate:

  * cursor moved significantly AND an element relocated OR selection region resized

Pick top candidate as `primary`. Emit `alternatives` as next best (cap 2).

**Impact classification**
Set:

* `deleted=true` if delta includes large removals (rows deleted, file removed, text deleted) and UI indicates destructive action.
* Otherwise `modified/created` based on delta composition.

**Acceptance checks**

* Always emit `primary.kind`; if uncertain, `unknown`
* If `confidence < 0.5`, must provide ≥1 alternative unless none exist

---

### Plugin 16: compliance.redact (derived-only + DLP)

**ID:** `compliance.redact`
**Inputs:** any artifacts to be persisted
**Outputs:** redacted artifacts (same schema)

**Rules (deterministic)**

* For all text fields, apply pattern detectors:

  * emails, IPv4/IPv6, long hex strings, JWT-like tokens, API key-like patterns
* Replace sensitive substrings with:

  * `"[REDACTED:<type>:<sha256(prefix)>]"` (prefix-limited hashing)
* Preserve geometry + confidence.
* Record redaction counts in metrics.

**Hard gate**

* If policy forbids persisting certain app windows, drop artifacts whose `app_hint` matches denylist.

**Acceptance checks**

* No raw secrets remain after scan (unit-tested fixtures)

---

### Plugin 17: persist (derived store + TTL image store)

**ID:** `persist`
**Inputs:** redacted artifacts + metadata
**Outputs:** persisted ids + commit record

**Storage invariants**

* Persist **no raw pixels** in the derived store.
* If there is an image blob store, enforce TTL=60 days via:

  * expiration metadata at write time
  * periodic sweeper + audit log

**Acceptance checks**

* Artifact envelope present for each persisted object
* Provenance references valid

---

### Plugin 18: index (text + structure + vector)

**ID:** `index`
**Inputs:** persisted artifacts
**Outputs:** updated indices

**Indices**

* Inverted text index: `(norm_text -> postings)` with `{artifact_id, bbox, ts_ms}`
* Time index: `(ts_ms -> state_id/action_id/delta_id)`
* Structure index:

  * tables by `(table_id, sheet_name?, visible_headers_hash)`
  * code blocks by `(language, file_hint?)`
* Optional vector index:

  * embeddings of element labels/text blocks/state summaries (computed locally)

**Acceptance checks**

* Index updates are idempotent (re-run yields same postings)

---
