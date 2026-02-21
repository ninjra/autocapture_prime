# Advanced20 Strict Rubric

Generated: 2026-02-19

Purpose: define fail-closed grading modes used by strict Advanced20 evaluation.

## Global Rules
- Evaluate all 20 rows (`Q1..Q10`, `H1..H10`), no skip-as-pass.
- Reject `indeterminate` summaries for Q-series in strict mode.
- Ignore `support:` and `source:` bullets for strict token checks.
- Do not match expected tokens against full serialized result JSON.

## Q-Series Modes
- `Q1`: exact token presence on answer surface + topic/state path checks.
- `Q2`: exact token presence on answer surface + topic/state path checks.
- `Q3`: exact token presence on answer surface + topic/state path checks.
- `Q4`: exact token presence on answer surface + topic/state path checks.
- `Q5`: exact token presence on answer surface + topic/state path checks.
- `Q6`: exact token presence on answer surface + topic/state path checks + no `indeterminate`.
- `Q7`: exact token presence on answer surface + topic/state path checks.
- `Q8`: exact token presence on answer surface + topic/state path checks.
- `Q9`: exact token presence on answer surface + topic/state path checks + numeric strict checks (`red_count=8`, `green_count=16`).
- `Q10`: exact token presence on answer surface + topic/state path checks.

## H-Series Modes
- `H1..H9`: structured exact equality (`display.fields` / `hard_vlm.fields`), no free-text fallback in strict mode.
- `H10`: IoU tolerance for bounding boxes (`COMPLETE`, `VIEW_DETAILS`) with threshold `0.60`; other fields structured exact.
