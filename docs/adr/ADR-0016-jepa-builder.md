**Title:** Baseline Deterministic JEPA-like State Builder (Training Optional)
**Context:** Baseline must work without training; training is optional and gated.
**Decision:** Implement deterministic windowing/pooling for StateSpan/StateEdge; keep JEPA training as optional plugin with approval gates.
**Consequences:**

* Immediate functionality without training dependencies.
* Training path adds model governance requirements.

**Sources:** [SRC-068, SRC-069, SRC-070, SRC-071, SRC-072, SRC-073, SRC-074, SRC-075, SRC-003, SRC-076, SRC-079, SRC-080]

---
