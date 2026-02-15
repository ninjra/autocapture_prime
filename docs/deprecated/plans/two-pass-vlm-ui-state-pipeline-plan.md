# Plan: Two-Pass VLM UI-State Pipeline + Q1-Q10 Golden Contract

**Generated**: 2026-02-11
**Estimated Complexity**: High

## Overview
Implement a deterministic, citation-first, two-pass visual processing pipeline for `screenshot.png (7680x2160)` and hard-bind it to a measured Q1-Q10 golden contract:
1. `thumbnail_pass` proposes candidate UI regions quickly at reduced resolution.
2. `hi_res_pass` parses each ROI from original-resolution pixels into structured JSON with VLM-primary extraction.
3. `merge` reconciles ROIs into one canonical `UI state` JSON used by retrieval and natural-language query answering.

This plan explicitly operationalizes the 4 pillars:
- Performance: bounded pass-1 + selective pass-2 + cached transforms + stage budgets.
- Accuracy: high-resolution ROI parsing + layout-aware merge + evidence-linked answers.
- Security: localhost-only inference endpoints, fail-closed parser/permissions, append-only audit trail.
- Citeability: every claim references extracted evidence spans, model/version/prompt hash, and immutable provenance.

## Prerequisites
- Existing SST plugin host and stage hook system (`processing.stage.hooks`).
- Existing `vision.extractor`, query trace, journal, ledger, and metadata storage path.
- Localhost model endpoints available for:
  - Pass 1: `Qwen3-VL-8B-FP8` or `InternVL3.5-8B-Flash`.
  - Pass 2: `MAI-UI-8B` (or `UI-Venus-1.5-8B` only if license cleared).
- Existing deterministic test harness and plugin lock workflow.
- Existing golden-case framework for query correctness checks.

## Authoritative Input Contract (Provided Dataset)
This plan treats the following as the authoritative contract for the target screenshot run:

### Session IDs
- `THREAD`: `autocapture_screenshot_2026-02-02_113519`
- `CHAT_ID`: `UNKNOWN`

### Input
- `screenshot.png` at `7680x2160`.

### Determinism Rule
- Values are asserted only if directly visible and legible (`MEASURED`).
- If not provable from visual evidence, return `NO EVIDENCE` (never hallucinate).
- Shipping gate: `ANY_REGRESS => DO_NOT_SHIP`.

## Sprint 1: Contractization Of Q1-Q10 Truth Pack
**Goal**: Convert the supplied measured answers into immutable golden fixtures and machine-checkable acceptance criteria.
**Demo/Validation**:
- Golden fixtures load without schema drift.
- CI can fail on any contract mismatch.

### Task 1.1: Add Structured Golden Contract Artifact
- **Location**: `tests/fixtures/query_golden/thread_autocapture_screenshot_2026-02-02_113519/contract.json` (new)
- **Description**: Encode Q1-Q10 expected outputs, per-field evidentiary status (`MEASURED` vs `NO EVIDENCE`), and strict ordering requirements.
- **Complexity**: 6
- **Dependencies**: none
- **Acceptance Criteria**:
  - File stores session IDs, timestamp, key claims, Q1-Q10 expected records, and regression gates.
  - Includes `determinism_verified=true` and `do_not_ship_on_regress=true`.
- **Validation**:
  - JSON schema + fixture unit test.

### Task 1.2: Add Golden Question Spec Manifest
- **Location**: `tests/fixtures/query_golden/thread_autocapture_screenshot_2026-02-02_113519/questions.json` (new)
- **Description**: Persist each question with `id`, risk/improvement intent, enforcement location, and regression detection logic.
- **Complexity**: 5
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Q1-Q10 are present with exact prompt text and expected shape.
  - All gates are explicit and deterministic.
- **Validation**:
  - Manifest schema and round-trip loader test.

### Task 1.3: Add NO-EVIDENCE Enforcement Primitive
- **Location**: `autocapture_nx/query/answer_contract.py` (new), `autocapture_nx/kernel/query.py`
- **Description**: Introduce a strict answer-state primitive requiring `NO EVIDENCE` on unproven claims and preventing implicit best-guess fallback.
- **Complexity**: 7
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Non-overlapping z-order claims are gated to `NO EVIDENCE`.
  - Icon-only tab strips can return `NO EVIDENCE` for title/count.
- **Validation**:
  - Unit tests for negative evidence cases.

## Sprint 2: Two-Pass VLM Extraction Pipeline
**Goal**: Ensure answers derive from VLM-first structured extraction, with OCR only as secondary context.
**Demo/Validation**:
- Pipeline emits pass-1 ROI proposals, pass-2 structured parses, and merged `derived.ui.state`.
- Provenance shows `vlm_primary=true`.

### Task 2.1: Implement Thumbnail ROI Proposer Plugin
- **Location**: `plugins/builtin/sst_roi_thumbnail_proposer/` (new)
- **Description**: Downscale to ~`1920x540`, run pass-1 VLM, emit normalized candidate ROIs (window/tab-strip/url-bar/terminal/card/calendar/chat/etc.).
- **Complexity**: 8
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Output schema includes model ID, prompt hash, score, and coordinates.
  - Runtime cap and ROI cap are enforced.
- **Validation**:
  - Plugin unit tests and bounded-latency tests.

### Task 2.2: Implement Hi-Res ROI Parser Plugin
- **Location**: `plugins/builtin/sst_roi_hires_parser/` (new)
- **Description**: Crop each ROI from original `7680x2160`, optional tile, run `MAI-UI-8B` (or licensed alternative), emit structured JSON for each ROI.
- **Complexity**: 9
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - ROI-local and global coordinates are preserved.
  - Output includes extraction confidence and structured elements.
- **Validation**:
  - Deterministic parse tests with fixed decoding params.

### Task 2.3: OCR-As-Context (Never Primary)
- **Location**: `plugins/builtin/sst_roi_hires_parser/context_ocr.py` (new)
- **Description**: Attach OCR text as context into pass-2 prompts while preserving VLM as authoritative source.
- **Complexity**: 6
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Metadata records source role (`vlm_primary`, `ocr_context`).
  - Query arbitration disallows OCR-only final claims where VLM evidence exists.
- **Validation**:
  - Provenance tests asserting source role ordering.

## Sprint 3: Canonical Merge + UI State Contract
**Goal**: Reconcile all extracted regions into one deterministic UI-state object suitable for metadata-only querying.
**Demo/Validation**:
- Stable `derived.ui.state` JSON across repeated runs.
- Deduplication, ordering, and boundary reconciliation are deterministic.

### Task 3.1: Implement Merge Plugin
- **Location**: `plugins/builtin/sst_ui_state_merge/` (new)
- **Description**: Convert normalized coordinates to global pixels, dedupe overlaps, reconcile boundaries, assign deterministic IDs.
- **Complexity**: 9
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Stable ID assignment and stable ordering.
  - Conflict resolution emits trace reason codes.
- **Validation**:
  - Golden snapshot tests for merged output.

### Task 3.2: Persist Canonical UI State Into Metadata
- **Location**: `autocapture_nx/processing/sst/persist.py`, `plugins/builtin/storage_sqlcipher/plugin.py` or replacement storage plugin path
- **Description**: Store `derived.ui.state` and evidence links such that queries no longer depend on source image existence.
- **Complexity**: 7
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Query retrieval succeeds after source image deletion.
  - All answer claims can cite entity IDs and evidence spans.
- **Validation**:
  - Integration test with metadata-only query path.

## Sprint 4: Query Reasoning + Plugin Attribution
**Goal**: Route Q1-Q10 through canonical state + reasoning chain, with measurable per-plugin contributions.
**Demo/Validation**:
- Query returns structured, human-checkable outputs.
- Metrics include correctness, latency, and handoff breakdown by plugin sequence.

### Task 4.1: Add Structured Answer Formatter
- **Location**: `autocapture_nx/kernel/query_format.py` (new), `autocapture_nx/kernel/query.py`
- **Description**: Output one-sentence or bullet breakdowns with explicit evidence snippets and `NO EVIDENCE` fields.
- **Complexity**: 7
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Supports compact outputs like `inboxes: 4 -> gmail1, gmail2, outlook-vdi, outlook-host-taskbar`.
  - No raw OCR dump as top-level answer content.
- **Validation**:
  - Formatting tests with strict expected strings.

### Task 4.2: Add End-To-End Workflow Attribution Graph
- **Location**: `tools/export_run_workflow_tree.py`, `docs/reports/` (artifact output)
- **Description**: Export plugin DAG/tree for each query: stage timings, evidence handoffs, and contribution weights.
- **Complexity**: 8
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Tree includes pass-1, pass-2, merge, retrieval, reasoning, answer formatting.
  - Deterministic node/edge ordering across runs.
- **Validation**:
  - Snapshot tests for graph JSON/Markdown export.

### Task 4.3: Add Correctness + Feedback Truth Loop
- **Location**: `autocapture_nx/metrics/query_feedback.py` (new), `tools/query_feedback_cli.py` (new)
- **Description**: Log expected answer, returned answer, user verdict, delta reason, and remediation linkage without any auto-pass behavior.
- **Complexity**: 8
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - No path can mark failed answers as passed.
  - Each failure links to plugin/stage-level suspected root cause.
- **Validation**:
  - Tests asserting fail cases remain failed unless extraction actually fixes them.

## Sprint 5: Q1-Q10 Enforcement Layers
**Goal**: Implement generic extractors/reasoners for each question class with no tactical shortcuts.
**Demo/Validation**:
- Run full Q1-Q10 set; all outputs match contract or explicitly `NO EVIDENCE` where defined.

### Task 5.1: Window Graph + Z-Order/Occlusion Engine (Q1)
- **Location**: `plugins/builtin/ui_window_graph/` (new)
- **Description**: Build top-level window graph with host-vs-VDI context and provable front/back edges only where overlap exists.
- **Complexity**: 8
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Emits ordered list plus non-inferable relations as `NO EVIDENCE`.
- **Validation**:
  - Golden diff on name/context/order/occlusion.

### Task 5.2: Focus Inference + Evidence Linker (Q2)
- **Location**: `plugins/builtin/ui_focus_inference/` (new)
- **Description**: Detect active/focused context from selection/caret/highlight signals and attach at least 2 evidence items.
- **Complexity**: 7
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Includes exact highlighted text for each evidence item.
- **Validation**:
  - Baseline check for `focused_window_id` + evidence list.

### Task 5.3: Structured Pane Extractors (Q3-Q6, Q8, Q10)
- **Location**: `plugins/builtin/ui_structured_extractors/` (new)
- **Description**: Generic parsers for email headers/cards, activity timelines, detail key-values, calendars, dev-note sections, browser chrome tuples.
- **Complexity**: 9
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Domain-only policy for email domain extraction.
  - Ordered row/group extraction for timeline/KV/calendar outputs.
- **Validation**:
  - Per-question golden assertions on field-level tuples.

### Task 5.4: Chat + Thumbnail + Color-Aware Console Parsers (Q7, Q9)
- **Location**: `plugins/builtin/ui_chat_parser/` (new), `plugins/builtin/ui_console_color_parser/` (new)
- **Description**: Parse sender/timestamp/text in chat windows and classify console lines by rendered color with counts and extracted red-line text.
- **Complexity**: 8
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Chat extraction aligns message/sender/timestamp deterministically.
  - Console parser outputs exact counts and per-line text by color.
- **Validation**:
  - Golden list and count checks.

## Sprint 6: Hardening, Policy, And Soak Readiness
**Goal**: Keep system stable for long-running, disability-critical use.
**Demo/Validation**:
- Soak passes with stable outputs and policy compliance.

### Task 6.1: Runtime Budget And Foreground Gating Enforcement
- **Location**: scheduler/governor plugins + processing orchestration config
- **Description**: Enforce ACTIVE-mode gating and IDLE-mode budgeted processing for heavy visual passes.
- **Complexity**: 7
- **Dependencies**: Sprint 2+
- **Acceptance Criteria**:
  - Non-capture processing pauses correctly during ACTIVE user state.
- **Validation**:
  - Budget tests and long-run stability checks.

### Task 6.2: Security + Audit For New Plugins
- **Location**: permission manifests, journal/ledger emitters, policygate
- **Description**: Add explicit permission manifests and append-only audit events for every new privileged action.
- **Complexity**: 6
- **Dependencies**: Sprint 4+
- **Acceptance Criteria**:
  - All model calls and storage writes are auditable and fail-closed.
- **Validation**:
  - Security regression + audit integrity tests.

## Testing Strategy
- Unit:
  - Schema validation for ROI pass outputs and canonical UI-state.
  - Coordinate transforms, overlap dedupe, and deterministic ID generation.
  - NO-EVIDENCE enforcement and anti-hallucination checks.
- Integration:
  - Single-image ingest to query path through full plugin DAG.
  - Metadata-only query mode (image removed) for Q1-Q10.
  - Localhost-only model endpoint policy checks.
- Golden:
  - Q1-Q10 exact output contract checks, ordering checks, and field constraints.
  - Per-stage timing and plugin-contribution snapshots.
- Soak:
  - Repeated query runs with correctness variance checks and resource budgets.

## Potential Risks & Gotchas
- VLM JSON drift:
  - Mitigation: strict schema parser + retry with deterministic template + fail-closed invalid records.
- ROI misses for small UI regions:
  - Mitigation: class coverage requirements + adaptive ROI expansion fallback.
- OCR contamination of final answers:
  - Mitigation: source-role constraints and answer arbitration requiring VLM-anchored evidence for primary claims.
- Misleading z-order in non-overlap windows:
  - Mitigation: explicit non-overlap rule; emit `NO EVIDENCE`.
- Tab-strip ambiguity on icon-only tabs:
  - Mitigation: return `NO EVIDENCE` unless zoom/resolve confidence is above threshold.
- Feedback-system integrity risks:
  - Mitigation: hard prohibition on auto-pass or expected-answer override behavior.

## Rollback Plan
- Feature flags:
  - Independently disable `thumbnail_pass`, `hi_res_pass`, `merge`, or question-specific extractors.
- Data safety:
  - Append-only records remain; new record types are additive.
- Deployment rollback:
  - Revert plugin enablement/config + plugin lock updates in a single rollback commit.

## Review Notes
- `request_user_input` is unavailable in current collaboration mode; no blocking ambiguities remained, so assumptions were minimized and encoded as explicit contract rules.
- Subagent review is unavailable in this runtime; compensated with deterministic gate design, explicit gotcha analysis, and strict `DO_NOT_SHIP` regress criteria.

## Appendix A: Q1-Q10 Golden Baseline (Provided Values)
These are the provided measured target outcomes the implementation must satisfy.

### A.1 Session
- `THREAD=autocapture_screenshot_2026-02-02_113519`
- `CHAT_ID=UNKNOWN`
- `TS=2026-02-11T22:04:58Z`

### A.2 Q1 Window Enumeration + Z-Order
- Distinct windows include:
  - `statistic_harness` browser (host, fully visible)
  - `autocapture_demo` browser (host, partially occluded)
  - `SiriusXM` browser (host, partially occluded)
  - `Slack DM` window (host, fully visible)
  - `ChatGPT` browser (host, fully visible)
  - `console/log` window (host, fully visible)
  - `Remote Desktop Web Client` window (host containing VDI, fully visible)
  - far-right white background sliver (host, app unknown, very small visible)
- Proven edges:
  - Slack above SiriusXM
  - ChatGPT above SiriusXM
  - Console/log above SiriusXM
  - Console/log above bottom-left browser
  - VDI above far-right white background window
- Full total order for non-overlapping windows: `NO EVIDENCE`.

### A.3 Q2 Focused Window
- Best-supported focused context: VDI Outlook view.
- Evidence includes selected email row + reading pane consistency and visible action card.
- Highlighted subject:
  - `Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476`

### A.4 Q3 Email/Card Extraction
- Subject:
  - `Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476`
- Sender display:
  - `Permian Resources Service Desk`
- Sender domain only:
  - `permian.xyz.com`
- Primary action buttons:
  - `COMPLETE`, `VIEW DETAILS`

### A.5 Q4 Record Activity Timeline
- Entry 1:
  - `Your record was updated on Feb 02, 2026 - 12:08pm CST`
  - `State changed from New to Assigned`
- Entry 2:
  - `Mary Mata created the incident on Feb 02, 2026 - 12:08pm CST`
  - `New Onboarding Request Contractor - Ricardo Lopez - Feb 02, 2026 (53370)`

### A.6 Q5 Details Key-Value Extraction (ordered)
- Left column top-to-bottom:
  - `Service requestor: Norry Mata`
  - `Opened at: Feb 02, 2026 - 12:06pm CST`
  - `Assigned to: MAC-TIME-ST88`
  - `Category: Spry (HPT Owners)`
  - `Priority: Medium`
  - `Site: Office`
  - `Department: Permian Basin Cap., CI`
  - `VIA: Portal`
  - `Area Pro Type: NO EVIDENCE`
- Right column top-to-bottom:
  - `Logical call Name: LOPEZ`
  - `Contractor Support Email: cab3_spend@livestrata.com`
  - `VPI Employee have a preferred first name?: No`
  - `Cell Phone Number (Y / N)? Y / N: NA`
  - `Job Title: V3U / FOG`
  - `Hiring Manager: Nancy Mata`
  - `Location: Carlsbad`
  - `Laptop Needed?: Yes`
  - next field label/value cut off: `NO EVIDENCE`

### A.7 Q6 Calendar/Schedule Extraction
- Month/year:
  - `January 2026`
- Selected date:
  - `2`
- First 5 visible scheduled items:
  1. `Today 3:00 PM - 47353AC - ...` (title truncated, `NO EVIDENCE` for full title)
  2. `Today 7:00 PM - Complete Weekly Quor...`
  3. `Tomorrow 8:30 AM - CC Daily Standup`
  4. `Tomorrow 9:30 AM - HODN Coding`
  5. `Wednesday 8:30 AM - CC Daily Standup`

### A.8 Q7 Slack DM Extraction
- Last two visible messages:
  - `(You, TUESDAY/no time): "For videos, ping you in 5 - 10 mins?"`
  - `(Jennifer Doherty, 9:42 PM): "gwatt"`
- Embedded thumbnail description:
  - small screenshot thumbnail with white dialog/window centered on blue background; fine text not legible.

### A.9 Q8 Dev Note/Terminal Summary Extraction
- What changed:
  - `Vectors UI now shows a "Summary" column derived from payload fields (loginid/type/host/etc)`
  - `Added k preset buttons (32/64/128) and server-side clamp (1-200) to avoid runaway result sizes`
  - `Vectors GET now accepts k and dimensions and pre-fills them.`
- Files:
  - `src/statistic_harness/v4/templates/vectors.html`
  - `src/statistic_harness/v4/server.py`
- Tests:
  - `PYTHONPATH=src /tmp/stat_harness_venv/bin/python -m pytest -q`

### A.10 Q9 Console Color-Aware Extraction
- Expected counts:
  - `red=8`, `green=16`, `other=1`
- Red-line block:
```text
if (-not (Test-Endpoint $endpoint)) {
    $sect = Get-EndpointPart -EndpointValue $endpoint
    $wslIp = Get-WslIp -Distro $distro
    if ($wslIp -and $port) {
        $saltEndpoint = "$($wslIp):$port"
        if (Test-Endpoint $saltEndpoint) {
            Write-Host "Using WSL IP endpoint $saltEndpoint for $projectId" -ForegroundColor Yellow
            $endpoint = $saltEndpoint
```

### A.11 Q10 Browser Chrome Extraction
- `statistic_harness` window:
  - active title `statistic_harness`, hostname `NO EVIDENCE`, visible tab count `1`
- `autocapture_demo` window:
  - active title `autocapture_demo`, hostname `NO EVIDENCE`, visible tab count `2`
- `SiriusXM` window:
  - active title `NO EVIDENCE`, hostname `listen.siriusxm.com`, tab count `NO EVIDENCE`
- `ChatGPT` window:
  - active title `ChatGPT`, hostname `chatgpt.com`, visible tab count `3`
- VDI host browser window:
  - active title `Remote Desktop Web Client`, hostname `outlook.office.com`, visible tab count `1`

### A.12 Key Claims And Ship Gate
- Claims:
  - Outlook subject and timeline values are measured.
  - Details include assignment and contractor support email.
  - Console has 8 red and 16 green lines plus 1 other.
  - Full front-to-back global order is not inferable for non-overlapping windows.
- Gate:
  - `ANY_REGRESS => DO_NOT_SHIP`
  - `DETERMINISM: VERIFIED`

## Appendix B: Recommendation Set To Implement
1. Non-overlap z-order rule:
   - Only assert relative order where overlap exists; otherwise return `NO EVIDENCE`.
2. Icon-only tab strip handling:
   - Return `NO EVIDENCE` for tab title/count when not resolvable.
3. Color-aware console extraction:
   - Segment by hue + line bands before OCR/text parse.
