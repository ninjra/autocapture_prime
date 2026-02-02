**Title:** Pluggable Vector Search with Deterministic Baseline
**Context:** The blueprint allows optional ANN, but requires deterministic behavior by default.
**Decision:** Ship deterministic linear scan vector index; keep HNSW optional and stubbed unless versioned snapshots are provided.
**Consequences:**

* Deterministic baseline is slower but reliable.
* Optional ANN requires snapshot/version governance.

**Sources:** [SRC-065, SRC-066, SRC-067, SRC-034]

---
