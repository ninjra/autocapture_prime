**Title:** Persist derived artifacts only; enforce 60‑day TTL for pixels
**Context:** Pixels are disallowed after TTL; derived artifacts must support queries.
**Decision:** Store no raw images in the derived artifact store; image store (if any) has strict TTL metadata + sweeper audits.
**Consequences:**

* Cannot re-run improved extractors after TTL unless you stored enough intermediate structure
* Must store provenance-rich outputs now (bboxes + confidences)
  **Alternatives:** Keep thumbnails (rejected).

---
