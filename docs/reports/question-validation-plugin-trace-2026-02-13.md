# Question Validation + Plugin Path Trace (Q/H)

- Generated: `2026-02-13T21:54:37.845896Z`
- Artifact: `artifacts/advanced10/advanced20_20260213T032827Z_rerun1.json`
- Run report: `artifacts/single_image_runs/single_20260213T032827Z/report.json`
- Evaluated summary: total=10 passed=5 failed=5

## Confidence Rubric
- `high` (>=0.80): strict-evaluated pass or strongly supported non-strict answer with multiple providers
- `medium` (0.50-0.79): non-strict `ok` answer with some provider support
- `low` (<0.50): strict-evaluated fail or `no_evidence` / indeterminate outputs
- Note: `Q1..Q10` are non-strict in this artifact (`expected_eval.evaluated=false`), so confidence there is heuristic.

## Question Results (All Q and H)
| ID | Strict Evaluated | Strict Passed | Answer State | Confidence | Label | Winner | Providers In Path |
| --- | ---: | ---: | --- | ---: | --- | --- | ---: |
| Q1 | False | None | ok | 0.50 | medium | classic | 1 |
| Q2 | False | None | ok | 0.50 | medium | classic | 1 |
| Q3 | False | None | no_evidence | 0.18 | low | classic | 0 |
| Q4 | False | None | ok | 0.50 | medium | classic | 1 |
| Q5 | False | None | ok | 0.50 | medium | classic | 1 |
| Q6 | False | None | ok | 0.50 | medium | classic | 1 |
| Q7 | False | None | ok | 0.50 | medium | classic | 1 |
| Q8 | False | None | ok | 0.50 | medium | classic | 1 |
| Q9 | False | None | ok | 0.50 | medium | classic | 1 |
| Q10 | False | None | ok | 0.50 | medium | classic | 1 |
| H1 | True | False | ok | 0.24 | low | classic | 1 |
| H2 | True | False | no_evidence | 0.16 | low | classic | 0 |
| H3 | True | False | ok | 0.24 | low | classic | 1 |
| H4 | True | True | ok | 0.93 | high | classic | 1 |
| H5 | True | True | no_evidence | 0.86 | high | classic | 0 |
| H6 | True | True | no_evidence | 0.86 | high | classic | 0 |
| H7 | True | True | ok | 0.93 | high | classic | 1 |
| H8 | True | True | no_evidence | 0.86 | high | classic | 0 |
| H9 | True | False | no_evidence | 0.16 | low | classic | 0 |
| H10 | True | False | no_evidence | 0.16 | low | classic | 0 |

## Plugin Execution + Answer Path
| Plugin ID | Load Status | In Any Answer Path | Answer Count | Answer IDs | Avg Confidence |
| --- | --- | --- | ---: | --- | ---: |
| builtin.anchor.basic | loaded | False | 0 | - | - |
| builtin.answer.basic | loaded | False | 0 | - | - |
| builtin.backpressure.basic | loaded | False | 0 | - | - |
| builtin.citation.basic | loaded | False | 0 | - | - |
| builtin.devtools.ast_ir | loaded | False | 0 | - | - |
| builtin.devtools.diffusion | loaded | False | 0 | - | - |
| builtin.egress.gateway | loaded | False | 0 | - | - |
| builtin.embedder.basic | loaded | False | 0 | - | - |
| builtin.journal.basic | loaded | False | 0 | - | - |
| builtin.ledger.basic | loaded | False | 0 | - | - |
| builtin.observability.basic | loaded | False | 0 | - | - |
| builtin.ocr.basic | loaded | False | 0 | - | - |
| builtin.privacy.egress_sanitizer | loaded | False | 0 | - | - |
| builtin.processing.sst.pipeline | loaded | True | 13 | Q1, Q2, Q4, Q5, Q6, Q7, Q8, Q9, Q10, H1, H3, H4, H7 | 0.53 |
| builtin.processing.sst.ui_vlm | loaded | False | 0 | - | - |
| builtin.prompt.bundle.default | loaded | False | 0 | - | - |
| builtin.reranker.basic | loaded | False | 0 | - | - |
| builtin.research.default | loaded | False | 0 | - | - |
| builtin.retrieval.basic | loaded | False | 0 | - | - |
| builtin.storage.sqlcipher | loaded | False | 0 | - | - |
| builtin.time.advanced | loaded | False | 0 | - | - |
| builtin.vlm.vllm_localhost | loaded | False | 0 | - | - |
| builtin.observation.graph | failed | False | 0 | - | - |

## Per-Question Plugin Path + Confidence
### Q1
- Question: Enumerate every distinct top-level window visible in the screenshot. For each window: app/product name, host-vs-VDI context, and whether it is fully visible or partially occluded. Return the list in front-to-back z-order.
- Answer state: `ok`
- Strict evaluated: `False` | strict passed: `None`
- Confidence: `0.50` (medium)
- Plugins in answer path:
  - `builtin.processing.sst.pipeline` | contribution_bp=10000 | claim_count=3 | citation_count=3

### Q2
- Question: Which window has keyboard/input focus? Provide 2 pieces of visual evidence (e.g., highlighted title bar, selected row, caret) and include the exact highlighted text for each evidence item.
- Answer state: `ok`
- Strict evaluated: `False` | strict passed: `None`
- Confidence: `0.50` (medium)
- Plugins in answer path:
  - `builtin.processing.sst.pipeline` | contribution_bp=10000 | claim_count=3 | citation_count=3

### Q3
- Question: In the VDI Outlook reading pane showing a task/incident email: extract (a) email subject, (b) sender display name, (c) sender email domain only (do not return the full address), and (d) the labels of the primary action buttons in the embedded task card.
- Answer state: `no_evidence`
- Strict evaluated: `False` | strict passed: `None`
- Confidence: `0.18` (low)
- Plugins in answer path: none

### Q4
- Question: From that same task/incident view, extract the complete 'Record Activity' timeline: each entry’s timestamp (including timezone if shown) and its associated text, in the same top-to-bottom order displayed.
- Answer state: `ok`
- Strict evaluated: `False` | strict passed: `None`
- Confidence: `0.50` (medium)
- Plugins in answer path:
  - `builtin.processing.sst.pipeline` | contribution_bp=10000 | claim_count=1 | citation_count=1

### Q5
- Question: From the 'Details' section in the same VDI task/incident view, extract all visible field labels and their values as key-value pairs (include fields that are present-but-empty as empty strings). Preserve the on-screen ordering.
- Answer state: `ok`
- Strict evaluated: `False` | strict passed: `None`
- Confidence: `0.50` (medium)
- Plugins in answer path:
  - `builtin.processing.sst.pipeline` | contribution_bp=10000 | claim_count=1 | citation_count=1

### Q6
- Question: In the VDI right-side calendar/schedule pane: extract the displayed month+year, the currently selected date, and then list the first 5 visible scheduled items (top-to-bottom) with start time + title.
- Answer state: `ok`
- Strict evaluated: `False` | strict passed: `None`
- Confidence: `0.50` (medium)
- Plugins in answer path:
  - `builtin.processing.sst.pipeline` | contribution_bp=10000 | claim_count=3 | citation_count=3

### Q7
- Question: In the Slack DM window: transcribe the last two visible messages as (sender, timestamp, exact text). Also describe what the embedded image thumbnail depicts in 1 sentence (do not infer beyond what is visible).
- Answer state: `ok`
- Strict evaluated: `False` | strict passed: `None`
- Confidence: `0.50` (medium)
- Plugins in answer path:
  - `builtin.processing.sst.pipeline` | contribution_bp=10000 | claim_count=3 | citation_count=3

### Q8
- Question: In the upper-left dev note/terminal-summary window: extract the full 'What changed' section (each line), the 'Files:' list, and the exact 'Tests:' command shown.
- Answer state: `ok`
- Strict evaluated: `False` | strict passed: `None`
- Confidence: `0.50` (medium)
- Plugins in answer path:
  - `builtin.processing.sst.pipeline` | contribution_bp=10000 | claim_count=3 | citation_count=3

### Q9
- Question: In the console/log window that contains both red and green text: extract all visible lines and classify each line by its rendered color (red/green/other). Return counts per color and the full text of every red line.
- Answer state: `ok`
- Strict evaluated: `False` | strict passed: `None`
- Confidence: `0.50` (medium)
- Plugins in answer path:
  - `builtin.processing.sst.pipeline` | contribution_bp=10000 | claim_count=3 | citation_count=3

### Q10
- Question: For each visible browser window in the screenshot: extract the active tab title, the address-bar hostname (hostname only), and the count of visible tabs in that window’s tab strip.
- Answer state: `ok`
- Strict evaluated: `False` | strict passed: `None`
- Confidence: `0.50` (medium)
- Plugins in answer path:
  - `builtin.processing.sst.pipeline` | contribution_bp=10000 | claim_count=3 | citation_count=3

### H1
- Question: Compute the incident’s time-to-assignment in minutes by using (a) the "Opened at" timestamp in Details and (b) the "State changed" update timestamp in Record Activity. Return both timestamps and the elapsed minutes.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `False`
- Confidence: `0.24` (low)
- Plugins in answer path:
  - `builtin.processing.sst.pipeline` | contribution_bp=10000 | claim_count=2 | citation_count=2

### H2
- Question: From the change summary, take the k preset values and compute their sum. Then verify whether each preset is valid under the documented server-side clamp range. Return sum, clamp_range, and a per-preset validity list.
- Answer state: `no_evidence`
- Strict evaluated: `True` | strict passed: `False`
- Confidence: `0.16` (low)
- Plugins in answer path: none

### H3
- Question: Cross-window reasoning: Slack mentions running a "new converter" at two sizes. Identify those two numbers from Slack, then infer the best-matching parameter in the dev note (k vs dimension). Finally, produce two example GET query strings using k=64 and those two values as the inferred parameter.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `False`
- Confidence: `0.24` (low)
- Plugins in answer path:
  - `builtin.processing.sst.pipeline` | contribution_bp=10000 | claim_count=3 | citation_count=3

### H4
- Question: Code reasoning: Summarize the endpoint-selection + retry logic shown in the colored script into pseudocode with explicit conditionals. Include (a) the condition that switches to $saltEndpoint and (b) the condition that triggers a retry after Invoke-Expression.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.processing.sst.pipeline` | contribution_bp=10000 | claim_count=3 | citation_count=3

### H5
- Question: Find one correctness bug/inconsistency in the script’s final success log line and provide the exact corrected line. (Hint: which variable is referenced in the message vs which endpoint may actually have succeeded?)
- Answer state: `no_evidence`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.86` (high)
- Plugins in answer path: none

### H6
- Question: Data cleaning (Excel-like): In Details, the field label "Cell Phone Number (Y / N)? Y / N" has value "NA". Propose a normalized schema and a deterministic transform for this specific record (what values go into the normalized fields).
- Answer state: `no_evidence`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.86` (high)
- Plugins in answer path: none

### H7
- Question: Reasoning over the worklog: Count how many completed checkboxes ([x]) are visible in the bottom-left notes window, and name the currently running action shown directly underneath the checklist.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.processing.sst.pipeline` | contribution_bp=10000 | claim_count=2 | citation_count=2

### H8
- Question: Vision + UI semantics (not OCR-only): In the Outlook message list (Today section), count how many rows show the blue unread indicator bar. Return the count only for Today (not Thursday/Last week).
- Answer state: `no_evidence`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.86` (high)
- Plugins in answer path: none

### H9
- Question: Vision classification: In the SiriusXM carousel row at the bottom center, classify the 6 fully visible tiles into {talk/podcast, NCAA team, NFL event}. Return counts per class and list the titles/entities you used.
- Answer state: `no_evidence`
- Strict evaluated: `True` | strict passed: `False`
- Confidence: `0.16` (low)
- Plugins in answer path: none

### H10
- Question: Action grounding: Provide screenshot-normalized bounding boxes (x1,y1,x2,y2 in [0,1]) for the two task-card buttons in Outlook: COMPLETE and VIEW DETAILS. Coordinates are relative to the full screenshot (2048x575).
- Answer state: `no_evidence`
- Strict evaluated: `True` | strict passed: `False`
- Confidence: `0.16` (low)
- Plugins in answer path: none
