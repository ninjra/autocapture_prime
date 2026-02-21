**Title:** Deprecate legacy plugin manager in favor of NX subprocess plugins
**Context:** The legacy YAML plugin manager (`autocapture/plugins`) loads extensions in-process, which conflicts with the kernel’s isolation and sandboxing requirements. PromptOps and Research relied on this legacy manager, creating an isolation gap.
**Decision:** Migrate PromptOps and Research to the NX plugin system with subprocess hosting. Introduce NX builtins for prompt bundles and default research sources, and emit a deprecation warning when the legacy manager is instantiated. Keep legacy code for compatibility, but stop using it in core paths.
**Consequences:**

* Performance: PromptOps/Research load only scoped NX plugins (not the full plugin set).
* Accuracy: Prompt bundle snapshots remain deterministic; research defaults continue to function without legacy plugins.
* Security: PromptOps/Research now run under NX sandbox rules and process isolation.
* Citeability: Audit metadata and deterministic plugin selection apply uniformly.

**Alternatives considered:**

* Keep legacy manager in-process (fails isolation requirements).
* Rewrite PromptOps/Research as kernel-native services (loses plugin extensibility).
* Defer migration (continues isolation gap).

---
