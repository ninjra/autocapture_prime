**Title:** Security Boundary and Policy Gate Enforcement
**Context:** The system must remain local-only by default and prevent plugin bypass of policy.
**Decision:** Enforce policy gating between retrieval and answer layers; treat embeddings as sensitive derived data; disallow silent egress.
**Consequences:**

* Centralized policy enforcement.
* Plugins must route exports through PolicyGate.

**Sources:** [SRC-095, SRC-096, SRC-097, SRC-019, SRC-028, SRC-029]

---
