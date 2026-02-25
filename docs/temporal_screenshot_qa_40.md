# Temporal Screenshot QA (Zero‑shot) — Advanced Question Suite (40)

This file is a **question archetype bank** plus **copy/paste Codex CLI prompts** to generate **40 fully-instantiated, answer-verified Q&A items** from your **processed** screenshot+UIA+HID stores (raw media already reaped).

---

## Operating assumptions (locked)
- **Authoritative time:** screenshot time (the timestamp rendered *on-screen*) is canonical.
- **Per record:** new records include screenshot-derived text + UIA snapshot + HID slice aligned to the same timeline.
- **Stores available at query time:** **SQLite metadata** + **temporal vector store** (no raw screenshots).
- **Answer format required:** **Markdown answer** followed by an **embedded JSON block**.
- **Failure policy:** output **NOT_FOUND** or **NEEDS_CLARIFICATION**. **Never** output “top‑k candidates.”

---

## Output contract for answers (what your pipeline should return)

### Human-readable section (Markdown)
Keep it short and factual (1–6 lines), no speculation.

### Embedded machine-readable JSON block
Every answer must include exactly one JSON block like:

```json
{
  "status": "OK",
  "question_id": "Q01",
  "time_window": {
    "start": "YYYY-MM-DDTHH:MM:SS",
    "end": "YYYY-MM-DDTHH:MM:SS",
    "timezone": "America/Denver",
    "source": "screenshot_time_overlay"
  },
  "answer": {
    "type": "string|number|boolean|timestamp|duration|list|object",
    "value": "..."
  },
  "evidence": {
    "frames": [
      {
        "frame_id": "opaque-id",
        "screenshot_time": "YYYY-MM-DDTHH:MM:SS",
        "app": "optional",
        "window_title": "optional",
        "screen_bbox": {"x": 0, "y": 0, "w": 0, "h": 0},
        "text_spans": [{"text": "...", "bbox": {"x":0,"y":0,"w":0,"h":0}}],
        "uia_refs": [{"node_id":"...","role":"...","name":"...","value":"..."}],
        "hid_refs": [{"event_id":"...","type":"key|mouse|scroll","detail":"..."}]
      }
    ],
    "joins": [
      {"kind":"uia↔frame", "left":"frame_id", "right":"uia_frame_id"},
      {"kind":"hid↔frame", "left":"hid_ts", "right":"frame_ts"}
    ]
  },
  "notes": "optional, factual only"
}
```

**Hard rule:** If any part cannot be grounded in stored evidence → set `status` to `NOT_FOUND` or `NEEDS_CLARIFICATION` and do not guess.

---

## Evidence requirements (minimum bar)
For `status="OK"` answers:
- Provide **at least one `frame_id` + screenshot_time** that directly supports the claim.
- For temporal aggregations, provide **2+ frames** spanning the interval *or* an interval proof derived from contiguous segments.
- For HID-derived claims, include **the exact HID event ids** used.
- For UIA-derived claims, include **node_id + role + name** (and value/state if relevant).
- For vector-store retrieval, include the **doc_id / embedding_id** used to retrieve the supporting frames.

---

## Question archetypes (40)

Each archetype below is intentionally **template-like**. When generating an eval set, you **instantiate placeholders** using facts you *already verified exist* in your processed stores.

### Q01 — Unique windows in a rolling window
**Question:** In the last **{DUR}**, what **unique top-level windows** (app + window title) were visible, and for each what were the **first_seen** and **last_seen** screenshot times?  
**Requires:** UIA (top-level window), screenshot_time, temporal grouping.  
**Answer type:** `list` of `{app,title,first_seen,last_seen}`.

### Q02 — Unique domains/hosts observed
**Question:** In the last **{DUR}**, what **unique URL hosts/domains** were visible on screen, and what was the **last_seen** time for each?  
**Requires:** screenshot text + UIA (address bar if available) + regex host parsing.  
**Answer type:** `list` of `{host,last_seen}`.

### Q03 — Error/toast/dialog inventory + duration visible
**Question:** In the last **{DUR}**, list each distinct **error/toast/dialog message** that appeared and its **first_seen**, **last_seen**, and **total_visible_duration** (merge gaps ≤ {GAP_SEC}s).  
**Requires:** screenshot text + UIA dialog roles.  
**Answer type:** `list`.

### Q04 — Clicked call-to-action buttons
**Question:** In the last **{DUR}**, what **button labels** did we click (UIA role=button), and what was the **most recent click time** for each label?  
**Requires:** HID clicks + UIA hit-test/active element + temporal join.  
**Answer type:** `list`.

### Q05 — Most frequent focus target
**Question:** In the last **{DUR}**, which **UIA element** (role+name) held focus the **most total time**, and what was that total focused duration?  
**Requires:** UIA focus changes over time.  
**Answer type:** `object` `{role,name,duration_sec}`.

---

### Q06 — Count + duration for a verified text snippet
**Question:** Between **{T0}** and **{T1}**, how many frames contained the text **“{TEXT_SNIPPET}”**, and what was the **total visible duration** (merge gaps ≤ {GAP_SEC}s)?  
**Requires:** screenshot text spans + temporal merge.  
**Answer type:** `object` `{frame_count,total_visible_duration_sec}`.

### Q07 — Longest continuous foreground app session
**Question:** In the last **{DUR}**, what was the **longest continuous time** the foreground app was **{APP}**, and what were the start/end screenshot times?  
**Requires:** UIA active window/app + temporal segmentation.  
**Answer type:** `object`.

### Q08 — Peak window-switching interval
**Question:** In the last **{DUR}**, during which **single {BUCKET_MIN}-minute interval** did the active window change the most, and how many changes occurred?  
**Requires:** UIA active window changes + bucketing.  
**Answer type:** `object` `{bucket_start,bucket_end,switch_count}`.

### Q09 — Click cadence
**Question:** In the last **{DUR}**, what was the **median time between mouse clicks** (in seconds), measured by HID events?  
**Requires:** HID click timestamps + robust stats.  
**Answer type:** `number`.

### Q10 — Type-to-UI latency
**Question:** Identify a verified instance where we typed **“{TYPED_TOKEN}”** and then the UI reflected it (the same token became visible). What was the **latency** from last keypress to first visible occurrence?  
**Requires:** HID key events + screenshot text occurrence + temporal join.  
**Answer type:** `object` `{typed_end_ts,visible_ts,latency_ms}`.

---

### Q11 — Shortcut-triggered UI change
**Question:** After the most recent use of shortcut **{KEY_COMBO}** within **{DUR}**, what was the immediate UI change (window title/app/URL before vs after) within {DELTA_SEC}s?  
**Requires:** HID key combo + UIA/window/url before-after diff.  
**Answer type:** `object`.

### Q12 — Click → navigation (URL change)
**Question:** Find a verified click on UIA element **“{UIA_NAME}”** that caused navigation (URL host or path changed). What were the URLs before and after, and the time delta?  
**Requires:** HID click + UIA target + URL extraction.  
**Answer type:** `object`.

### Q13 — Most recent save/export dialog
**Question:** What was the most recent **save/export** dialog we saw, what **filename** was shown, and when was it dismissed?  
**Requires:** UIA dialog snapshot + screenshot text.  
**Answer type:** `object`.

### Q14 — Modal dialog lifecycle
**Question:** Identify the most recent **modal dialog** lifecycle: when did it appear, when did it disappear, what was its title, and what action closed it (click vs key)?  
**Requires:** UIA modal role + HID.  
**Answer type:** `object`.

### Q15 — Toggle/checkbox state transition
**Question:** Find the most recent time a **toggle/checkbox** changed state. What was the label, old state, new state, and the triggering HID event?  
**Requires:** UIA state + HID.  
**Answer type:** `object`.

---

### Q16 — Left vs right half app layout (7680×2160)
**Question:** At screenshot time **{TS}**, what were the primary visible apps/windows on the **left half** vs **right half** of the 7680×2160 canvas?  
**Requires:** UIA window bounding boxes + screen geometry.  
**Answer type:** `object` `{left:[...], right:[...]}`.

### Q17 — New window appearance in a quadrant
**Question:** In the last **{DUR}**, how many times did a **new top-level window** first appear with its centroid in the **top-right quadrant**, and what was the most recent instance?  
**Requires:** UIA window bbox + first_seen detection.  
**Answer type:** `object`.

### Q18 — Notification banner text + location
**Question:** What was the most recent **notification/banner** we saw? Provide its text, screenshot time, and screen bbox.  
**Requires:** screenshot text + UIA notification roles or visual region classification.  
**Answer type:** `object`.

### Q19 — Cross-monitor cursor traverse
**Question:** Find an instance where the mouse cursor moved from **x < 3840** to **x ≥ 3840** without clicking. What were the start/end positions and times?  
**Requires:** HID mouse move stream.  
**Answer type:** `object`.

### Q20 — Scrollable content detection
**Question:** At time **{TS}**, was there any visible scrollable container with content not fully shown (scrollbar not at end)? If yes, which container (role/name) and what was its scroll position?  
**Requires:** UIA scroll patterns.  
**Answer type:** `object` or `NOT_FOUND`.

---

### Q21 — Numeric min/max within an app
**Question:** In the last **{DUR}**, within app **{APP}**, what were the **min** and **max** currency-like amounts shown (e.g., $12.34), and when did each occur?  
**Requires:** screenshot text regex + app filter.  
**Answer type:** `object`.

### Q22 — Percentage change event
**Question:** Identify the most recent time a **percentage value** on screen changed (e.g., 41% → 42%). What changed, and what was the time delta?  
**Requires:** text tracking across frames.  
**Answer type:** `object`.

### Q23 — Non-overlay date extraction
**Question:** What is the most recent **non-overlay date** (not the capture timestamp) shown on screen, and what UI context did it belong to (window/app/element)?  
**Requires:** date regex + UIA context.  
**Answer type:** `object`.

### Q24 — Time-of-day strings relative to screenshot time
**Question:** In a verified {DUR} window, how many time-of-day strings (e.g., “3:30 PM”) were visible that referred to times **after** the screenshot timestamp on that frame?  
**Requires:** time parsing + compare to screenshot_time.  
**Answer type:** `number`.

### Q25 — Reappearing identifier tracking
**Question:** Pick a visible identifier matching **{ID_REGEX}** (e.g., ABC-123). When did it first appear, and did it reappear later? Provide first/last seen times.  
**Requires:** regex + temporal scan.  
**Answer type:** `object`.

---

### Q26 — Focus ancestry path
**Question:** At time **{TS}**, what was the full UIA ancestry path (roles+names) of the focused element?  
**Requires:** UIA tree.  
**Answer type:** `list` of `{role,name}`.

### Q27 — Click with no visible effect
**Question:** Find a click event that produced **no visible effect** within {DELTA_SEC}s (no window title change, no URL change, and no significant text delta). Provide the clicked element and time.  
**Requires:** HID click + UIA target + before/after diff.  
**Answer type:** `object`.

### Q28 — Auto-refresh change (no HID)
**Question:** Identify a UI value that changed **without any HID input** within ±{QUIET_SEC}s (auto-refresh). What changed and when?  
**Requires:** UIA value diff + HID silence window.  
**Answer type:** `object`.

### Q29 — Paste-like text entry detection
**Question:** Find an instance where a text field value jumped by ≥ {N} chars within {DELTA_SEC}s (suggesting paste). What field (label/path) and when did it happen?  
**Requires:** UIA value changes + temporal diff.  
**Answer type:** `object`.

### Q30 — Most clicked UIA role
**Question:** In the last **{DUR}**, which UIA role received the most clicks (button/link/checkbox/etc), and what was the count?  
**Requires:** HID clicks + UIA role attribution.  
**Answer type:** `object`.

---

### Q31 — State-to-state action reconstruction
**Question:** Reconstruct the minimal action sequence that led from seeing **“{START_MARKER}”** to seeing **“{END_MARKER}”** within {MAX_SPAN_MIN} minutes. List actions with times.  
**Requires:** text markers + HID + windowing.  
**Answer type:** `list`.

### Q32 — Search term + first result
**Question:** Find the most recent in-app/web search where a term was entered and submitted. What was the term, and what was the top visible result title?  
**Requires:** HID typing + UIA search field + text after submit.  
**Answer type:** `object`.

### Q33 — Scroll distance + UI scroll position delta
**Question:** For a verified scrolling session lasting ≥ {SPAN_SEC}s, what was the total scroll wheel delta and the net scroll position change of the target scroll container?  
**Requires:** HID scroll + UIA scroll position.  
**Answer type:** `object`.

### Q34 — Copy→paste sequence (no clipboard content)
**Question:** Did we perform a copy→paste sequence (Ctrl/Cmd+C then Ctrl/Cmd+V) within {SPAN_MIN} minutes? If yes, when and what was the paste target field/app?  
**Requires:** HID key combos + UIA focus at paste time.  
**Answer type:** `object` or `NOT_FOUND`.

### Q35 — New tab/window via shortcut
**Question:** Identify the most recent time we opened a new tab or window via keyboard shortcut (Ctrl/Cmd+T or Ctrl/Cmd+N). What was the resulting window title/URL (if any) and when?  
**Requires:** HID shortcut + UIA/window/url.  
**Answer type:** `object`.

---

### Q36 — Hover-triggered tooltip
**Question:** Find a tooltip that appeared after a hover (mouse move, no click). What was its text and when did it appear/disappear?  
**Requires:** HID mouse move + tooltip UIA role or text transient.  
**Answer type:** `object` or `NOT_FOUND`.

### Q37 — Context menu via right-click
**Question:** Find the most recent context menu opened via right-click. What was the menu title (if any) and which item was selected?  
**Requires:** HID right-click + UIA menu items + subsequent click.  
**Answer type:** `object` or `NOT_FOUND`.

### Q38 — UIA vs rendered text discrepancy
**Question:** Identify an element where UIA name/value disagreed with rendered text on screen (same bbox region). What were the two strings and when?  
**Requires:** UIA + screenshot text alignment.  
**Answer type:** `object`.

### Q39 — Vector similarity across time
**Question:** Using the temporal vector store, find a pair of screens in the last **{DUR}** that are highly similar (same semantic content) but occurred at different times. What are the two times, and what changed between them?  
**Requires:** vector similarity + diff summarization.  
**Answer type:** `object`.

### Q40 — Leave-and-return to same state
**Question:** Identify the most recent time we left a screen state (same app+window title+key markers) and later returned to it. What were leave time, return time, and time away?  
**Requires:** state fingerprinting + temporal reasoning.  
**Answer type:** `object`.

---

## Codex CLI: exact commands + prompts

All commands below use `codex exec` (non-interactive mode). Codex CLI supports attaching files/images and writing the final message to a file via `--output-last-message` and validating output via `--output-schema`. See official docs for flags and subcommand behavior.  
(References: `codex exec`, global flag placement, `--image`, `--sandbox`, `--ask-for-approval`, `--output-last-message`, `--output-schema`.)

### 0) Pre-req: create the output schema file (copy/paste)
Create a file named `temporal_qa_40.schema.json` with the content below:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Temporal Screenshot QA Suite (40)",
  "type": "object",
  "required": ["suite_id", "timezone", "items"],
  "properties": {
    "suite_id": {"type": "string"},
    "timezone": {"type": "string"},
    "source": {
      "type": "object",
      "properties": {
        "sqlite_path": {"type": "string"},
        "vector_store": {"type": "string"}
      },
      "required": ["sqlite_path", "vector_store"]
    },
    "items": {
      "type": "array",
      "minItems": 40,
      "maxItems": 40,
      "items": {
        "type": "object",
        "required": ["id", "question", "expected_markdown", "expected_json"],
        "properties": {
          "id": {"type": "string"},
          "question": {"type": "string"},
          "expected_markdown": {"type": "string"},
          "expected_json": {
            "type": "object",
            "required": ["status", "question_id", "time_window", "answer", "evidence"],
            "properties": {
              "status": {"type": "string", "enum": ["OK", "NOT_FOUND", "NEEDS_CLARIFICATION"]},
              "question_id": {"type": "string"},
              "time_window": {
                "type": "object",
                "required": ["start", "end", "timezone", "source"],
                "properties": {
                  "start": {"type": "string"},
                  "end": {"type": "string"},
                  "timezone": {"type": "string"},
                  "source": {"type": "string"}
                }
              },
              "answer": {
                "type": "object",
                "required": ["type", "value"],
                "properties": {
                  "type": {"type": "string"},
                  "value": {}
                }
              },
              "evidence": {
                "type": "object",
                "required": ["frames"],
                "properties": {
                  "frames": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                      "type": "object",
                      "required": ["frame_id", "screenshot_time"],
                      "properties": {
                        "frame_id": {"type": "string"},
                        "screenshot_time": {"type": "string"},
                        "app": {"type": "string"},
                        "window_title": {"type": "string"},
                        "screen_bbox": {"type": "object"},
                        "text_spans": {"type": "array"},
                        "uia_refs": {"type": "array"},
                        "hid_refs": {"type": "array"}
                      }
                    }
                  },
                  "joins": {"type": "array"}
                }
              },
              "notes": {"type": "string"}
            }
          }
        }
      }
    }
  }
}
```

### 1) One-shot generation run (produces a verified 40-item suite)
Copy/paste **exactly** the following command (edit only env vars / paths if needed):

```bash
# Optional but recommended: provide explicit store locations.
# export SCREEN_SQLITE_PATH="/absolute/path/to/your.sqlite"
# export TEMPORAL_VECTOR_STORE="your-vector-store-identifier-or-url"

codex exec   --sandbox read-only   --ask-for-approval never   --skip-git-repo-check   --output-schema ./temporal_qa_40.schema.json   --output-last-message ./temporal_qa_40.json   - <<'PROMPT'
You are generating an evaluation set for a temporal screenshot+UIA+HID system.
Hard requirements:
- Do NOT guess. Only output answers you can verify from the available processed stores.
- Use screenshot_time (the timestamp rendered on-screen) as the authoritative time.
- Output must be valid JSON matching temporal_qa_40.schema.json.
- Produce exactly 40 items (Q01..Q40). If an archetype cannot be instantiated, widen your search window (older history) until it can; if truly impossible, replace with a closely related archetype that still tests the same modality and explain in expected_json.notes.
- Never output top-k candidate answers. If uncertain, mark NOT_FOUND or NEEDS_CLARIFICATION, but your goal is to choose parameters so status=OK for all 40.

Task:
1) Locate the SQLite metadata store and vector store.
   - Prefer env vars SCREEN_SQLITE_PATH and TEMPORAL_VECTOR_STORE if set.
   - Otherwise search the workspace for likely sqlite/db files and inspect schema to find tables covering frames/screenshot_time, UIA, HID, and any embedding/vector references.
2) Build a small in-memory index over time:
   - frames with screenshot_time, app, window_title, url/text (if present)
   - UIA snapshots: focused element changes, top-level windows, scroll containers, dialogs
   - HID events: clicks, keypresses, scroll, mouse moves
3) For each archetype Q01..Q40 (see this MD file), choose concrete parameters (DUR, TS, TEXT_SNIPPET, APP, etc) such that:
   - The question is answerable (status OK).
   - The answer is supported by specific evidence (frame_id + screenshot_time at minimum).
4) Compute ground truth answers deterministically from the stores (SQLite + vector store).
5) Emit JSON:
{
  "suite_id": "...",
  "timezone": "America/Denver",
  "source": {"sqlite_path":"...", "vector_store":"..."},
  "items": [ ... 40 objects ... ]
}
Where each item has:
- id: "Q01" .. "Q40"
- question: fully instantiated natural language question
- expected_json: the machine-parseable answer object (status OK) with evidence pointers
- expected_markdown: a short markdown answer that embeds the same JSON in a ```json code block (exactly one).
PROMPT
```

### 2) If Codex asks for clarification
Re-run #1 after you set the env vars (example):

```bash
export SCREEN_SQLITE_PATH="/absolute/path/to/frames.sqlite"
export TEMPORAL_VECTOR_STORE="qdrant://localhost:6333/your_collection"  # example id string only

codex exec --sandbox read-only --ask-for-approval never --skip-git-repo-check   --output-schema ./temporal_qa_40.schema.json   --output-last-message ./temporal_qa_40.json   - "Repeat the generation task exactly as before, now using the provided store locations."
```

---

## Notes for scoring / regression gating
- Parse the JSON block from your pipeline’s answer and compare `status`, `answer.value`, and required evidence fields.
- Treat any missing evidence, mismatched time semantics, or speculative language as a failure.
- Prefer strict deterministic comparisons for timestamps and counts; normalize timezone consistently.

