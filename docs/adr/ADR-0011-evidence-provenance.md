**Title:** Enforce EvidenceRef + ProvenanceRecord on Derived Objects
**Context:** The state layer must be citable and debuggable by construction.
**Decision:** Require EvidenceRef[] and ProvenanceRecord on all derived objects; block persistence if missing.
**Consequences:**

* Stronger auditability and citation guarantees.
* Slightly higher storage and validation overhead.

**Sources:** [SRC-022, SRC-053, SRC-098, SRC-009]

---
