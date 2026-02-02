**Title:** Determinism Scope Is Explicitly Partial
**Context:** Some components are deterministic by construction, others depend on model inference.
**Decision:** Treat schemas/contracts/provenance/caching/evidence bundles as deterministic; treat embedding inference and ANN builds as partially deterministic unless forced or snapshot/versioned.
**Consequences:**

* Determinism boundaries must be documented and tested.
* ANN and inference may require additional constraints for strict determinism.

**Sources:** [SRC-127, SRC-128, SRC-129, SRC-130]

---
