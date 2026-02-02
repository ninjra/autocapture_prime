**Title:** Codex Two-Phase Process and DO_NOT_SHIP Gates
**Context:** The source mandates a recon-first process and explicit regression gates.
**Decision:** Require PHASE 1 recon artifacts before implementation; enforce DO_NOT_SHIP gates via tests and gate scripts.
**Consequences:**

* Slower initial changes but lower regression risk.
* CI/local tooling must surface gate failures.

**Sources:** [SRC-100, SRC-101, SRC-107, SRC-108, SRC-115, SRC-118, SRC-119, SRC-121, SRC-122, SRC-123]

---
