**Title:** Introduce State Layer and State Tape
**Context:** The blueprint inserts a State Layer between extraction and indexing to make temporal state explicit and citable.
**Decision:** Add a deterministic State Layer that produces an append-only state_tape (StateSpan + StateEdge) and persist it separately from raw evidence.
**Consequences:**

* Retrieval pivots to state_tape instead of raw-store browsing.
* State transitions become explicit and replayable.

**Sources:** [SRC-001, SRC-015, SRC-024, SRC-025, SRC-016]

---
