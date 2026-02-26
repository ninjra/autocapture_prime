# Question Validation + Plugin Path Trace (Q/H)

- Generated: `2026-02-26T16:57:57.913820Z`
- Artifact: `artifacts/advanced10/advanced20_20260226T165750Z.json`
- Run report: `artifacts/single_image_runs/single_20260226T165223Z/report.json`
- Evaluated summary: total=20 passed=20 failed=0
- Overall confidence mean: `0.9300`

## Question Results (All Q and H)
| ID | Strict Evaluated | Strict Passed | Answer State | Confidence | Label | Winner | Providers In Path |
| --- | ---: | ---: | --- | ---: | --- | --- | ---: |
| Q1 | True | True | ok | 0.93 | high | state | 2 |
| Q2 | True | True | ok | 0.93 | high | state | 2 |
| Q3 | True | True | ok | 0.93 | high | state | 2 |
| Q4 | True | True | ok | 0.93 | high | state | 2 |
| Q5 | True | True | ok | 0.93 | high | state | 2 |
| Q6 | True | True | ok | 0.93 | high | state | 2 |
| Q7 | True | True | ok | 0.93 | high | state | 2 |
| Q8 | True | True | ok | 0.93 | high | state | 2 |
| Q9 | True | True | ok | 0.93 | high | state | 2 |
| Q10 | True | True | ok | 0.93 | high | state | 2 |
| H1 | True | True | ok | 0.93 | high | state | 2 |
| H2 | True | True | ok | 0.93 | high | state | 2 |
| H3 | True | True | ok | 0.93 | high | state | 2 |
| H4 | True | True | ok | 0.93 | high | state | 2 |
| H5 | True | True | ok | 0.93 | high | state | 2 |
| H6 | True | True | ok | 0.93 | high | state | 2 |
| H7 | True | True | ok | 0.93 | high | state | 2 |
| H8 | True | True | ok | 0.93 | high | state | 2 |
| H9 | True | True | ok | 0.93 | high | state | 2 |
| H10 | True | True | ok | 0.93 | high | state | 2 |

## Class Summary (Q/H/Other)
| Class | Total | Strict Evaluated | Strict Passed | Strict Failed | Confidence Mean |
| --- | ---: | ---: | ---: | ---: | ---: |
| H | 10 | 10 | 10 | 0 | 0.9300 |
| Q | 10 | 10 | 10 | 0 | 0.9300 |

## Answer State Confusion By Class
### Class H
| Answer State | Count |
| --- | ---: |
| ok | 10 |

### Class Q
| Answer State | Count |
| --- | ---: |
| ok | 10 |


## Plugin Inventory + Effectiveness
| Plugin ID | Status | In Path | Out Path | Strict Pass | Strict Fail | Neutral | Avg Conf | Conf Δ | Mean Est Latency ms | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| builtin.answer.synth_vllm_localhost | loaded | 20 | 0 | 20 | 0 | 0 | 0.9300 | +0.0000 | 0.000 | neutral |
| builtin.observation.graph | loaded | 20 | 0 | 20 | 0 | 0 | 0.9300 | +0.0000 | 0.000 | neutral |
| builtin.anchor.basic | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.answer.basic | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.backpressure.basic | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.citation.basic | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.devtools.ast_ir | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.devtools.diffusion | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.egress.gateway | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.embedder.vllm_localhost | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.index.colbert_hash | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.journal.basic | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.ledger.basic | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.observability.basic | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.ocr.basic | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.ocr.nemotron_torch | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.ocr.rapid | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.privacy.egress_sanitizer | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.processing.sst.pipeline | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.processing.sst.ui_vlm | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.processing.sst.uia_context | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.prompt.bundle.default | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.reranker.basic | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.reranker.colbert_hash | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.retrieval.basic | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.runtime.governor | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.runtime.scheduler | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.screen.answer.v1 | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.screen.index.v1 | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.screen.parse.v1 | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.build.delta | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.build.state | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.compliance.redact | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.extract.chart | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.extract.code | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.extract.spreadsheet | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.extract.table | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.index | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.infer.action | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.layout.assemble | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.match.ids | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.ocr.onnx | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.persist | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.preprocess.normalize | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.preprocess.tile | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.temporal.segment | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.track.cursor | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.sst.ui.parse | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.state.anomaly | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.state.evidence.compiler | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.state.jepa.training | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.state.jepa_like | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.state.policy | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.state.retrieval | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.state.vector.hnsw | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.state.vector.linear | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.state.vector.sqlite_ts | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.state.workflow.miner | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.storage.sqlcipher | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.time.advanced | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |
| builtin.vlm.vllm_localhost | loaded | 0 | 20 | 0 | 0 | 0 | 0.0000 | -0.9300 | 0.000 | remove_or_rewire |

## Per-Question Plugin Path + Confidence
### Q1
- Question: Enumerate every distinct top-level window visible in the screenshot. For each window: app/product name, host-vs-VDI context, and whether it is fully visible or partially occluded. Return the list in front-to-back z-order.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### Q2
- Question: Which window has keyboard/input focus? Provide 2 pieces of visual evidence (e.g., highlighted title bar, selected row, caret) and include the exact highlighted text for each evidence item.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### Q3
- Question: In the VDI Outlook reading pane showing a task/incident email: extract (a) email subject, (b) sender display name, (c) sender email domain only (do not return the full address), and (d) the labels of the primary action buttons in the embedded task card.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### Q4
- Question: From that same task/incident view, extract the complete 'Record Activity' timeline: each entry’s timestamp (including timezone if shown) and its associated text, in the same top-to-bottom order displayed.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### Q5
- Question: From the 'Details' section in the same VDI task/incident view, extract all visible field labels and their values as key-value pairs (include fields that are present-but-empty as empty strings). Preserve the on-screen ordering.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### Q6
- Question: In the VDI right-side calendar/schedule pane: extract the displayed month+year, the currently selected date, and then list the first 5 visible scheduled items (top-to-bottom) with start time + title.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### Q7
- Question: In the Slack DM window: transcribe the last two visible messages as (sender, timestamp, exact text). Also describe what the embedded image thumbnail depicts in 1 sentence (do not infer beyond what is visible).
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### Q8
- Question: In the upper-left dev note/terminal-summary window: extract the full 'What changed' section (each line), the 'Files:' list, and the exact 'Tests:' command shown.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### Q9
- Question: In the console/log window that contains both red and green text: extract all visible lines and classify each line by its rendered color (red/green/other). Return counts per color and the full text of every red line.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### Q10
- Question: For each visible browser window in the screenshot: extract the active tab title, the address-bar hostname (hostname only), and the count of visible tabs in that window’s tab strip.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### H1
- Question: Compute the incident’s time-to-assignment in minutes by using (a) the "Opened at" timestamp in Details and (b) the "State changed" update timestamp in Record Activity. Return both timestamps and the elapsed minutes.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=2 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### H2
- Question: From the change summary, take the k preset values and compute their sum. Then verify whether each preset is valid under the documented server-side clamp range. Return sum, clamp_range, and a per-preset validity list.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### H3
- Question: Cross-window reasoning: Slack mentions running a "new converter" at two sizes. Identify those two numbers from Slack, then infer the best-matching parameter in the dev note (k vs dimension). Finally, produce two example GET query strings using k=64 and those two values as the inferred parameter.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=2 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### H4
- Question: Code reasoning: Summarize the endpoint-selection + retry logic shown in the colored script into pseudocode with explicit conditionals. Include (a) the condition that switches to $saltEndpoint and (b) the condition that triggers a retry after Invoke-Expression.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### H5
- Question: Find one correctness bug/inconsistency in the script’s final success log line and provide the exact corrected line. (Hint: which variable is referenced in the message vs which endpoint may actually have succeeded?)
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### H6
- Question: Data cleaning (Excel-like): In Details, the field label "Cell Phone Number (Y / N)? Y / N" has value "NA". Propose a normalized schema and a deterministic transform for this specific record (what values go into the normalized fields).
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### H7
- Question: Reasoning over the worklog: Count how many completed checkboxes ([x]) are visible in the bottom-left notes window, and name the currently running action shown directly underneath the checklist.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### H8
- Question: Vision + UI semantics (not OCR-only): In the Outlook message list (Today section), count how many rows show the blue unread indicator bar. Return the count only for Today (not Thursday/Last week).
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### H9
- Question: Vision classification: In the SiriusXM carousel row at the bottom center, classify the 6 fully visible tiles into {talk/podcast, NCAA team, NFL event}. Return counts per class and list the titles/entities you used.
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0

### H10
- Question: Action grounding: Provide screenshot-normalized bounding boxes (x1,y1,x2,y2 in [0,1]) for the two task-card buttons in Outlook: COMPLETE and VIEW DETAILS. Coordinates are relative to the full screenshot (2048x575).
- Answer state: `ok`
- Strict evaluated: `True` | strict passed: `True`
- Confidence: `0.93` (high)
- Plugins in answer path:
  - `builtin.observation.graph` | contribution_bp=10000 | claim_count=1 | citation_count=1 | est_latency_ms=0
  - `builtin.answer.synth_vllm_localhost` | contribution_bp=0 | claim_count=0 | citation_count=0 | est_latency_ms=0
