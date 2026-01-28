### 1) Persistence layout (recommended)

Two stores:

**A) Derived Artifact Store (long-lived)**

* Append-only, content-addressed if possible
* Suitable backends: SQLite (metadata) + files (payload blobs), or a document store
* Must support:

  * get by id
  * scan by time range
  * scan by kind
  * secondary indices

**B) Image Blob Store (TTL 60 days)**

* Optional; may be empty if images aren’t retained at all
* Must support:

  * put(frame_id, bytes, expires_at)
  * get(frame_id) (only within TTL)
  * delete(frame_id)
  * audit(enforced deletions)

### 2) Query primitives (API surface)

Implement these deterministic query functions:

```python
def q_states_time_range(ts_start_ms: int, ts_end_ms: int) -> list[str]: ...
def q_actions_time_range(ts_start_ms: int, ts_end_ms: int) -> list[str]: ...
def q_find_text(norm_text: str, ts_start_ms: int|None=None, ts_end_ms: int|None=None) -> list[dict]: ...
def q_tables_in_state(state_id: str) -> list[str]: ...
def q_table_cell_history(table_id: str, r: int, c: int, ts_start_ms: int, ts_end_ms: int) -> list[dict]: ...
def q_deltas_where(predicate: dict, ts_start_ms: int, ts_end_ms: int) -> list[str]: ...
def q_actions_where(predicate: dict, ts_start_ms: int, ts_end_ms: int) -> list[str]: ...
```

### 3) Answering “what did I click by accident last week?”

Implement deterministic retrieval:

1. Identify time range.
2. Query `ActionEvent` where:

   * `primary.kind in {click,double_click,right_click,key_shortcut}`
   * `impact.deleted == true` OR delta shows large removals
3. Sort by confidence desc.
4. Return top events with:

   * timestamp
   * target element label/type
   * evidence (cursor overlap, focus change, delta summary)
   * alternatives

### 4) Answering “constant value at top of spreadsheet from last meeting”

1. Identify meeting time window (via external calendar integration if available; otherwise explicit range).
2. Query states in that window; find spreadsheet artifacts.
3. For each spreadsheet:

   * take “top-of-sheet” captured cells (first visible row(s))
   * pick the cell(s) with low variance across window → “constant value”
4. Return value + cell address + provenance bboxes + confidence.

---
