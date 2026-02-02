implement this plan and the associated spec file as plugins as appropriate. THREAD: 2026-01-31_autocapture-jepa-blueprint
CHAT_ID: 20260131_autocapture-jepa-blueprint

* Add a **State Layer** to Autocapture: deterministic, versioned `state_tape` derived from captures with strict provenance.
* Introduce **plugin types** for state-building, indexing, retrieval, and evidence compilation (baseline works without training; JEPA-training is optional).
* Define **data contracts**: `EvidenceRef`, `ProvenanceRecord`, `StateSpan`, `StateEdge`, and `QueryEvidenceBundle`.
* Extend storage: SQLite tables + optional pluggable vector index; strict content-addressed IDs for cache + reproducibility.
* Add a **retrieval API** and **LLM prompt contract** that enforces citation-by-construction (no evidence → no answer).
* Provide a **Codex verification prompt** to enumerate required code/schema changes before any edits.

---

## key_claims

| Claim                                                                                                                                                                                                   | Label         |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| A “State Layer” that produces compact `StateSpan` embeddings + `StateEdge` transitions reduces LLM reliance on token recall and improves temporal coherence for autocapture queries.                    | [INFERENCE]   |
| Enforcing a first-class `EvidenceRef` + `ProvenanceRecord` on every derived artifact makes answers citable and debuggable by construction.                                                              | [INFERENCE]   |
| A baseline “JEPA-like” state builder can ship without training by composing frozen extractors + deterministic pooling; optional JEPA training can later improve prediction-error and sequence modeling. | [INFERENCE]   |
| Quantitative wins (latency/accuracy) are workload-dependent and require local benchmarks on your capture cadence and extraction quality.                                                                | [NO EVIDENCE] |

---

# 1) Blueprint: what Autocapture should become

## 1.1 System shape (new layer highlighted)

```text
[Capture Sources]
  screenshots / window metadata / input events
        |
        v
[Artifact Store]  (encrypted, append-only)
        |
        v
[Extraction Layer]  (OCR, UI hints, region embeddings)
        |
        v
[STATE LAYER]  (new)  --> produces: StateSpan(z_t), StateEdge(Δ, err), links to EvidenceRef
        |
        v
[Index Layer]  (text + vector + metadata)
        |
        v
[Query + LLM Orchestrator]
  - retrieval over state tape
  - evidence bundle assembly
  - response with citations
```

## 1.2 Autocapture “Core Contract” (exactly what it should do and be like)

| Capability             | Must do                                                                         | Must not do                                                  |
| ---------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Capture & retention    | Capture artifacts with stable IDs; retention policies; encrypted at rest        | Silent egress of raw media/text by default                   |
| Pipeline orchestration | Run plugins deterministically over immutable artifacts; idempotent reprocessing | Non-versioned derived outputs (no “mystery state”)           |
| Provenance             | Attach evidence + provenance to **every** derived object                        | Produce embeddings/labels without a trace back to media/time |
| State tape             | Maintain an append-only timeline of `StateSpan` + `StateEdge`                   | Hide state inside the LLM prompt only                        |
| Query                  | Provide structured retrieval returning `QueryEvidenceBundle`                    | Let the LLM “browse” raw store directly                      |
| Policy                 | Enforce app allow/deny, redaction, egress policy at the platform boundary       | Let plugins bypass policy controls                           |

---

# 2) Plugin architecture extensions

## 2.1 New plugin types

| Plugin type                      | Purpose                                                 | Input → Output                           | Determinism requirements                               |
| -------------------------------- | ------------------------------------------------------- | ---------------------------------------- | ------------------------------------------------------ |
| `StateBuilderPlugin`             | Build `StateSpan` + `StateEdge` from extracted features | `ExtractBatch` → `StateTapeBatch`        | Fixed config hash; stable pooling; content-address IDs |
| `VectorIndexPlugin` (optional)   | Provide ANN search over state embeddings                | `StateSpan[]` ↔ `topK(StateSpan)`        | Deterministic build or versioned index snapshots       |
| `EvidenceCompilerPlugin`         | Compile minimal evidence for a query hit                | `StateSpanHit[]` → `QueryEvidenceBundle` | Evidence selection rules fixed + versioned             |
| `WorkflowMinerPlugin` (optional) | Cluster repeated sequences into workflows               | `StateTape` → `WorkflowDefs`             | Versioned model + seed                                 |
| `AnomalyPlugin` (optional)       | Use prediction error to flag surprises                  | `StateEdge.err` → `Alerts`               | Thresholds versioned + tested                          |

## 2.2 Plugin base interface (spec)

```ts
// language-agnostic shape; implement in your runtime of choice
type PluginId = string;         // e.g., "state.jepa_like.v1"
type SemVer = string;           // e.g., "1.3.0"

interface AutocapturePlugin {
  id: PluginId;
  version: SemVer;
  init(ctx: PluginContext, config: unknown): void;

  // Deterministic signature: output IDs are derived from (inputs + plugin + config + model_version)
  process(batch: unknown): Promise<unknown>;

  // Optional: used for migrations / reproducibility
  getConfigSchema?(): object;   // JSON schema
  getOutputSchema?(): object;   // JSON schema
}
```

---

# 3) Data contracts (the critical “specs”)

## 3.1 Evidence and provenance (non-negotiable)

```json
{
  "EvidenceRef": {
    "media_id": "uuid",
    "ts_start_ms": 0,
    "ts_end_ms": 0,
    "frame_index": 0,
    "bbox_xywh": [0,0,0,0],
    "text_span": {"start": 0, "end": 0},
    "sha256": "hex",
    "redaction_applied": true
  },
  "ProvenanceRecord": {
    "producer_plugin_id": "string",
    "producer_plugin_version": "string",
    "model_id": "string",
    "model_version": "string",
    "config_hash": "hex",
    "input_artifact_ids": ["uuid"],
    "created_ts_ms": 0
  }
}
```

**Invariant:** no derived object is persisted without both `EvidenceRef[]` and `ProvenanceRecord`.

## 3.2 State tape objects

```json
{
  "StateSpan": {
    "state_id": "uuid",
    "session_id": "uuid",
    "ts_start_ms": 0,
    "ts_end_ms": 0,
    "z_embedding": {"dim": 768, "dtype": "f16", "blob": "base64"},
    "summary_features": {
      "app": "string",
      "window_title_hash": "hex",
      "top_entities": ["string"]
    },
    "evidence": ["EvidenceRef"],
    "provenance": "ProvenanceRecord"
  },
  "StateEdge": {
    "edge_id": "uuid",
    "from_state_id": "uuid",
    "to_state_id": "uuid",
    "delta_embedding": {"dim": 768, "dtype": "f16", "blob": "base64"},
    "pred_error": 0.0,
    "evidence": ["EvidenceRef"],
    "provenance": "ProvenanceRecord"
  }
}
```

**Notes**

* `StateSpan` is the “what’s true during this time range”.
* `StateEdge` is the “what changed + how surprising was it”.

## 3.3 Query API returns an evidence bundle (not raw artifacts)

```json
{
  "QueryEvidenceBundle": {
    "query_id": "uuid",
    "hits": [{
      "state_id": "uuid",
      "score": 0.0,
      "ts_start_ms": 0,
      "ts_end_ms": 0,
      "evidence": ["EvidenceRef"],
      "extracted_text_snippets": [{
        "media_id": "uuid",
        "ts_ms": 0,
        "text": "string",
        "span": {"start": 0, "end": 0}
      }]
    }],
    "policy": {
      "can_show_raw_media": false,
      "can_export_text": false
    }
  }
}
```

**Invariant:** LLM sees only `QueryEvidenceBundle` + explicitly permitted payloads.

---

# 4) Storage & indexing spec

## 4.1 SQLite tables (minimal viable schema)

```sql
-- Raw artifacts already exist in your system; below are state-layer additions.

CREATE TABLE state_span (
  state_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  ts_start_ms INTEGER NOT NULL,
  ts_end_ms INTEGER NOT NULL,
  z_embedding BLOB NOT NULL,
  z_dim INTEGER NOT NULL,
  z_dtype TEXT NOT NULL,
  app TEXT,
  window_title_hash TEXT,
  top_entities_json TEXT,
  provenance_json TEXT NOT NULL
);

CREATE TABLE state_edge (
  edge_id TEXT PRIMARY KEY,
  from_state_id TEXT NOT NULL,
  to_state_id TEXT NOT NULL,
  delta_embedding BLOB NOT NULL,
  delta_dim INTEGER NOT NULL,
  delta_dtype TEXT NOT NULL,
  pred_error REAL NOT NULL,
  provenance_json TEXT NOT NULL,
  FOREIGN KEY(from_state_id) REFERENCES state_span(state_id),
  FOREIGN KEY(to_state_id) REFERENCES state_span(state_id)
);

CREATE TABLE state_evidence_link (
  id TEXT PRIMARY KEY,
  state_object_type TEXT NOT NULL,    -- "span" | "edge"
  state_object_id TEXT NOT NULL,      -- state_id or edge_id
  evidence_json TEXT NOT NULL
);

CREATE INDEX idx_state_span_time ON state_span(ts_start_ms, ts_end_ms);
CREATE INDEX idx_state_span_session ON state_span(session_id);
CREATE INDEX idx_state_edge_from_to ON state_edge(from_state_id, to_state_id);
```

## 4.2 Vector search (pluggable)

* Default implementation: `LinearScanVectorIndex` (no dependencies; slower but deterministic).
* Optional implementation: `HNSWVectorIndex` (faster; must be versioned and reproducibly built).

**Contract:** index stores `(state_id, embedding_hash, model_version)` so stale embeddings cannot be queried.

---

# 5) State Builder spec (baseline first, JEPA-like next)

## 5.1 Baseline “JEPA-like” (ships first, no training required)

**Inputs** (from Extraction Layer):

* region-level vision embeddings (per window/ROI)
* OCR text + text embeddings
* app/window metadata
* input events (optional)

**Computation**

* `StateSpan` windowing: fixed duration (e.g., 3–10s) OR heuristic boundary when app/window changes.
* `z_t` = deterministic pooling:

  * region embeddings pooled by fixed rule (mean, with optional weights by ROI type)
  * text embedding pooled by fixed rule (mean over tokens above confidence threshold)
  * concatenate/merge then project to fixed dim (deterministic linear layer or fixed PCA matrix shipped with build)

**StateEdge**

* `Δz_t = z_t - z_(t-1)` (or normalized difference)
* `pred_error = 1 - cosine(z_t, z_(t-1))` (baseline surprise)

This yields: temporal continuity, change detection, and searchability without requiring any JEPA training loop.

## 5.2 Optional: true JEPA-style training (later plugin upgrade)

Add a trainable predictor with a teacher/target encoder:

* context encoder produces `z_ctx` from partially observed spans
* target encoder (EMA/teacher) produces `z_tgt` from masked-out future/regions
* predictor outputs `z_pred`; loss = `MSE(z_pred, stopgrad(z_tgt))`

**Training boundaries**

* training runs locally and writes `model_version` + `training_run_id`
* inference is a separate plugin version gate: only load signed/approved model artifacts

---

# 6) LLM Orchestrator contract (citation-by-construction)

## 6.1 Retrieval sequence (hard requirement)

1. parse user question → structured query (time/app/entity filters)
2. retrieve `StateSpan` hits (vector + metadata)
3. expand to neighbor edges for continuity (`StateEdge` graph walk)
4. compile `QueryEvidenceBundle`
5. generate answer with inline citations referencing `EvidenceRef.media_id + ts`

## 6.2 Guardrails

* If `QueryEvidenceBundle.hits` is empty → respond “no evidence”.
* If policy disallows raw media/text → answer must be based on permitted summaries only and explicitly state that limitation.

---

# 7) 4 Pillars optimization (design-level, enforceable)

## 7.1 Performance (P1)

* Deterministic caching key: `hash(plugin_id, plugin_version, model_version, config_hash, input_artifact_ids[])`
* Incremental processing: only new captures produce new `StateSpan`
* Query path: ANN/linear scan over `z_t` + narrow by time/app

## 7.2 Accuracy (P2)

* Separate “state” from “language”: LLM can’t invent timeline without evidence bundle
* `StateEdge.pred_error` enables anomaly surfacing and “what changed” queries
* Optional workflow mining improves repeated-task recall without storing more raw text

## 7.3 Security (P3)

* Default local-only; encrypted artifact store; embeddings treated as sensitive derived data
* Policy gate sits between retrieval and LLM
* Optional export modes are explicit and logged (no silent egress)

## 7.4 Citable (P4)

* Evidence is first-class: every `StateSpan/Edge` stores `EvidenceRef[]`
* Query returns evidence bundle; answer template requires citing evidence IDs/timestamps

---

# 8) Codex “verify before change” prompt (use as-is)

```text
You are Codex operating on the Autocapture repository.

Goal: implement a new “State Layer” and plugins described below WITHOUT making changes until you first verify what must change.

PHASE 1 — RECON (no code changes):
1) Identify current pipeline stages and extension points:
   - capture ingestion
   - extraction (OCR/embeddings)
   - indexing/search
   - query/LLM orchestration
2) Locate:
   - plugin registry / DI container
   - job scheduler / background worker
   - artifact store + encryption boundary
   - database schema + migrations framework
3) Produce an inventory:
   - files/modules to modify
   - new files/modules to add
   - new DB tables/migrations
   - any required config flags
4) For each identified change, map it to one of these new components:
   - StateBuilderPlugin
   - EvidenceCompilerPlugin
   - StateTape storage (state_span/state_edge/state_evidence_link)
   - VectorIndexPlugin (default linear scan; optional ANN)
   - QueryEvidenceBundle API + policy gate
5) List risks:
   - performance hot paths
   - security boundary violations
   - determinism pitfalls
   - schema migration hazards

Output of PHASE 1 must be:
A) a concrete change plan (by file path) and a migration plan
B) a test plan with regression checks
C) a rollout plan with feature flags (default off)

PHASE 2 — IMPLEMENT (only after plan is accepted):
Implement minimal baseline (no training required):
- Create new DB tables and migration
- Add StateLayer stage to pipeline
- Implement baseline StateBuilderPlugin:
  - deterministic windowing
  - z_t pooling from existing extracted features
  - Δz and pred_error baseline
  - evidence + provenance attached
- Implement retrieval API to return QueryEvidenceBundle
- Update LLM orchestrator to require evidence bundle and to return “no evidence” when empty
- Add tests:
  - provenance completeness (required)
  - deterministic IDs for same input/config (required)
  - policy gate prevents raw export when disabled (required)
  - query returns stable evidence references (required)

Do not introduce new heavy dependencies unless already present.
Prefer pure code / existing libraries already in repo.

Stop immediately if any regression is detected; do not ship.
```

---

## Pillars per recommendation

| Recommendation                                                                    | improved   | risked                                                             | enforcement_location                                       | regression_detection                                                                                                |
| --------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------ | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Add State Layer + provenance/evidence contracts as first-class DB objects         | P2, P4, P1 | P3 (more derived data persisted)                                   | DB schema + pipeline boundary + policy gate                | Any missing `EvidenceRef`/`ProvenanceRecord` ⇒ DO_NOT_SHIP; storage growth budget; query p95 latency budget         |
| Ship baseline JEPA-like state builder (no training) using deterministic pooling   | P1, P2, P4 | P2 (representation may be weaker than trained), P1 (extra compute) | StateBuilderPlugin + caching key + batch scheduler         | Ingestion latency regression > budget ⇒ DO_NOT_SHIP; determinism test failure ⇒ DO_NOT_SHIP                         |
| Add QueryEvidenceBundle API and make LLM orchestration evidence-only              | P2, P4, P3 | P1 (extra retrieval step)                                          | Query service + orchestrator prompt contract + policy gate | Any answer without evidence IDs when hits exist ⇒ DO_NOT_SHIP; “no evidence” path covered by tests                  |
| Optional later: predictor/JEPA training plugin gated by model approval/versioning | P2         | P1 (training cost), P3 (model artifact handling)                   | Model store + approval gate + provenance model_version     | Model version mismatch or unsigned model loaded ⇒ DO_NOT_SHIP; accuracy eval regression on golden set ⇒ DO_NOT_SHIP |

---

## DETERMINISM

DETERMINISM: PARTIAL (scoped)

* VERIFIED for: schema/contracts; provenance rules; caching keys; evidence bundle structure.
* PARTIAL for: embedding/model inference unless forced to CPU deterministic mode and seeded; optional ANN index build unless snapshot/versioned.

TS: 2026-01-31T12:09:15 America/Denver

THREAD: 2026-01-31_autocapture-jepa-blueprint
CHAT_ID: 20260131_autocapture-jepa-blueprint
TS: 2026-01-31T12:09:15 America/Denver
