# Stage2+ unblock: allow forced heavy processing in `USER_QUERY` mode

## Purpose of this repo (as implemented today)

This codebase is an *end‑to‑end local capture → normalize → enrich → query* pipeline:

- **Stage 1 (Capture/Normalize):** ingest screenshots/UIA/HID into a durable normalized layer (metadata + media + derived records).
- **Stage 2 (Enrich):** run deterministic extractors (OCR, UIA text, etc.) plus optional VLM extraction; write derived text + indices and/or state-layer artifacts.
- **Stage 3 (Query):** answer natural-language questions by retrieving derived/state artifacts within a time window and building a cited response.

The **NX kernel (`autocapture_nx/`) + runtime (`autocapture/runtime/`) + built-in plugins** are the functional “spine”. `autocapture_prime/` contains older/parallel code paths and is a common source of confusion (scope drift).

## Scope drift that is actively hurting Stage 2+

The repo currently has multiple “nearly-the-same” orchestration paths (prime vs nx vs legacy), but **the hard breakage** preventing Stage 2+ from working is in the shared runtime governor, not in those parallel modules.

This patch focuses on the single issue that can make *all Stage 2+ processing appear dead* even when Stage 1 is healthy.

---

## Symptom

In Windows-sidecar + WSL2 workflows (no local input tracker), Stage 2+ frequently needs an explicit operator run:

- `autocapture enrich` (or anything that sets `query_intent=True`) is expected to run the heavy `idle.extract` job even when the system is “active”.

Today, that frequently results in **no extraction/indexing happening at all**, and queries return no evidence even though Stage 1 data exists.

---

## Root cause (deterministic)

`RuntimeConductor.run_once(force=True)` sets `signals["query_intent"]=True`, which selects governor mode `USER_QUERY`.

However, the governor’s **lease gate** and **preemption logic** were written as if heavy work only occurs in `IDLE_DRAIN`, which blocks and/or immediately preempts heavy jobs in `USER_QUERY`.

### Blocking lease gate

File: `autocapture/runtime/governor.py`

```py
if decision.mode != "IDLE_DRAIN" or not decision.heavy_allowed:
    return BudgetLease(...allowed=False)
```

In `USER_QUERY`, `decision.mode != "IDLE_DRAIN"` is true → **heavy work never obtains a lease** → scheduler defers forever.

### Immediate preemption

File: `autocapture/runtime/governor.py`

```py
if decision.mode != "IDLE_DRAIN" and elapsed_ms >= grace_ms:
    return True
```

In `USER_QUERY`, after `preempt_grace_ms` (default 150ms) this returns true → any long-running heavy job aborts almost immediately.

---

## Patch

### 1) Allow heavy leases in `USER_QUERY`

### 2) Do not preempt *just because* we are in `USER_QUERY`

Apply the following diffs.

#### `autocapture/runtime/governor.py`

```diff
--- a/autocapture/runtime/governor.py
+++ b/autocapture/runtime/governor.py
@@ -275,7 +275,7 @@ class RuntimeGovernor:
     def lease(self, *, estimated_ms: int, require_gpu: bool) -> BudgetLease:
         with self._lock:
             decision = self._decide_locked(self._last_signals)
-            if decision.mode != "IDLE_DRAIN" or not decision.heavy_allowed:
+            if decision.mode not in {"IDLE_DRAIN", "USER_QUERY"} or not decision.heavy_allowed:
                 return BudgetLease(
                     allowed=False,
                     granted_ms=0,
                     mode=decision.mode,
@@ -333,7 +333,7 @@ class RuntimeGovernor:
         grace_ms = max(0, int(budgets.get("preempt_grace_ms", 150)))
         suspend_deadline = max(0, int(enf.get("suspend_deadline_ms", 500)))
-        if decision.mode != "IDLE_DRAIN" and suspend_deadline:
+        if decision.mode not in {"IDLE_DRAIN", "USER_QUERY"} and suspend_deadline:
             grace_ms = suspend_deadline if grace_ms <= 0 else min(grace_ms, suspend_deadline)
         elapsed_ms = (time.monotonic() - self._mode_changed_at) * 1000.0
-        if decision.mode != "IDLE_DRAIN" and elapsed_ms >= grace_ms:
+        if decision.mode not in {"IDLE_DRAIN", "USER_QUERY"} and elapsed_ms >= grace_ms:
             return True
         if (
             decision.mode == "IDLE_DRAIN"
             and not decision.heavy_allowed
             and decision.reason in {"budget_exhausted", "jobs_exhausted"}
```

#### `tests/test_governor_gating.py`

```diff
--- a/tests/test_governor_gating.py
+++ b/tests/test_governor_gating.py
@@ -57,6 +57,22 @@ class GovernorGatingTests(unittest.TestCase):
         scheduler.run_pending({"user_active": False, "idle_seconds": 10})
         self.assertEqual(ran, ["heavy", "light"])

+    def test_user_query_allows_heavy_even_when_active(self) -> None:
+        governor = RuntimeGovernor(idle_window_s=5)
+        scheduler = Scheduler(governor)
+        ran: list[str] = []
+        scheduler.enqueue(Job(name="heavy", fn=lambda: ran.append("heavy"), heavy=True))
+        scheduler.run_pending({"user_active": True, "idle_seconds": 0, "query_intent": True})
+        self.assertEqual(ran, ["heavy"])
+
+    def test_user_query_does_not_preempt_by_mode(self) -> None:
+        governor = RuntimeGovernor(idle_window_s=1)
+        governor.decide({"user_active": True, "idle_seconds": 0, "query_intent": True})
+        governor._mode_changed_at -= 1.0  # simulate > preempt_grace_ms elapsed
+        self.assertFalse(governor.should_preempt({"user_active": True, "idle_seconds": 0, "query_intent": True}))
+
     def test_preempt_immediate_on_activity_when_configured(self) -> None:
         governor = RuntimeGovernor(idle_window_s=1)
         governor.update_config({"runtime": {"budgets": {"preempt_grace_ms": 0}}})
```

---

## Verification

From repo root:

```bash
pytest tests/test_governor_gating.py -q
```

Expected: exit 0.

---

## Operational guidance: Windows sidecar + WSL2 (CUDA)

After this patch:

- `autocapture enrich` should actually run `idle.extract` even when `activity_signal.json` is missing/stale, because it forces `query_intent=True`.
- Once Stage 2 has produced derived text + indices/state, `autocapture query "<question>"` should begin returning evidence-backed answers (subject to your extractor/provider config).

If Stage 2 is still not producing anything, the next deterministic checks are:

1. Confirm you are pointing at the **same `AUTOCAPTURE_DATA_DIR`** where Stage 1 is writing `metadata.db` and `media/`.
2. Confirm extractors are enabled and available (`processing.idle.extractors.ocr` etc.) and that the OCR/VLM providers are reachable from the environment executing Stage 2.

---

## Optional scope-drift cleanup (recommended, not required for this fix)

If you want to reduce future confusion:

- Add a short `docs/ARCHITECTURE.md` declaring `autocapture_nx/` as canonical runtime and `autocapture_prime/` as legacy/experimental.
- Add a deprecation banner to the `autocapture_prime` CLI entrypoints directing users to `autocapture_nx`.

