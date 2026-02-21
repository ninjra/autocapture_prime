**Title:** Deterministic Caching and Content-Addressed Identity
**Context:** Idempotent reprocessing requires deterministic cache keys and IDs.
**Decision:** Use canonical JSON hashing (SHA-256) to compute config hashes, cache keys, and deterministic UUIDs from inputs + plugin + config + model version.
**Consequences:**

* Reprocessing is reproducible.
* Hashing/canonicalization must be stable across platforms.

**Sources:** [SRC-089, SRC-048, SRC-020, SRC-005]

---
