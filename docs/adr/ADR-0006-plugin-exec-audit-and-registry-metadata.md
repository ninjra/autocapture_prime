**Title:** Separate plugin execution audit DB + registry metadata
**Context:** The kernel must be able to rerun historical datasets against evolving plugins while preserving full, deterministic traceability. Plugin failures should not destabilize the kernel, and planner/provider choices must stay deterministic while still leveraging failure history.
**Decision:** Use a dedicated SQLite audit database configured via `storage.audit_db_path`. Record per-call execution rows with timestamps, run_id, plugin_id, capability, method, success flag, error, duration, row-count estimates, memory RSS/VMS, input/output/data hashes, code hash, settings hash, and payload byte sizes. Record registry metadata (version, capability tags, provides, entrypoints, permissions, manifest path) and plugin load failures. Expose audit-derived failure summaries for deterministic provider ordering when enabled in config.
**Consequences:**

* Performance: minor overhead per call; acceptable for the audit depth and bounded by local storage.
* Accuracy: deterministic hashes and failure history improve reproducibility and safer provider ordering.
* Security: append-only audit trail for plugin behavior and load failures.
* Citeability: stable hashes + metadata create a durable provenance record.

**Alternatives considered:**

* Store audit rows in the metadata DB (increases contention and churn).
* Log to flat files only (harder to query, weaker traceability).
* Sample audit rows (loses completeness for reruns).
* No failure-aware ordering (less stable behavior under flaky plugins).

---
