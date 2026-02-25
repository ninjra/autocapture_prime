# Stage1 Minimum Contract

## Purpose
Define the minimum normalized evidence required before a frame is considered Stage1-complete and safe for retention eligibility.

## Scope
- Applies to `record_type=evidence.capture.frame`.
- Evaluated from normalized metadata stores only.
- Query/runtime must not require raw media after this contract is satisfied.

## Required Artifacts Per Frame
1. Frame source row exists and is structurally complete:
   - `record_type=evidence.capture.frame`
   - non-empty `blob_path`
   - non-empty `content_hash`
   - `uia_ref.record_id` and `uia_ref.content_hash`
   - HID linkage via `input_ref.record_id` or `input_batch_ref.record_id`
2. Stage1 completion marker:
   - `record_type=derived.ingest.stage1.complete`
   - `source_record_id=<frame_id>`
   - `source_record_type=evidence.capture.frame`
   - `complete=true`
3. Retention eligibility marker:
   - `record_type=retention.eligible`
   - `source_record_id=<frame_id>`
   - `source_record_type=evidence.capture.frame`
   - `stage1_contract_validated=true`
   - `quarantine_pending=false`
4. UIA linkage requirements when `uia_ref` is present:
   - Snapshot row exists: `record_type=evidence.uia.snapshot` with id `uia_ref.record_id`
   - Deterministic doc rows exist:
     - `obs.uia.focus`
     - `obs.uia.context`
     - `obs.uia.operable`
   - Each `obs.uia.*` row must include:
     - `uia_record_id`, `uia_content_hash`
     - `hwnd`, `window_title`, `window_pid`
     - valid numeric `bboxes` (`[left, top, right, bottom]`, with `right>=left` and `bottom>=top`)

## Gate Semantics
- Contract gate must fail if any required count has a gap (`ok < required`).
- Contract gate must fail if per-frame issue counters are non-zero for required checks.
- Contract gate can require full queryability ratio (`frames_queryable / frames_total`) at `1.0`.

## Canonical Validator
- Tool: `tools/gate_stage1_contract.py`
- Primary input: `tools/soak/stage1_completeness_audit.py` output JSON.
- Optional input mode: direct DB/derived DB invocation (tool runs the audit first).

## Required Output Fields
`tools/gate_stage1_contract.py` emits:
- `ok`
- `reasons`
- `counts` (`frames_total`, `frames_queryable`, `frames_blocked`)
- `coverage` for:
  - `stage1_complete`
  - `retention_eligible`
  - `uia_snapshot`
  - `obs_uia_focus`
  - `obs_uia_context`
  - `obs_uia_operable`
- `issue_failures` (non-zero issue counters that block contract)

