**Title:** Persist State Tape Using SQLite Minimal Schema
**Context:** The source provides a minimal SQLite schema for state spans, edges, and evidence links.
**Decision:** Implement the state_tape store with state_span/state_edge/state_evidence_link tables and required indexes.
**Consequences:**

* Enables deterministic, append-only state persistence.
* Requires local DB initialization and schema creation on open.

**Sources:** [SRC-060, SRC-061, SRC-062, SRC-063, SRC-064, SRC-110]

---
