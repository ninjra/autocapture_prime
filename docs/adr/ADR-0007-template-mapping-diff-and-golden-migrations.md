**Title:** Template mapping diffs + golden migration fixtures
**Context:** Prompt/template mappings and storage migrations are high-risk for regressions. We need deterministic visibility into mapping drift and a safety net for DB migrations that preserves provenance and reproducibility.
**Decision:** Record template mapping diffs in the audit DB with stable source snapshots, hashes, and unified diffs. Add versioned golden migration fixtures under `tests/fixtures/migrations/` and enforce deterministic migration verification in tests.
**Consequences:**

* Performance: minimal overhead to hash and diff mappings; migrations remain test-only.
* Accuracy: mapping diffs expose regressions early; golden fixtures ensure deterministic migrations.
* Security: audit trail of mapping evolution and migration outcomes.
* Citeability: stable hashes + diffs provide traceable provenance for prompt/template evolution.

**Alternatives considered:**

* Rely on git diffs alone (misses runtime mapping composition and sources).
* Skip golden fixtures (migration regressions can slip through).
* Manual spot checks (non-deterministic, hard to reproduce).

---
