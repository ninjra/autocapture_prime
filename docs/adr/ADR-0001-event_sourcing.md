**Title:** Use event-sourced persistence: store states + deltas + actions
**Context:** Post‑TTL forensics require history and change explanations.
**Decision:** Persist `ScreenState`, `DeltaEvent`, `ActionEvent` as first-class artifacts; treat all else as derived.
**Consequences:**

* Enables “what changed” queries without pixels
* Requires careful schema/versioning and storage growth management
  **Alternatives considered:** Storing only extracted text (insufficient for UI/action questions).

---
