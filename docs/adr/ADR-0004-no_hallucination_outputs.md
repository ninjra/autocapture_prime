**Title:** Outputs must be observed/derived/unknown; never fabricated
**Context:** Vision models can output plausible but false details.
**Decision:** Any field lacking evidence is left unset and explicitly marked unknown; confidence gating required.
**Consequences:**

* Fewer false positives; more partial outputs
* Query layer must handle unknowns gracefully
  **Alternatives:** “Fill in” missing values (rejected).

---
