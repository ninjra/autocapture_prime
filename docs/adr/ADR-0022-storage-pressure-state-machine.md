**Title:** Storage Pressure Degrades Processing Before Capture
**Context:** Hard disk pressure can halt capture, creating silent downtime; capture continuity is a higher priority than derived processing.
**Decision:** Implement a storage pressure state machine (green/yellow/red/black) that pauses processing first, then reduces capture fidelity, stopping capture only as last resort.
**Consequences:**

* Capture continuity is preserved under low disk conditions.
* Requires clear status reporting and operator guidance for remediation.

**Sources:** [SRC-012, SRC-019, SRC-028, SRC-029, SRC-030, SRC-031]

---
