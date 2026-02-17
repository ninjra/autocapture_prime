# Windows Hypervisor Popup Query Contract

## Purpose
Use a native Windows popup/command bar in Hypervisor and send natural-language queries to `autocapture_prime` on localhost without running capture/processing in the query path.

## Endpoint
- Method: `POST`
- URL: `http://127.0.0.1:8787/api/query/popup`
- Headers:
  - `Authorization: Bearer <token>`
  - `Content-Type: application/json`
- Body:
  - `query` (string, required)
  - `schedule_extract` (bool, optional, default `false`)
  - `max_citations` (int, optional, default `8`, max `32`)

## Token Bootstrapping
1. Read token once from localhost:
   - `GET http://127.0.0.1:8787/api/auth/token`
2. Cache token in-memory in Hypervisor process.
3. Refresh token only when 401 is returned.

## Response Contract
```json
{
  "ok": true,
  "query": "who is working with me on the flagged quorum message",
  "query_run_id": "qry_xxx",
  "state": "ok",
  "summary": "Quorum collaborator: Nikki M",
  "bullets": ["quorum collaborator: Nikki M", "source pane: Outlook task card"],
  "topic": "adv_incident",
  "confidence_pct": 93.0,
  "needs_processing": false,
  "processing_blocked_reason": "",
  "scheduled_extract_job_id": "",
  "latency_ms_total": 42.5,
  "citations": [
    {
      "claim_index": 0,
      "citation_index": 0,
      "claim_text": "Quorum collaborator: Nikki M",
      "record_id": "run1/derived.hard_vlm.answer/1",
      "record_type": "derived.hard_vlm.answer",
      "source": "hard_vlm.direct",
      "span_kind": "record",
      "offset_start": 0,
      "offset_end": 28,
      "stale": false,
      "stale_reason": ""
    }
  ]
}
```

## Hypervisor UX Rules
- Show `summary` as the main answer line.
- Show up to 3 `bullets` as supporting lines.
- Show confidence chip from `confidence_pct`.
- If `needs_processing=true`:
  - Show non-blocking hint: `processing_blocked_reason`.
  - Optionally call again with `schedule_extract=true`.
- Keep query bar non-modal and fast; do not block UI thread.

## Retry/Failure Policy
- Network timeout: 12s.
- Retries: 2 with exponential backoff (200ms, 600ms).
- On 401: refresh token via `/api/auth/token` and retry once.
- On non-200:
  - Show concise error in popup.
  - Persist diagnostic row with `query`, status code, and response body.

## Acceptance Checklist
- Popup can submit query and render `summary/bullets/citations`.
- 401 flow auto-recovers by token refresh.
- `needs_processing` state is rendered and schedule-retry path works.
- No direct database access from Hypervisor; API only.

## One-Line Smoke
```bash
/mnt/d/projects/autocapture_prime/tools/popup_query_smoke.sh "what am i working on right now"
```
