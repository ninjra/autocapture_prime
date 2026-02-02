**Title:** Template-level evaluation harness for PromptOps
**Context:** We need deterministic, template-layer checks for prompt mappings that are consistent across clients and suitable for meta-analysis, without invoking model inference.
**Decision:** Implement a PromptOps template evaluation harness that runs PromptOps transformations on ground-truth cases, validates expected hashes/tokens/apply behavior, and emits a deterministic JSON report. The harness uses SHA-256 for prompt and source hashes to avoid client-to-client differences, disables PromptOps history/GitHub side effects during evaluation, and supports per-case overrides.
**Consequences:**

* Performance: lightweight, no model calls.
* Accuracy: catches prompt/template regressions early with ground-truth checks.
* Security: avoids side effects (no prompt persistence, no GitHub actions).
* Citeability: stable hashes + case metadata enable durable, comparable reports.

**Alternatives considered:**

* Model-based evaluation (non-deterministic and costly).
* Git diff–only checks (miss runtime source mappings).
* Rely on PromptOps history (side effects and inconsistent across clients).

---
