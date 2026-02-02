**Title:** No-Holes Capture Policy (Vaulted Exclusions)
**Context:** Excluded frames currently risk dropping raw pixels, creating unrecoverable gaps that undermine recall and citations.
**Decision:** Always persist raw pixels locally, even for excluded frames, by writing them to a vault namespace and keeping a non-null media_path; gate derived artifacts by default unless explicitly opted in.
**Consequences:**

* Recall continuity and citable evidence improve by eliminating gaps.
* Requires encryption-at-rest and clear UX markers for excluded/sensitive content.

**Sources:** [SRC-017, SRC-023, SRC-024, SRC-025, SRC-064, SRC-079]

---
