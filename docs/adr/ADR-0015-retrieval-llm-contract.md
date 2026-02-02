**Title:** Evidence-Only Retrieval API and LLM Contract
**Context:** The LLM must not browse raw stores and must cite evidence by construction.
**Decision:** Retrieval builds QueryEvidenceBundle and the answer layer consumes only that bundle; empty hits return “no evidence”.
**Consequences:**

* LLM input is constrained to evidence bundles.
* Policy gate controls raw media/text exposure.

**Sources:** [SRC-006, SRC-081, SRC-082, SRC-083, SRC-084, SRC-085, SRC-086, SRC-087, SRC-088, SRC-059, SRC-096]

---
