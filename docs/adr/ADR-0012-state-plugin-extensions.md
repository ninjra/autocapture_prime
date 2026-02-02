**Title:** Extend Plugin System with State Layer Plugin Types
**Context:** The state layer requires independent, replaceable components with deterministic behavior.
**Decision:** Add StateBuilderPlugin, VectorIndexPlugin, EvidenceCompilerPlugin, WorkflowMinerPlugin, and AnomalyPlugin under the existing plugin system with deterministic ID derivation.
**Consequences:**

* Enables swap-in components without kernel changes.
* Requires plugin registry allowlists and capability policies.

**Sources:** [SRC-002, SRC-030, SRC-033, SRC-036, SRC-039, SRC-042, SRC-047, SRC-048]

---
