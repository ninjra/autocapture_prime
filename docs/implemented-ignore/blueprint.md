### 1) Problem statement

Given a time‑ordered stream of **full‑resolution screenshots** (frames) and **no OS hooks** (no keylogging, no click capture, no accessibility API), extract and retain enough **derived** information to answer questions about:

* **What was shown** (text, tables, code panes, charts, UI elements)
* **When it was shown** (time‑indexed states)
* **How it changed** (structured deltas and diffs)
* **What the user likely did** (inferred actions grounded to UI elements with confidence and alternatives)

Constraint: **Raw images expire after 60 days** and must not be retained beyond policy. The system must persist **derived artifacts only** (text/layout/structure/diffs/provenance), sufficient for post‑TTL queries.

### 2) Goals

1. Convert each frame into a **structured “ScreenState”** with a DOM‑like element graph.
2. Convert adjacent states into **DeltaEvents** describing precise changes (cell diffs, code diffs, UI changes).
3. Infer **ActionEvents** (click/type/scroll/drag/etc.) grounded to elements with confidence and top‑k alternatives.
4. Persist only **derived artifacts** with **provenance** (frame id + bbox + extractor/version/config hash).
5. Provide a **query API** capable of answering forensic questions like:

   * “What constant value was at the top of the spreadsheet in last meeting?”
   * “What did I click by accident last week that deleted that stuff?”

### 3) Non‑goals (explicit)

* Perfect reconstruction of the original pixels after TTL (not attempted).
* Guaranteed perfect action attribution (impossible pixels‑only in some cases); instead produce **probabilistic attribution** with evidence.
* Full semantic understanding of arbitrary application internals (only what is visible).

### 4) High‑level architecture (dataflow)

**FrameIngest → Preprocess → Extractors → StateBuilder → StateMatcher → TemporalSegmenter → DeltaBuilder → ActionInferencer → Compliance → Persistence → Indexing → Query/Answer**

Key principle: store **states + deltas + actions**, not just OCR text.

### 5) Failure policy

* Extraction is **best‑effort** but **never silently hallucinates**.
* Every field is either:

  * **observed** (from OCR/VLM/pixels), or
  * **derived** (from deterministic transforms), or
  * **unknown** (explicitly marked)
* If a plugin cannot meet its acceptance constraints, it emits a **diagnostic** and leaves outputs **unset** (or partial), never invented.

### 6) Deterministic execution requirements

* All model calls run in **deterministic decode** mode (no sampling).
* All concurrency is **output‑sorted** deterministically.
* All floating outputs are **quantized** (e.g., 4 decimals) before hashing/persisting.
* Every persisted artifact includes:

  * `extractor_id`, `extractor_version`
  * `config_hash` (stable canonical JSON)
  * `input_image_sha256`
  * `schema_version`

---
