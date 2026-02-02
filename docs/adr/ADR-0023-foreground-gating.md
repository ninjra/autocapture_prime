**Title:** Foreground Gating for Heavy Processing
**Context:** The system must stay invisible while the user is active; heavy processing during activity violates the core trust contract.
**Decision:** Treat user activity as authoritative: when active, enforce worker ceilings (often 0) for OCR/VLM/embeddings and respect GPU concurrency caps; only allow heavy work during idle windows within budgets.
**Consequences:**

* Responsiveness and trust improve; heavy workloads shift to idle periods.
* Derived artifacts may be delayed; scheduling must surface reasons in UI.

**Sources:** [SRC-022, SRC-061, SRC-062]

---
