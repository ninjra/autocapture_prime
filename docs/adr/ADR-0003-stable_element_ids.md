**Title:** Stable element IDs via deterministic bipartite matching
**Context:** Questions like “what did I click” need stable targets over time.
**Decision:** Track elements using IoU/type/text/parent cost + Hungarian assignment with fixed thresholds.
**Consequences:**

* Best-effort stability; scrollable content may remain difficult
* Deterministic and testable matching
  **Alternatives:** Hash-only IDs (too brittle).

---
