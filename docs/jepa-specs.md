# 1. System Context & Constraints

Project_Scope: Extend Autocapture with a deterministic, versioned **State Layer** that produces an append-only `state_tape` (`StateSpan` + `StateEdge`) derived from captures; enforce first-class evidence + provenance on every derived object; provide structured retrieval that returns `QueryEvidenceBundle` (not raw artifacts) and an LLM orchestration contract that is citation-by-construction (no evidence → no answer), using SQLite state tables plus an optional pluggable vector index; include a Codex verification prompt and regression-gated test plan.
Architectural_Hard_Rules:

* State_Layer_Existence: A new State Layer MUST exist and produce a deterministic, versioned `state_tape` derived from captures with strict provenance. Sources: [SRC-001]
* Plugin_Extension_Model: The architecture MUST support plugin types for state-building, indexing, retrieval, and evidence compilation; baseline MUST work without training; JEPA-training MUST be optional. Sources: [SRC-002, SRC-003]
* Non_Negotiable_Provenance: Every derived object MUST have `EvidenceRef[]` and a `ProvenanceRecord`; persistence MUST be blocked otherwise. Sources: [SRC-022, SRC-053]
* Append_Only_State_Tape: State tape MUST be append-only over `StateSpan` + `StateEdge`. Sources: [SRC-024]
* No_LLM_Raw_Browse: The LLM MUST NOT browse the raw store directly; it MUST only receive `QueryEvidenceBundle` plus explicitly permitted payloads. Sources: [SRC-027, SRC-059]
* No_Evidence_No_Answer: If `QueryEvidenceBundle.hits` is empty, the system MUST respond “no evidence”. Sources: [SRC-087]
* Policy_Boundary: App allow/deny, redaction, and egress policy MUST be enforced at the platform boundary; plugins MUST NOT bypass policy controls. Sources: [SRC-028, SRC-029]
* Storage_Baseline: State-layer additions MUST use SQLite tables; a pluggable vector index MAY be used; content-addressed IDs MUST be used for cache + reproducibility. Sources: [SRC-005]
* Dependency_Discipline: No new heavy dependencies MUST be introduced unless already present; prefer pure code/existing repo libraries. Sources: [SRC-116, SRC-117]
* Release_Gating: Stop immediately on regressions; do not ship if regression gates trigger. Sources: [SRC-118]
  Environment_Standards:
  Repository_Runtime: Python >=3.10 (pyproject.toml); optional Node.js for web UI; SQLite/SQLCipher for local stores. Sources: [SRC-050]
  Data_Stores:
  Artifact_Store:
  Properties: encrypted, append-only; captures retained via retention policies; raw media/text must not silently egress by default. Sources: [SRC-013, SRC-018, SRC-019]
  Interface: storage.metadata + storage.media capabilities (put_new/put/put_batch/get/keys for metadata; put/put_new/put_path/put_stream/get for media). Sources: [SRC-013, SRC-018, SRC-019]
  SQLite_State_Store:
  Required_Tables: `state_span`, `state_edge`, `state_evidence_link`. Sources: [SRC-060, SRC-061, SRC-062, SRC-063]
  Required_Indexes: `idx_state_span_time`, `idx_state_span_session`, `idx_state_edge_from_to`. Sources: [SRC-064]
  Determinism_Standards:
  Plugin_Output_ID_Derivation: Output IDs MUST be derived from (inputs + plugin + config + model_version). Sources: [SRC-048]
  Cache_Key: MUST be `hash(plugin_id, plugin_version, model_version, config_hash, input_artifact_ids[])`. Sources: [SRC-089]
  Determinism_Scope: partial (scoped); schema/contracts/provenance/caching/evidence bundle are verified; embedding inference and ANN build are partial unless constrained. Sources: [SRC-127, SRC-128, SRC-129, SRC-130]
  Query_And_LLM_Standards:
  Evidence_Bundle_Only: Query API MUST return `QueryEvidenceBundle`; LLM sees only evidence bundle + explicitly permitted payloads. Sources: [SRC-026, SRC-059]
  Citations: Answers MUST include inline citations referencing `EvidenceRef.media_id + ts`. Sources: [SRC-086]
  Testing_And_Shipping_Standards:
  Required_Tests: provenance completeness; deterministic IDs; policy gate prevents raw export when disabled; query returns stable evidence references. Sources: [SRC-115]
  DO_NOT_SHIP_Gates:

  * Missing evidence/provenance on any derived object. Sources: [SRC-119]
  * Ingestion latency regression > budget. Budget: <= 10% regression (performance.state_layer.ingestion_latency_regression_pct). Sources: [SRC-121]
  * Determinism test failure. Sources: [SRC-122]
  * Any answer without evidence IDs when hits exist. Sources: [SRC-123]
  * Training plugin loads unsigned or mismatched model version. Sources: [SRC-125]
  * Accuracy eval regression on golden set. Golden set definition: `tests/fixtures/state_golden.json` evaluated by `tools/state_layer_eval.py`. Sources: [SRC-126]
    Process_Standards:
    Codex_Two_Phase: PHASE 1 recon before edits; PHASE 2 implement only after plan accepted. Sources: [SRC-101, SRC-108]
    Claims_and_Evidence_Level:
* Claim_1: A “State Layer” producing `StateSpan` + `StateEdge` reduces LLM token-recall reliance and improves temporal coherence. Evidence_Level: [INFERENCE] Sources: [SRC-008]
* Claim_2: First-class `EvidenceRef` + `ProvenanceRecord` makes answers citable/debuggable by construction. Evidence_Level: [INFERENCE] Sources: [SRC-009]
* Claim_3: Baseline “JEPA-like” state builder can ship without training; optional JEPA training may improve prediction-error/sequence modeling. Evidence_Level: [INFERENCE] Sources: [SRC-010]
* Claim_4: Latency/accuracy wins are workload-dependent and require local benchmarks. Evidence_Level: [NO EVIDENCE] Sources: [SRC-011]
  Source_Index:
* SRC-001:
  Type: Requirement
  Priority: MUST
  Quote: "Add a **State Layer** to Autocapture: deterministic, versioned `state_tape` derived from captures with strict provenance."
  Notes: Introduces new deterministic, versioned timeline layer.
* SRC-002:
  Type: Requirement
  Priority: MUST
  Quote: "Introduce **plugin types** for state-building, indexing, retrieval, and evidence compilation"
  Notes: Requires new plugin categories.
* SRC-003:
  Type: Constraint
  Priority: MUST
  Quote: "baseline works without training; JEPA-training is optional"
  Notes: Baseline must ship without training; training is optional.
* SRC-004:
  Type: Requirement
  Priority: MUST
  Quote: "Define **data contracts**: `EvidenceRef`, `ProvenanceRecord`, `StateSpan`, `StateEdge`, and `QueryEvidenceBundle`."
  Notes: Contracts are required and central.
* SRC-005:
  Type: Requirement
  Priority: MUST
  Quote: "Extend storage: SQLite tables + optional pluggable vector index; strict content-addressed IDs for cache + reproducibility."
  Notes: State storage + vector search optional + content addressing.
* SRC-006:
  Type: Requirement
  Priority: MUST
  Quote: "Add a **retrieval API** and **LLM prompt contract** that enforces citation-by-construction (no evidence → no answer)."
  Notes: Evidence-only retrieval and LLM contract.
* SRC-007:
  Type: Requirement
  Priority: MUST
  Quote: "Provide a **Codex verification prompt** to enumerate required code/schema changes before any edits."
  Notes: Deliver a pre-edit recon prompt.
* SRC-008:
  Type: Data
  Priority: INFO
  Quote: "A “State Layer” that produces compact `StateSpan` embeddings + `StateEdge` transitions reduces LLM reliance on token recall"
  Notes: Labeled [INFERENCE] in source.
* SRC-009:
  Type: Data
  Priority: INFO
  Quote: "Enforcing a first-class `EvidenceRef` + `ProvenanceRecord` on every derived artifact makes answers citable and debuggable"
  Notes: Labeled [INFERENCE] in source.
* SRC-010:
  Type: Data
  Priority: INFO
  Quote: "A baseline “JEPA-like” state builder can ship without training"
  Notes: Labeled [INFERENCE] in source.
* SRC-011:
  Type: Data
  Priority: INFO
  Quote: "Quantitative wins (latency/accuracy) are workload-dependent and require local benchmarks"
  Notes: Labeled [NO EVIDENCE] in source.
* SRC-012:
  Type: Data
  Priority: MUST
  Quote: "screenshots / window metadata / input events"
  Notes: Capture inputs.
* SRC-013:
  Type: Constraint
  Priority: MUST
  Quote: "[Artifact Store]  (encrypted, append-only)"
  Notes: Artifact store properties.
* SRC-014:
  Type: Data
  Priority: MUST
  Quote: "[Extraction Layer]  (OCR, UI hints, region embeddings)"
  Notes: Extraction outputs feeding state builder.
* SRC-015:
  Type: Requirement
  Priority: MUST
  Quote: "[STATE LAYER]  (new)  --> produces: StateSpan(z_t), StateEdge(Δ, err)"
  Notes: State layer outputs.
* SRC-016:
  Type: Data
  Priority: MUST
  Quote: "[Index Layer]  (text + vector + metadata)"
  Notes: Downstream indexing layer.
* SRC-017:
  Type: Behavior
  Priority: MUST
  Quote: "[Query + LLM Orchestrator] - retrieval over state tape - evidence bundle assembly - response with citations"
  Notes: Orchestrator responsibilities.
* SRC-018:
  Type: Requirement
  Priority: MUST
  Quote: "Capture artifacts with stable IDs; retention policies; encrypted at rest"
  Notes: Capture/storage contract.
* SRC-019:
  Type: Constraint
  Priority: MUST
  Quote: "Silent egress of raw media/text by default"
  Notes: Must not happen.
* SRC-020:
  Type: Requirement
  Priority: MUST
  Quote: "Run plugins deterministically over immutable artifacts; idempotent reprocessing"
  Notes: Deterministic/idempotent pipeline.
* SRC-021:
  Type: Constraint
  Priority: MUST
  Quote: "Non-versioned derived outputs (no “mystery state”)"
  Notes: Must not exist.
* SRC-022:
  Type: Requirement
  Priority: MUST
  Quote: "Attach evidence + provenance to **every** derived object"
  Notes: Applies to all derived artifacts.
* SRC-023:
  Type: Constraint
  Priority: MUST
  Quote: "Produce embeddings/labels without a trace back to media/time"
  Notes: Must not occur.
* SRC-024:
  Type: Requirement
  Priority: MUST
  Quote: "Maintain an append-only timeline of `StateSpan` + `StateEdge`"
  Notes: Append-only `state_tape`.
* SRC-025:
  Type: Constraint
  Priority: MUST
  Quote: "Hide state inside the LLM prompt only"
  Notes: Must not hide state only in prompt.
* SRC-026:
  Type: Requirement
  Priority: MUST
  Quote: "Provide structured retrieval returning `QueryEvidenceBundle`"
  Notes: Query API contract.
* SRC-027:
  Type: Constraint
  Priority: MUST
  Quote: "Let the LLM “browse” raw store directly"
  Notes: Must not be allowed.
* SRC-028:
  Type: Requirement
  Priority: MUST
  Quote: "Enforce app allow/deny, redaction, egress policy at the platform boundary"
  Notes: Policy enforcement requirement.
* SRC-029:
  Type: Constraint
  Priority: MUST
  Quote: "Let plugins bypass policy controls"
  Notes: Must not be allowed.
* SRC-030:
  Type: Requirement
  Priority: MUST
  Quote: "`StateBuilderPlugin` ... Build `StateSpan` + `StateEdge` from extracted features"
  Notes: New plugin type and purpose.
* SRC-031:
  Type: Constraint
  Priority: MUST
  Quote: "Fixed config hash; stable pooling; content-address IDs"
  Notes: Determinism requirements for state building.
* SRC-032:
  Type: Data
  Priority: MUST
  Quote: "`ExtractBatch` → `StateTapeBatch`"
  Notes: State builder IO.
* SRC-033:
  Type: Requirement
  Priority: COULD
  Quote: "`VectorIndexPlugin` (optional) ... Provide ANN search over state embeddings"
  Notes: Optional plugin type.
* SRC-034:
  Type: Constraint
  Priority: MUST
  Quote: "Deterministic build or versioned index snapshots"
  Notes: Determinism requirement for vector index.
* SRC-035:
  Type: Data
  Priority: MUST
  Quote: "`StateSpan[]` ↔ `topK(StateSpan)`"
  Notes: Vector index IO.
* SRC-036:
  Type: Requirement
  Priority: MUST
  Quote: "`EvidenceCompilerPlugin` ... Compile minimal evidence for a query hit"
  Notes: Evidence compilation plugin required.
* SRC-037:
  Type: Constraint
  Priority: MUST
  Quote: "Evidence selection rules fixed + versioned"
  Notes: Determinism for evidence compilation.
* SRC-038:
  Type: Data
  Priority: MUST
  Quote: "`StateSpanHit[]` → `QueryEvidenceBundle`"
  Notes: Evidence compiler IO.
* SRC-039:
  Type: Requirement
  Priority: COULD
  Quote: "`WorkflowMinerPlugin` (optional) ... Cluster repeated sequences into workflows"
  Notes: Optional workflow mining.
* SRC-040:
  Type: Constraint
  Priority: MUST
  Quote: "Versioned model + seed"
  Notes: Determinism requirement for workflow mining.
* SRC-041:
  Type: Data
  Priority: MUST
  Quote: "`StateTape` → `WorkflowDefs`"
  Notes: Workflow miner IO.
* SRC-042:
  Type: Requirement
  Priority: COULD
  Quote: "`AnomalyPlugin` (optional) ... flag surprises"
  Notes: Optional anomaly detection.
* SRC-043:
  Type: Constraint
  Priority: MUST
  Quote: "Thresholds versioned + tested"
  Notes: Determinism requirement for anomaly plugin.
* SRC-044:
  Type: Data
  Priority: MUST
  Quote: "`StateEdge.err` → `Alerts`"
  Notes: Anomaly plugin IO.
* SRC-045:
  Type: Data
  Priority: MUST
  Quote: "type PluginId = string;         // e.g., "state.jepa_like.v1""
  Notes: PluginId type.
* SRC-046:
  Type: Data
  Priority: MUST
  Quote: "type SemVer = string;           // e.g., "1.3.0""
  Notes: Versioning type.
* SRC-047:
  Type: Requirement
  Priority: MUST
  Quote: "interface AutocapturePlugin {"
  Notes: Base plugin interface exists; see full code block in source.
* SRC-048:
  Type: Constraint
  Priority: MUST
  Quote: "output IDs are derived from (inputs + plugin + config + model_version)"
  Notes: Deterministic identity rule.
* SRC-049:
  Type: Requirement
  Priority: COULD
  Quote: "getConfigSchema?(): object; ... getOutputSchema?(): object;"
  Notes: Optional JSON schema hooks.
* SRC-050:
  Type: Data
  Priority: INFO
  Quote: "language-agnostic shape; implement in your runtime of choice"
  Notes: Repository runtime is not specified in sources.
* SRC-051:
  Type: Data
  Priority: MUST
  Quote: ""EvidenceRef": {"
  Notes: Full EvidenceRef contract provided in source section 3.1.
* SRC-052:
  Type: Data
  Priority: MUST
  Quote: ""ProvenanceRecord": {"
  Notes: Full ProvenanceRecord contract provided in source section 3.1.
* SRC-053:
  Type: Constraint
  Priority: MUST
  Quote: "no derived object is persisted without both `EvidenceRef[]` and `ProvenanceRecord`."
  Notes: Persistence invariant.
* SRC-054:
  Type: Data
  Priority: MUST
  Quote: ""StateSpan": {"
  Notes: Full StateSpan contract provided in source section 3.2.
* SRC-055:
  Type: Data
  Priority: MUST
  Quote: ""StateEdge": {"
  Notes: Full StateEdge contract provided in source section 3.2.
* SRC-056:
  Type: Data
  Priority: MUST
  Quote: "`StateSpan` is the “what’s true during this time range”."
  Notes: Semantics of span.
* SRC-057:
  Type: Data
  Priority: MUST
  Quote: "`StateEdge` is the “what changed + how surprising was it”."
  Notes: Semantics of edge.
* SRC-058:
  Type: Data
  Priority: MUST
  Quote: ""QueryEvidenceBundle": {"
  Notes: Full QueryEvidenceBundle contract provided in source section 3.3.
* SRC-059:
  Type: Constraint
  Priority: MUST
  Quote: "LLM sees only `QueryEvidenceBundle` + explicitly permitted payloads."
  Notes: LLM input restriction invariant.
* SRC-060:
  Type: Requirement
  Priority: MUST
  Quote: "SQLite tables (minimal viable schema)"
  Notes: Minimal state-layer DB schema required.
* SRC-061:
  Type: Data
  Priority: MUST
  Quote: "CREATE TABLE state_span ("
  Notes: Full `state_span` schema provided.
* SRC-062:
  Type: Data
  Priority: MUST
  Quote: "CREATE TABLE state_edge ("
  Notes: Full `state_edge` schema provided.
* SRC-063:
  Type: Data
  Priority: MUST
  Quote: "CREATE TABLE state_evidence_link ("
  Notes: Full `state_evidence_link` schema provided.
* SRC-064:
  Type: Requirement
  Priority: MUST
  Quote: "CREATE INDEX idx_state_span_time ON state_span(ts_start_ms, ts_end_ms);"
  Notes: Index requirements; see full block for others.
* SRC-065:
  Type: Requirement
  Priority: MUST
  Quote: "Default implementation: `LinearScanVectorIndex` (no dependencies; slower but deterministic)."
  Notes: Baseline vector search implementation.
* SRC-066:
  Type: Requirement
  Priority: COULD
  Quote: "Optional implementation: `HNSWVectorIndex` (faster; must be versioned and reproducibly built)."
  Notes: Optional faster vector index with determinism requirements.
* SRC-067:
  Type: Constraint
  Priority: MUST
  Quote: "index stores `(state_id, embedding_hash, model_version)` so stale embeddings cannot be queried."
  Notes: Vector index staleness prevention.
* SRC-068:
  Type: Requirement
  Priority: MUST
  Quote: "Baseline “JEPA-like” (ships first, no training required)"
  Notes: Baseline state builder requirement.
* SRC-069:
  Type: Data
  Priority: MUST
  Quote: "region-level vision embeddings ... OCR text + text embeddings ... app/window metadata"
  Notes: Baseline inputs; input events optional elsewhere.
* SRC-070:
  Type: Requirement
  Priority: MUST
  Quote: "StateSpan windowing: fixed duration (e.g., 3–10s) OR heuristic boundary when app/window changes."
  Notes: Deterministic windowing strategies.
* SRC-071:
  Type: Requirement
  Priority: MUST
  Quote: "region embeddings pooled by fixed rule (mean, with optional weights by ROI type)"
  Notes: Deterministic vision pooling.
* SRC-072:
  Type: Requirement
  Priority: MUST
  Quote: "text embedding pooled by fixed rule (mean over tokens above confidence threshold)"
  Notes: Deterministic text pooling.
* SRC-073:
  Type: Requirement
  Priority: MUST
  Quote: "project to fixed dim (deterministic linear layer or fixed PCA matrix shipped with build)"
  Notes: Deterministic projection.
* SRC-074:
  Type: Requirement
  Priority: MUST
  Quote: "`Δz_t = z_t - z_(t-1)`"
  Notes: Baseline edge delta.
* SRC-075:
  Type: Requirement
  Priority: MUST
  Quote: "`pred_error = 1 - cosine(z_t, z_(t-1))`"
  Notes: Baseline surprise metric.
* SRC-076:
  Type: Requirement
  Priority: COULD
  Quote: "Optional: true JEPA-style training"
  Notes: Optional training upgrade.
* SRC-077:
  Type: Behavior
  Priority: COULD
  Quote: "context encoder produces `z_ctx`"
  Notes: Training architecture component.
* SRC-078:
  Type: Behavior
  Priority: COULD
  Quote: "loss = `MSE(z_pred, stopgrad(z_tgt))`"
  Notes: Training loss definition.
* SRC-079:
  Type: Requirement
  Priority: MUST
  Quote: "training runs locally and writes `model_version` + `training_run_id`"
  Notes: Training boundary requirements.
* SRC-080:
  Type: Constraint
  Priority: MUST
  Quote: "only load signed/approved model artifacts"
  Notes: Inference gate requirement.
* SRC-081:
  Type: Requirement
  Priority: MUST
  Quote: "Retrieval sequence (hard requirement)"
  Notes: Query+LLM sequence must be implemented.
* SRC-082:
  Type: Requirement
  Priority: MUST
  Quote: "parse user question → structured query (time/app/entity filters)"
  Notes: Structured query parse requirement.
* SRC-083:
  Type: Requirement
  Priority: MUST
  Quote: "retrieve `StateSpan` hits (vector + metadata)"
  Notes: Retrieval step.
* SRC-084:
  Type: Requirement
  Priority: MUST
  Quote: "expand to neighbor edges for continuity (`StateEdge` graph walk)"
  Notes: Continuity expansion.
* SRC-085:
  Type: Requirement
  Priority: MUST
  Quote: "compile `QueryEvidenceBundle`"
  Notes: Evidence bundle assembly.
* SRC-086:
  Type: Requirement
  Priority: MUST
  Quote: "generate answer with inline citations referencing `EvidenceRef.media_id + ts`"
  Notes: Citation formatting requirement.
* SRC-087:
  Type: Requirement
  Priority: MUST
  Quote: "If `QueryEvidenceBundle.hits` is empty → respond “no evidence”."
  Notes: No-evidence behavior.
* SRC-088:
  Type: Constraint
  Priority: MUST
  Quote: "answer must be based on permitted summaries only and explicitly state that limitation."
  Notes: Policy-limited answer requirement.
* SRC-089:
  Type: Requirement
  Priority: MUST
  Quote: "Deterministic caching key: `hash(plugin_id, plugin_version, model_version, config_hash, input_artifact_ids[])`"
  Notes: Cache key contract.
* SRC-090:
  Type: Requirement
  Priority: SHOULD
  Quote: "Incremental processing: only new captures produce new `StateSpan`"
  Notes: Performance recommendation.
* SRC-091:
  Type: Requirement
  Priority: SHOULD
  Quote: "Query path: ANN/linear scan over `z_t` + narrow by time/app"
  Notes: Recommended query flow.
* SRC-092:
  Type: Constraint
  Priority: MUST
  Quote: "LLM can’t invent timeline without evidence bundle"
  Notes: Evidence gating for accuracy.
* SRC-093:
  Type: Requirement
  Priority: SHOULD
  Quote: "`StateEdge.pred_error` enables anomaly surfacing and “what changed” queries"
  Notes: Recommended usage of pred_error.
* SRC-094:
  Type: Requirement
  Priority: COULD
  Quote: "Optional workflow mining improves repeated-task recall without storing more raw text"
  Notes: Optional feature.
* SRC-095:
  Type: Constraint
  Priority: MUST
  Quote: "Default local-only; encrypted artifact store; embeddings treated as sensitive derived data"
  Notes: Security posture.
* SRC-096:
  Type: Constraint
  Priority: MUST
  Quote: "Policy gate sits between retrieval and LLM"
  Notes: Enforced boundary.
* SRC-097:
  Type: Constraint
  Priority: MUST
  Quote: "Optional export modes are explicit and logged (no silent egress)"
  Notes: Export control requirement.
* SRC-098:
  Type: Constraint
  Priority: MUST
  Quote: "every `StateSpan/Edge` stores `EvidenceRef[]`"
  Notes: Evidence required on state objects.
* SRC-099:
  Type: Requirement
  Priority: MUST
  Quote: "answer template requires citing evidence IDs/timestamps"
  Notes: Prompt/answer contract requirement.
* SRC-100:
  Type: Constraint
  Priority: MUST
  Quote: "WITHOUT making changes until you first verify what must change."
  Notes: Codex pre-edit recon requirement.
* SRC-101:
  Type: Requirement
  Priority: MUST
  Quote: "PHASE 1 — RECON (no code changes):"
  Notes: Phase 1 definition.
* SRC-102:
  Type: Requirement
  Priority: MUST
  Quote: "Identify current pipeline stages and extension points:"
  Notes: Recon must inventory stages.
* SRC-103:
  Type: Requirement
  Priority: MUST
  Quote: "Locate:"
  Notes: Recon must locate key subsystems; full list in prompt.
* SRC-104:
  Type: Requirement
  Priority: MUST
  Quote: "Produce an inventory:"
  Notes: Recon inventory required.
* SRC-105:
  Type: Requirement
  Priority: MUST
  Quote: "map it to one of these new components:"
  Notes: Map changes to new components list.
* SRC-106:
  Type: Requirement
  Priority: MUST
  Quote: "List risks:"
  Notes: Must list risks (perf/security/determinism/migration).
* SRC-107:
  Type: Requirement
  Priority: MUST
  Quote: "Output of PHASE 1 must be:"
  Notes: Must produce change plan, test plan, rollout plan with flags.
* SRC-108:
  Type: Constraint
  Priority: MUST
  Quote: "PHASE 2 — IMPLEMENT (only after plan is accepted):"
  Notes: Implementation gate.
* SRC-109:
  Type: Requirement
  Priority: MUST
  Quote: "Implement minimal baseline (no training required):"
  Notes: Baseline implementation scope.
* SRC-110:
  Type: Requirement
  Priority: MUST
  Quote: "Create new DB tables and migration"
  Notes: Migration required.
* SRC-111:
  Type: Requirement
  Priority: MUST
  Quote: "Add StateLayer stage to pipeline"
  Notes: Pipeline stage required.
* SRC-112:
  Type: Requirement
  Priority: MUST
  Quote: "Implement baseline StateBuilderPlugin:"
  Notes: Baseline builder required; details enumerated in prompt.
* SRC-113:
  Type: Requirement
  Priority: MUST
  Quote: "Implement retrieval API to return QueryEvidenceBundle"
  Notes: Retrieval API required.
* SRC-114:
  Type: Requirement
  Priority: MUST
  Quote: "Update LLM orchestrator to require evidence bundle"
  Notes: Orchestrator changes required.
* SRC-115:
  Type: Requirement
  Priority: MUST
  Quote: "Add tests:"
  Notes: Test additions required; details enumerated in prompt.
* SRC-116:
  Type: Constraint
  Priority: MUST
  Quote: "Do not introduce new heavy dependencies unless already present."
  Notes: Dependency constraint.
* SRC-117:
  Type: Requirement
  Priority: SHOULD
  Quote: "Prefer pure code / existing libraries already in repo."
  Notes: Strong preference.
* SRC-118:
  Type: Constraint
  Priority: MUST
  Quote: "Stop immediately if any regression is detected; do not ship."
  Notes: Release gate.
* SRC-119:
  Type: Constraint
  Priority: MUST
  Quote: "Any missing `EvidenceRef`/`ProvenanceRecord` ⇒ DO_NOT_SHIP"
  Notes: Hard gate.
* SRC-120:
  Type: Data
  Priority: SHOULD
  Quote: "storage growth budget; query p95 latency budget"
  Notes: Budget values not provided.
* SRC-121:
  Type: Constraint
  Priority: MUST
  Quote: "Ingestion latency regression > budget ⇒ DO_NOT_SHIP"
  Notes: Requires defining a budget.
* SRC-122:
  Type: Constraint
  Priority: MUST
  Quote: "determinism test failure ⇒ DO_NOT_SHIP"
  Notes: Hard gate.
* SRC-123:
  Type: Constraint
  Priority: MUST
  Quote: "Any answer without evidence IDs when hits exist ⇒ DO_NOT_SHIP"
  Notes: Hard gate.
* SRC-124:
  Type: Requirement
  Priority: MUST
  Quote: "“no evidence” path covered by tests"
  Notes: Must test no-evidence path.
* SRC-125:
  Type: Constraint
  Priority: MUST
  Quote: "Model version mismatch or unsigned model loaded ⇒ DO_NOT_SHIP"
  Notes: Training/inference hard gate.
* SRC-126:
  Type: Constraint
  Priority: MUST
  Quote: "accuracy eval regression on golden set ⇒ DO_NOT_SHIP"
  Notes: Requires defining golden set and eval.
* SRC-127:
  Type: Constraint
  Priority: MUST
  Quote: "DETERMINISM: PARTIAL (scoped)"
  Notes: Determinism is partial by design/scope.
* SRC-128:
  Type: Data
  Priority: MUST
  Quote: "VERIFIED for: schema/contracts; provenance rules; caching keys; evidence bundle structure."
  Notes: Verified deterministic components.
* SRC-129:
  Type: Constraint
  Priority: MUST
  Quote: "PARTIAL for: embedding/model inference unless forced to CPU deterministic mode and seeded"
  Notes: Determinism caveat for inference.
* SRC-130:
  Type: Constraint
  Priority: MUST
  Quote: "optional ANN index build unless snapshot/versioned"
  Notes: Determinism caveat for ANN.
* SRC-131:
  Type: Data
  Priority: MUST
  Quote: "TS: 2026-01-31T12:09:15 America/Denver"
  Notes: Source timestamp.
* SRC-132:
  Type: Data
  Priority: MUST
  Quote: "THREAD: 2026-01-31_autocapture-jepa-blueprint"
  Notes: Source thread id.
* SRC-133:
  Type: Data
  Priority: MUST
  Quote: "CHAT_ID: 20260131_autocapture-jepa-blueprint"
  Notes: Source chat id.
  Coverage_Map:
* SRC-001: [MOD-005, ADR-0010, Section1.Architectural_Hard_Rules.State_Layer_Existence]
* SRC-002: [MOD-008, MOD-009, MOD-011, MOD-012, ADR-0012, Section1.Architectural_Hard_Rules.Plugin_Extension_Model]
* SRC-003: [MOD-008, MOD-017, ADR-0016, Section1.Architectural_Hard_Rules.Plugin_Extension_Model]
* SRC-004: [MOD-007, ADR-0011]
* SRC-005: [MOD-006, MOD-009, MOD-010, MOD-018, ADR-0013, ADR-0014, Section1.Architectural_Hard_Rules.Storage_Baseline]
* SRC-006: [MOD-012, MOD-014, ADR-0015, Section1.Architectural_Hard_Rules.No_Evidence_No_Answer]
* SRC-007: [MOD-022, ADR-0019]
* SRC-008: [ADR-0010]
* SRC-009: [ADR-0011]
* SRC-010: [ADR-0016]
* SRC-011: [ADR-0019]
* SRC-012: [MOD-001, Section1.Environment_Standards.Data_Stores.Artifact_Store]
* SRC-013: [MOD-002, ADR-0018, Section1.Environment_Standards.Data_Stores.Artifact_Store.Properties]
* SRC-014: [MOD-003, MOD-008]
* SRC-015: [MOD-005, MOD-008, ADR-0010]
* SRC-016: [MOD-009, ADR-0014]
* SRC-017: [MOD-014, ADR-0015]
* SRC-018: [MOD-002, ADR-0018, Section1.Architectural_Hard_Rules.Storage_Baseline]
* SRC-019: [MOD-013, MOD-014, ADR-0018]
* SRC-020: [MOD-004, MOD-018, ADR-0017]
* SRC-021: [MOD-004, ADR-0017]
* SRC-022: [MOD-007, MOD-008, MOD-011, ADR-0011]
* SRC-023: [MOD-007, ADR-0011]
* SRC-024: [MOD-006, MOD-005, ADR-0010]
* SRC-025: [MOD-005, MOD-014, ADR-0015]
* SRC-026: [MOD-012, ADR-0015]
* SRC-027: [MOD-012, MOD-014, ADR-0015]
* SRC-028: [MOD-013, ADR-0018]
* SRC-029: [MOD-004, MOD-013, ADR-0018]
* SRC-030: [MOD-008, ADR-0012]
* SRC-031: [MOD-008, MOD-018, ADR-0017]
* SRC-032: [MOD-008]
* SRC-033: [MOD-010, ADR-0014]
* SRC-034: [MOD-009, MOD-010, ADR-0014]
* SRC-035: [MOD-009, MOD-010]
* SRC-036: [MOD-011, ADR-0012]
* SRC-037: [MOD-011, ADR-0012]
* SRC-038: [MOD-011, MOD-012]
* SRC-039: [MOD-015]
* SRC-040: [MOD-015]
* SRC-041: [MOD-015]
* SRC-042: [MOD-016]
* SRC-043: [MOD-016]
* SRC-044: [MOD-016]
* SRC-045: [MOD-008, ADR-0012]
* SRC-046: [MOD-008, ADR-0012]
* SRC-047: [MOD-008, MOD-009, MOD-011, ADR-0012]
* SRC-048: [MOD-018, ADR-0017]
* SRC-049: [MOD-008, MOD-009, MOD-011]
* SRC-050: [Section1.Environment_Standards.Repository_Runtime]
* SRC-051: [MOD-007]
* SRC-052: [MOD-007]
* SRC-053: [MOD-007, MOD-006, MOD-020, ADR-0011]
* SRC-054: [MOD-007, MOD-006, MOD-008]
* SRC-055: [MOD-007, MOD-006, MOD-008]
* SRC-056: [ADR-0010]
* SRC-057: [ADR-0010]
* SRC-058: [MOD-007, MOD-011, MOD-012]
* SRC-059: [MOD-014, ADR-0015]
* SRC-060: [MOD-019, ADR-0013]
* SRC-061: [MOD-006, MOD-019]
* SRC-062: [MOD-006, MOD-019]
* SRC-063: [MOD-006, MOD-019]
* SRC-064: [MOD-006, MOD-019]
* SRC-065: [MOD-009, ADR-0014]
* SRC-066: [MOD-010, ADR-0014]
* SRC-067: [MOD-009, MOD-010, ADR-0014]
* SRC-068: [MOD-008, ADR-0016]
* SRC-069: [MOD-008]
* SRC-070: [MOD-008, Section4.Sample_Table_STATE_SPAN_WINDOWING]
* SRC-071: [MOD-008, Section4.Sample_Table_Z_POOLING]
* SRC-072: [MOD-008, Section4.Sample_Table_Z_POOLING]
* SRC-073: [MOD-008]
* SRC-074: [MOD-008, Section4.Sample_Table_STATE_EDGE]
* SRC-075: [MOD-008, MOD-016, Section4.Sample_Table_STATE_EDGE]
* SRC-076: [MOD-017]
* SRC-077: [MOD-017]
* SRC-078: [MOD-017]
* SRC-079: [MOD-017]
* SRC-080: [MOD-017, ADR-0016]
* SRC-081: [MOD-012, MOD-014, ADR-0015]
* SRC-082: [MOD-012]
* SRC-083: [MOD-012, MOD-009]
* SRC-084: [MOD-012]
* SRC-085: [MOD-011, MOD-012]
* SRC-086: [MOD-014, Section4.Sample_Table_LLM_CITATIONS]
* SRC-087: [MOD-014, MOD-020]
* SRC-088: [MOD-013, MOD-014, Section4.Sample_Table_POLICY_GATE]
* SRC-089: [MOD-018, MOD-004]
* SRC-090: [MOD-005]
* SRC-091: [MOD-012, MOD-009]
* SRC-092: [MOD-014, ADR-0015]
* SRC-093: [MOD-016]
* SRC-094: [MOD-015]
* SRC-095: [MOD-002, MOD-013, ADR-0018]
* SRC-096: [MOD-013, MOD-014]
* SRC-097: [MOD-013, MOD-020]
* SRC-098: [MOD-008, MOD-006, ADR-0011]
* SRC-099: [MOD-014]
* SRC-100: [MOD-022]
* SRC-101: [MOD-022]
* SRC-102: [MOD-022]
* SRC-103: [MOD-022]
* SRC-104: [MOD-022]
* SRC-105: [MOD-022]
* SRC-106: [MOD-022]
* SRC-107: [MOD-021, MOD-022]
* SRC-108: [MOD-022]
* SRC-109: [MOD-022]
* SRC-110: [MOD-019, MOD-022]
* SRC-111: [MOD-005, MOD-022]
* SRC-112: [MOD-008, MOD-022]
* SRC-113: [MOD-012, MOD-022]
* SRC-114: [MOD-014, MOD-022]
* SRC-115: [MOD-020, MOD-022]
* SRC-116: [Section1.Architectural_Hard_Rules.Dependency_Discipline]
* SRC-117: [Section1.Architectural_Hard_Rules.Dependency_Discipline]
* SRC-118: [MOD-020, ADR-0019]
* SRC-119: [MOD-020, ADR-0019]
* SRC-120: [MOD-020]
* SRC-121: [MOD-020]
* SRC-122: [MOD-020]
* SRC-123: [MOD-020]
* SRC-124: [MOD-020]
* SRC-125: [MOD-017, MOD-020]
* SRC-126: [MOD-017, MOD-020]
* SRC-127: [ADR-0020]
* SRC-128: [ADR-0020]
* SRC-129: [ADR-0020]
* SRC-130: [ADR-0020]
* SRC-131: [Section1.Environment_Standards.Determinism_Standards.Determinism_Scope]
* SRC-132: [Section1.Environment_Standards.Determinism_Standards.Determinism_Scope]
* SRC-133: [Section1.Environment_Standards.Determinism_Standards.Determinism_Scope]
  Validation_Checklist:
* All four top-level sections are present and ordered correctly.
* No deferral markers; only explicit "N/A" where source omits a value.
* Every module and ADR includes a Sources list.
* Source_Index has stable SRC-### IDs with <=25-word quotes.
* Coverage_Map lists every SRC-### exactly once.
* Every logic-heavy module has a 3-row sample table in Section 4.
* DO_NOT_SHIP gates are explicitly encoded as tests/checks.

# 2. Functional Modules & Logic

Functional_Modules:

Module_Index:
* MOD-001: autocapture_nx/capture/pipeline.py
* MOD-002: plugins/builtin/storage_sqlcipher/plugin.py, autocapture_nx/kernel/metadata_store.py
* MOD-003: autocapture_nx/processing/sst/pipeline.py, autocapture_nx/processing/sst/stage_plugins.py
* MOD-004: autocapture_nx/processing/sst/pipeline.py, autocapture_nx/plugin_system/registry.py
* MOD-005: autocapture_nx/state_layer/processor.py, autocapture_nx/processing/idle.py
* MOD-006: autocapture_nx/state_layer/store_sqlite.py
* MOD-007: autocapture_nx/state_layer/contracts.py, contracts/state_layer.schema.json
* MOD-008: autocapture_nx/state_layer/builder_jepa.py
* MOD-009: autocapture_nx/state_layer/vector_index.py
* MOD-010: autocapture_nx/state_layer/vector_index_hnsw.py
* MOD-011: autocapture_nx/state_layer/evidence_compiler.py
* MOD-012: autocapture_nx/state_layer/retrieval.py, autocapture_nx/kernel/query.py, autocapture/web/routes/query.py
* MOD-013: autocapture_nx/state_layer/policy_gate.py
* MOD-014: autocapture_nx/kernel/query.py, plugins/builtin/answer_basic/plugin.py
* MOD-015: autocapture_nx/state_layer/workflow_miner.py
* MOD-016: autocapture_nx/state_layer/anomaly.py
* MOD-017: autocapture_nx/state_layer/jepa_training.py
* MOD-018: autocapture_nx/state_layer/ids.py
* MOD-019: autocapture_nx/state_layer/store_sqlite.py (schema/migration)
* MOD-020: tests/test_state_layer_*.py, tools/state_layer_eval.py, tools/gate_pillars.py
* MOD-021: config/default.json, contracts/config_schema.json
* MOD-022: promptops/prompts/codex_state_layer_verify.txt

* Object_ID: MOD-001
  Object_Name: Capture Sources Ingestion
  Object_Type: Other
  Priority: MUST
  Primary_Purpose: Ingest capture sources (screenshots, window metadata, input events) into the artifact store with stable IDs and retention policies.
  Sources: [SRC-012, SRC-018]
  Interface_Definition:

  ```text
  Inputs:
    - screenshots
    - window metadata
    - input events
  Outputs:
    - persisted capture artifacts with stable IDs (artifact_id format: `{run_id}/{kind}/{seq}` for evidence, `{run_id}/derived.*` for derived; components encoded via `encode_record_id_component`)
  Constraints:
    - artifacts encrypted at rest
    - retention policies applied (policy format: `storage.retention` with `evidence: "infinite"` or duration; `interval_s`, `max_delete_per_run`, `record_batches`)
  ```

* Object_ID: MOD-002
  Object_Name: Artifact Store Boundary
  Object_Type: Data Store
  Priority: MUST
  Primary_Purpose: Store raw capture artifacts as encrypted, append-only content with stable IDs and retention; prevent silent egress of raw media/text by default.
  Sources: [SRC-013, SRC-018, SRC-019, SRC-095]
  Interface_Definition:

  ```text
  Storage Properties (non-negotiable):
    - encrypted: true
    - append_only: true
    - retention_policies: supported
    - silent_egress_default: forbidden

  API Surface: `storage.metadata` (get/put/put_new/put_batch/keys) + `storage.media` (get/put/put_new/put_path/put_stream) (existing NX store interfaces)
  ```

* Object_ID: MOD-003
  Object_Name: Extraction Layer
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Produce extracted features required by State Layer (OCR text, UI hints, region embeddings) from immutable artifacts.
  Sources: [SRC-014, SRC-020]
  Interface_Definition:

  ```text
  Inputs:
    - immutable artifacts from Artifact Store
  Outputs (minimum set):
    - OCR text
    - UI hints
    - region embeddings

  ExtractBatch Schema: `{ "session_id": string, "states": [derived.sst.state records including screen_state, tokens, image_sha256, frame_id] }` (must contain identifiers to build EvidenceRef/Provenance)
  ```

* Object_ID: MOD-004
  Object_Name: Pipeline Orchestrator Deterministic Execution
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Run plugins deterministically over immutable artifacts with idempotent reprocessing; prevent non-versioned derived outputs.
  Sources: [SRC-020, SRC-021, SRC-047, SRC-089]
  Interface_Definition:

  ```text
  Responsibilities:
    - execute plugin.process(batch) deterministically
    - compute deterministic cache keys for plugin batches
    - support idempotent reprocessing: same inputs+config -> same outputs
    - reject or quarantine derived outputs that are not versioned

  Pipeline Stage Enumeration: ingest.frame, temporal.segment, preprocess.normalize, preprocess.tile, ocr.onnx, vision.vlm, layout.assemble, extract.table, extract.spreadsheet, extract.code, extract.chart, ui.parse, track.cursor, build.state, match.ids, build.delta, infer.action, compliance.redact, persist.bundle, index.text
  ```

* Object_ID: MOD-005
  Object_Name: State Layer Pipeline Stage
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Insert a new State Layer stage after Extraction Layer to generate and persist an append-only `state_tape` composed of `StateSpan` and `StateEdge`.
  Sources: [SRC-001, SRC-015, SRC-024, SRC-111]
  Interface_Definition:

  ```text
  Stage Position:
    - input: ExtractBatch from Extraction Layer
    - output: persisted StateTapeBatch (StateSpan[] + StateEdge[] + evidence links)

  Stage Contract:
    - calls configured StateBuilderPlugin.process(ExtractBatch) -> StateTapeBatch
    - persists StateSpan and StateEdge into SQLite StateTapeStore
    - enforces evidence+provenance invariant before persistence
    - append-only: no UPDATE/DELETE of state objects (exception policy: none; checkpoints are separate metadata records)
  ```

* Object_ID: MOD-006
  Object_Name: State Tape Store SQLite
  Object_Type: Data Store
  Priority: MUST
  Primary_Purpose: Persist `StateSpan` and `StateEdge` (and their evidence links) using the minimal viable SQLite schema.
  Sources: [SRC-060, SRC-061, SRC-062, SRC-063, SRC-064, SRC-024]
  Interface_Definition:

  ```sql
  -- State-layer additions

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

  ```text
  Evidence Persistence Encoding:
    - evidence_json representation: canonical JSON via `json.dumps(ref, sort_keys=True)`
    - linkage cardinality (rows per state object): one row per EvidenceRef per state object
  ```

* Object_ID: MOD-007
  Object_Name: Evidence and Provenance Contracts Validator
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Define and enforce the data contracts (`EvidenceRef`, `ProvenanceRecord`, `StateSpan`, `StateEdge`, `QueryEvidenceBundle`) and enforce the invariant that no derived object is persisted without evidence+provenance.
  Sources: [SRC-004, SRC-051, SRC-052, SRC-053, SRC-054, SRC-055, SRC-058, SRC-059]
  Interface_Definition:

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
    },
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
    },
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

  ```text
  Invariants:
    - Derived persistence MUST fail if EvidenceRef[] missing OR ProvenanceRecord missing.
    - LLM input MUST be restricted to QueryEvidenceBundle plus explicitly permitted payloads.
  ```

* Object_ID: MOD-008
  Object_Name: Baseline StateBuilderPlugin JEPA-like
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Build `StateSpan` and `StateEdge` from extracted features using deterministic windowing and pooling; attach evidence+provenance; output IDs derived deterministically.
  Sources: [SRC-030, SRC-031, SRC-032, SRC-068, SRC-069, SRC-070, SRC-071, SRC-072, SRC-073, SRC-074, SRC-075, SRC-048]
  Interface_Definition:

  ```ts
  // language-agnostic shape from source
  type PluginId = string;         // e.g., "state.jepa_like.v1"
  type SemVer = string;           // e.g., "1.3.0"

  interface AutocapturePlugin {
    id: PluginId;
    version: SemVer;
    init(ctx: PluginContext, config: unknown): void;

    // Deterministic signature: output IDs are derived from (inputs + plugin + config + model_version)
    process(batch: unknown): Promise<unknown>;

    getConfigSchema?(): object;   // JSON schema
    getOutputSchema?(): object;   // JSON schema
  }

  // Baseline StateBuilderPlugin specialization
  process(batch: ExtractBatch): Promise<StateTapeBatch>

  type ExtractBatch = { "session_id": string, "states": derived.sst.state[] }
  type StateTapeBatch = {
    spans: StateSpan[];
    edges: StateEdge[];
  }
  ```

  ```text
  Baseline Computation (deterministic):
    1) StateSpan windowing:
       - choose ONE deterministic mode per config:
         A) fixed duration windows (duration_ms: 5000 default; example range 3000–10000)
         B) heuristic boundary when app/window changes
       - mode selection + parameters MUST be part of config_hash

    2) Span embedding z_t pooling:
       - vision z_vision = deterministic hash vector from image_sha256 (fallback when no region embeddings)
       - text z_text = embed(normalized_text) over all tokens (no confidence threshold)
       - merge = weighted sum of text + vision + layout + input hash vectors, then normalize
       - project merged -> dim 768 via:
         - deterministic hash projection seeded by config hash
       - output z_embedding dtype: f16

    3) Edge computation:
       - delta_embedding: Δz_t = z_t - z_(t-1) (normalization rule: none; raw difference)
       - pred_error = 1 - cosine(z_t, z_(t-1))

    4) Evidence & provenance:
       - each StateSpan and StateEdge MUST include EvidenceRef[] and ProvenanceRecord
       - EvidenceRef selection rules: use screen_state.frame_id per state; sort by ts_start_ms/media_id; keep first max_evidence_refs
       - ProvenanceRecord fields MUST be filled from plugin+model+config+inputs

    5) IDs:
       - state_id and edge_id MUST be deterministically derived per SRC-048 (algorithm: canonical JSON -> sha256 -> UUID via deterministic_id_from_parts)
  ```

* Object_ID: MOD-009
  Object_Name: LinearScanVectorIndex
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Provide deterministic vector search over `StateSpan` embeddings without dependencies; support topK retrieval and store staleness metadata.
  Sources: [SRC-065, SRC-033, SRC-034, SRC-035, SRC-067, SRC-091]
  Interface_Definition:

  ```text
  VectorIndexPlugin Interface (NX):
    - index_spans(spans: StateSpan[]) -> {"indexed": int}
    - query(z_embedding: float[768], filters: {session_id?, start_ms?, end_ms?, app?, limit?}, k: int) -> StateSpanHit[]

  Determinism Requirements:
    - build must be deterministic OR snapshot/versioned
    - query results must be stable given same snapshot + inputs + filters

  Stored Metadata (per entry):
    - state_id
    - model_version (from provenance)
    - embedding_hash (derived from embedding blob when needed)
  ```

* Object_ID: MOD-010
  Object_Name: HNSWVectorIndex
  Object_Type: Library
  Priority: COULD
  Primary_Purpose: Provide faster ANN search over `StateSpan` embeddings with a deterministic bucketed index and snapshot marker to detect staleness.
  Sources: [SRC-066, SRC-034, SRC-067]
  Rationale: Source explicitly allows an optional faster index while requiring versioned/reproducible build.
  Acceptance_Criteria:

  * Index snapshot is versioned and reproducibly built.
  * Query refuses to run if `(embedding_hash, model_version)` mismatch indicates staleness.
  * Determinism caveat is addressed by snapshot/versioning (as required).
    Regression_Detection:
  * Determinism regression test fails for snapshot build.
  * Query returns results when model_version mismatch is detected.
  * Any non-versioned index snapshot is produced.
    Interface_Definition:

  ```text
  Same interface as MOD-009.
  Build determinism controls: deterministic bucketing + stable sort; snapshot marker detects store changes.
  Snapshot format and versioning scheme: derived from state tape snapshot markers; index rebuilds on change.
  ```

* Object_ID: MOD-011
  Object_Name: EvidenceCompilerPlugin
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Compile minimal evidence for query hits into a `QueryEvidenceBundle` using fixed, versioned selection rules.
  Sources: [SRC-036, SRC-037, SRC-038, SRC-058, SRC-059]
  Interface_Definition:

  ```text
  Input:
    - StateSpanHit[] (hit schema: {state_id: string, score: number})

  Output:
    - QueryEvidenceBundle (schema per MOD-007)

  Determinism:
    - evidence selection rules MUST be fixed + versioned
    - ordering of hits and evidence MUST be deterministic (ordering rule: score desc then state_id; evidence sorted by ts_start_ms then media_id)

  Evidence Constraints:
    - must not return raw artifacts directly
    - must include EvidenceRef[] for each hit
    - extracted_text_snippets inclusion must respect policy.can_export_text
  ```

* Object_ID: MOD-012
  Object_Name: Retrieval API Service
  Object_Type: API Endpoint
  Priority: MUST
  Primary_Purpose: Provide structured retrieval over the state tape, assembling a `QueryEvidenceBundle` via vector+metadata search, continuity expansion over edges, evidence compilation, and policy gating.
  Sources: [SRC-006, SRC-026, SRC-081, SRC-082, SRC-083, SRC-084, SRC-085, SRC-028, SRC-096]
  Interface_Definition:

  ```text
  API Transport: HTTP JSON (FastAPI)
  Endpoint/Route Name(s): POST /api/state/query

  Request Inputs:
    - user_question: string
    - optional filters: time/app/entity (exact schema: none; time window inferred via time.intent_parser from user_question)

  Response:
    - QueryEvidenceBundle

  Retrieval Algorithm (deterministic):
    1) parse user_question -> structured query (time/app/entity filters)
    2) retrieve StateSpan hits:
       - vector search over z_embedding via VectorIndexPlugin
       - metadata narrowing by time/app (filter semantics: include spans where ts_end_ms >= start and ts_start_ms <= end; app exact match)
    3) expand continuity:
       - graph walk over StateEdge neighbors for each hit
       - walk depth/hops: 1 (edge evidence merged for immediate neighbors)
       - dedupe rule: unique by (media_id, ts_start_ms, ts_end_ms, frame_index)
    4) Evidence compilation:
       - call EvidenceCompilerPlugin on final hit set
    5) Policy gate:
       - apply PolicyGate between retrieval result and any LLM-bound payload
  ```

* Object_ID: MOD-013
  Object_Name: Policy Gate
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Enforce app allow/deny, redaction, and egress policy at the platform boundary; prevent plugin bypass; determine what payloads can be shown/exported.
  Sources: [SRC-028, SRC-029, SRC-096, SRC-097, SRC-058]
  Interface_Definition:

  ```text
  Policy Inputs:
    - user context / tenant / environment: local single-tenant runtime config
    - query context: time_window + app filter (entity filters not implemented)

  Policy Outputs (minimum):
    - can_show_raw_media: boolean
    - can_export_text: boolean
    - redaction_required: boolean
    - redaction_spec: `processing.sst.redact_*` + `processing.state_layer.policy.redact_text`
    - logging_required_for_export: boolean

  Enforcement Points:
    - between Retrieval API and LLM Orchestrator
    - at any export boundary (raw media/text)

  Anti-Bypass:
    - plugins cannot directly egress; all egress must traverse PolicyGate (mechanism: StatePolicyGate + capability guard + evidence compiler)
  ```

* Object_ID: MOD-014
  Object_Name: LLM Orchestrator Evidence-Only
  Object_Type: Business Logic
  Priority: MUST
  Primary_Purpose: Produce answers using evidence bundle only; enforce citation-by-construction; return “no evidence” when hits are empty; obey policy restrictions and explicitly state limitations.
  Sources: [SRC-017, SRC-025, SRC-027, SRC-059, SRC-086, SRC-087, SRC-088, SRC-099, SRC-092]
  Interface_Definition:

  ```text
  Inputs:
    - user_question: string
    - QueryEvidenceBundle
    - policy decision (from QueryEvidenceBundle.policy)

  Behavior:
    - if hits is empty:
        return literal response: "no evidence"
    - else:
        - generate answer using only:
          - evidence references in hits
          - extracted_text_snippets (only if policy.can_export_text is true)
          - summaries permitted by policy (summary source: StateSpan.summary_features + time range)
        - include inline citations referencing EvidenceRef.media_id + timestamps (ts fields)
        - if policy disallows raw media/text:
          - base answer on permitted summaries only
          - explicitly state limitation

  Prompt Contract Content: "You must answer using only QueryEvidenceBundle. If hits are empty, respond 'no evidence'. Cite EvidenceRef.media_id + timestamps inline. If policy forbids text/media, answer only with allowed summaries and explicitly state the limitation."
  Prompt Template Path: promptops/prompts/state_answer_contract.txt
  ```

* Object_ID: MOD-015
  Object_Name: WorkflowMinerPlugin
  Object_Type: Library
  Priority: COULD
  Primary_Purpose: Cluster repeated `StateTape` sequences into workflows for repeated-task recall without storing more raw text.
  Sources: [SRC-039, SRC-040, SRC-041, SRC-094]
  Rationale: Optional feature to improve repeated-task recall while avoiding more raw text storage.
  Acceptance_Criteria:

  * Workflow mining output is versioned and reproducible given model+seed.
  * No additional raw text storage is introduced beyond existing pipeline outputs.
    Regression_Detection:
  * Non-deterministic workflow output for same state tape + model+seed.
  * Additional raw text persistence introduced.
    Interface_Definition:

  ```text
  Input: StateTape (schema: {session_id: string, spans: StateSpan[], edges: StateEdge[]})
  Output: WorkflowDefs (schema: {workflow_id: string, span_ids: string[], support_count: int, confidence: float})
  Determinism Controls:
    - model versioning: required
    - seed: required
  ```

* Object_ID: MOD-016
  Object_Name: AnomalyPlugin
  Object_Type: Library
  Priority: COULD
  Primary_Purpose: Use `StateEdge.pred_error` to flag surprises and generate alerts, with versioned/tested thresholds.
  Sources: [SRC-042, SRC-043, SRC-044, SRC-093, SRC-075]
  Rationale: Optional feature to surface anomalies and support “what changed” queries using pred_error.
  Acceptance_Criteria:

  * Thresholds are versioned and covered by tests.
  * Alerts are deterministic for same input edges and thresholds.
    Regression_Detection:
  * Alerts vary across identical runs (same edges + thresholds).
  * Threshold changes are not versioned or not tested.
    Interface_Definition:

  ```text
  Input: StateEdge.err/pred_error stream
  Output: Alerts (schema: {alert_id: string, edge_id: string, pred_error: float, ts_ms: int, severity: string})
  Threshold configuration: processing.state_layer.anomaly.pred_error_threshold (versioned + tested)
  ```

* Object_ID: MOD-017
  Object_Name: JEPA Training and Approved Inference Plugin
  Object_Type: Library
  Priority: COULD
  Primary_Purpose: Provide optional JEPA-style training and gated inference; training runs locally and writes model_version + training_run_id; inference only loads signed/approved models.
  Sources: [SRC-076, SRC-077, SRC-078, SRC-079, SRC-080, SRC-003, SRC-125, SRC-126]
  Rationale: Optional training can improve representation while requiring strict model artifact controls and approval gating.
  Acceptance_Criteria:

  * Training produces model_version and training_run_id outputs.
  * Inference refuses to load unsigned/unapproved artifacts.
  * Model version mismatch is detected and blocks shipping.
  * Accuracy regression on golden set does not occur (golden set: tests/fixtures/state_golden.json).
    Regression_Detection:
  * Unsigned model loads succeed.
  * Model version mismatches are not detected.
  * Accuracy regression on golden set is detected.
    Interface_Definition:

  ```text
  Training:
    - Input: training dataset derived from captures/state tape (dataset schema: {spans: StateSpan[], edges: StateEdge[], evidence: EvidenceRef[]})
    - Output: model artifact + model_version + training_run_id

  Inference Gate:
    - Required checks: signature/approval, model_version alignment
    - Enforcement location: plugin load path (`plugins/builtin/state_jepa_training/plugin.py` + `autocapture_nx/state_layer/jepa_training.py`)
  ```

* Object_ID: MOD-018
  Object_Name: Deterministic IDs and Caching
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Compute deterministic config hashes, caching keys, and content-addressed IDs to ensure idempotent reprocessing and reproducibility.
  Sources: [SRC-005, SRC-031, SRC-048, SRC-089, SRC-020]
  Interface_Definition:

  ```text
  Required Functions (names: compute_config_hash, compute_cache_key, compute_deterministic_id, deterministic_id_from_parts, compute_embedding_hash):
    - compute_config_hash(config: object) -> hex
    - compute_cache_key(plugin_id, plugin_version, model_version, config_hash, input_artifact_ids[]) -> hex
    - compute_deterministic_id(preimage: bytes) -> uuid
    - compute_embedding_hash(embedding_blob: bytes) -> hex

  Hash Algorithm(s): SHA-256 (canonical JSON via sha256_text/sha256_bytes)
  Preimage Composition (MUST include):
    - plugin_id
    - plugin_version
    - model_version
    - config_hash
    - input_artifact_ids[]
  ```

* Object_ID: MOD-019
  Object_Name: State Layer Database Migration
  Object_Type: Data Model
  Priority: MUST
  Primary_Purpose: Add new DB tables and indexes for state layer and wire into the repository’s migration framework.
  Sources: [SRC-110, SRC-060, SRC-061, SRC-062, SRC-063, SRC-064]
  Interface_Definition:

  ```text
  Migration Framework: inline SQLite DDL in StateTapeStore._ensure (CREATE TABLE IF NOT EXISTS; no external migration runner)
  Migration Steps:
    - create state_span
    - create state_edge
    - create state_evidence_link
    - create indexes listed in schema

  Rollback Strategy: disable `processing.state_layer.enabled` and/or point `storage.state_tape_path` to a new archive location (no deletes)
  ```

* Object_ID: MOD-020
  Object_Name: Test Suite and Regression Gates
  Object_Type: Library
  Priority: MUST
  Primary_Purpose: Add tests and regression detection that enforce provenance completeness, determinism, policy gate behavior, and evidence-citation correctness; implement DO_NOT_SHIP gates.
  Sources: [SRC-115, SRC-118, SRC-119, SRC-120, SRC-121, SRC-122, SRC-123, SRC-124, SRC-125, SRC-126, SRC-087]
  Interface_Definition:

  ```text
  Required Tests:
    - Provenance completeness:
        For every persisted derived object: has EvidenceRef[] AND ProvenanceRecord (hard gate).
    - Deterministic IDs:
        Same inputs+plugin+config+model_version => same state_id/edge_id and cache key.
    - Policy gate enforcement:
        When export disabled, raw media/text cannot be exported and LLM does not receive disallowed payloads.
    - Query stability:
        Query returns stable EvidenceRef references for same underlying state tape snapshot.
    - No-evidence path:
        Empty hits => literal response "no evidence".
    - Citation correctness:
        If hits exist, answer includes evidence IDs/timestamps; otherwise DO_NOT_SHIP.
    - State golden eval:
        `tools/state_layer_eval.py` over `tests/fixtures/state_golden.json` must pass.

  Budgeted Gates:
    - Ingestion latency regression budget: <= 10% (performance.state_layer.ingestion_latency_regression_pct)
    - Storage growth budget: <= 250 MB/day (performance.state_layer.storage_growth_mb_per_day)
    - Query p95 latency budget: <= 1500 ms (performance.state_layer.query_p95_ms)
  ```

* Object_ID: MOD-021
  Object_Name: Feature Flags and Rollout Controls
  Object_Type: Other
  Priority: MUST
  Primary_Purpose: Provide rollout plan with feature flags (default off) for State Layer and evidence-only orchestration changes.
  Sources: [SRC-107]
  Interface_Definition:

  ```text
  Feature Flags (names): processing.state_layer.enabled, processing.state_layer.query_enabled, processing.state_layer.features.index_enabled, processing.state_layer.features.workflow_enabled, processing.state_layer.features.anomaly_enabled, processing.state_layer.features.training_enabled, processing.state_layer.emit_frame_evidence
  Default Values:
    - all new State Layer features: off
  Flag Scope and Precedence Rules: config defaults off; user config overrides default; safe_mode overrides can force disable; feature flags evaluated per run
  ```

* Object_ID: MOD-022
  Object_Name: Codex Verification Prompt Artifact
  Object_Type: Other
  Priority: MUST
  Primary_Purpose: Provide the Codex “verify before change” prompt to enumerate required code/schema changes before edits and gate implementation behind an accepted plan.
  Sources: [SRC-007, SRC-100, SRC-101, SRC-102, SRC-103, SRC-104, SRC-105, SRC-106, SRC-107, SRC-108, SRC-109, SRC-110, SRC-111, SRC-112, SRC-113, SRC-114, SRC-115, SRC-116, SRC-117, SRC-118]
  Interface_Definition:

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
  Prompt Template Path: promptops/prompts/codex_state_layer_verify.txt

# 3. Architecture Decision Records (ADRs)

ADRs:

* ADR_ID: ADR-0010
  Title: Introduce State Layer and State Tape
  Status: Implemented
  Decision: Add a new State Layer stage that produces an append-only, deterministic, versioned `state_tape` composed of `StateSpan` and `StateEdge`, positioned between Extraction Layer and Index Layer.
  Rationale: The source blueprint explicitly inserts a State Layer after extraction and defines its outputs and semantics.
  Consequences:

  * State must be persisted explicitly, not only in prompts.
  * Query orchestration pivots to retrieving over state tape instead of raw browsing.
    Sources: [SRC-001, SRC-015, SRC-024, SRC-025, SRC-016]

* ADR_ID: ADR-0011
  Title: Make Evidence and Provenance Non-Negotiable for Derived Objects
  Status: Implemented
  Decision: Enforce `EvidenceRef[]` + `ProvenanceRecord` on every derived object; block persistence if either is missing; ensure state objects store evidence and provenance.
  Rationale: Source states invariant and must-do provenance rules.
  Consequences:

  * Adds storage and validation overhead.
  * Enables citation-by-construction and debuggability.
    Sources: [SRC-022, SRC-053, SRC-098, SRC-009]

* ADR_ID: ADR-0012
  Title: Extend Plugin System with New Plugin Types
  Status: Implemented
  Decision: Add plugin types (StateBuilderPlugin, VectorIndexPlugin optional, EvidenceCompilerPlugin, WorkflowMinerPlugin optional, AnomalyPlugin optional) under a base AutocapturePlugin interface with deterministic ID derivation.
  Rationale: Source defines plugin types, IO, and determinism requirements.
  Consequences:

  * Requires plugin registry updates and deterministic configuration/versioning.
    Sources: [SRC-002, SRC-030, SRC-033, SRC-036, SRC-039, SRC-042, SRC-047, SRC-048]

* ADR_ID: ADR-0013
  Title: Persist State Tape Using SQLite Minimal Schema
  Status: Implemented
  Decision: Use the provided minimal SQLite schema for state tape persistence (`state_span`, `state_edge`, `state_evidence_link`) including indexes.
  Rationale: Source provides explicit DDL and positions it as minimal viable schema.
  Consequences:

  * Requires DB migration and indexing.
  * Evidence storage encoding details remain: canonical JSON in state_evidence_link evidence_json.
    Sources: [SRC-060, SRC-061, SRC-062, SRC-063, SRC-064, SRC-110]

* ADR_ID: ADR-0014
  Title: Pluggable Vector Search with Deterministic Baseline
  Status: Implemented
  Decision: Provide a VectorIndexPlugin contract; ship LinearScanVectorIndex as default; optionally support HNSWVectorIndex only via versioned reproducible snapshots; index stores `(state_id, embedding_hash, model_version)`.
  Rationale: Source specifies default linear scan and optional HNSW with determinism constraints and staleness contract.
  Consequences:

  * Baseline is slower but deterministic.
  * ANN requires snapshot/version control and determinism safeguards.
    Sources: [SRC-065, SRC-066, SRC-067, SRC-034]

* ADR_ID: ADR-0015
  Title: Evidence-Only Retrieval API and LLM Contract
  Status: Implemented
  Decision: Implement retrieval sequence: parse question -> structured query -> state span retrieval -> edge expansion -> evidence bundle compilation; LLM consumes only QueryEvidenceBundle and must cite evidence; no evidence yields “no evidence”; policy gate enforces what is visible/exportable.
  Rationale: Source defines retrieval sequence as hard requirement and restricts LLM inputs.
  Consequences:

  * Orchestrator must be refactored to accept evidence bundles.
  * Prevents raw-store browsing by LLM.
    Sources: [SRC-006, SRC-081, SRC-082, SRC-083, SRC-084, SRC-085, SRC-086, SRC-087, SRC-088, SRC-059, SRC-096]

* ADR_ID: ADR-0016
  Title: Baseline Deterministic JEPA-like State Builder and Optional Training
  Status: Implemented
  Decision: Ship baseline StateBuilderPlugin with deterministic windowing/pooling and edge metrics without training; optionally support JEPA-style training with local runs, model_version/training_run_id outputs, and approved/signed inference gating.
  Rationale: Source mandates baseline without training and defines optional training boundaries and gating.
  Consequences:

  * Baseline delivers immediate functionality.
  * Training path adds model artifact governance requirements.
    Sources: [SRC-068, SRC-069, SRC-070, SRC-071, SRC-072, SRC-073, SRC-074, SRC-075, SRC-003, SRC-076, SRC-079, SRC-080]

* ADR_ID: ADR-0017
  Title: Deterministic Caching and Content-Addressed Identity
  Status: Implemented
  Decision: Enforce deterministic caching key and deterministic output ID derivation based on plugin + config + model_version + inputs to ensure idempotent reprocessing and reproducibility.
  Rationale: Source defines cache key formula and deterministic ID derivation.
  Consequences:

  * Requires consistent hashing and canonicalization across runtime.
  * Hash algorithm is SHA-256 unless specified elsewhere.
    Sources: [SRC-089, SRC-048, SRC-020, SRC-005]

* ADR_ID: ADR-0018
  Title: Security Boundary and Policy Gate Enforcement
  Status: Implemented
  Decision: Keep system default local-only, encrypted at rest; treat embeddings as sensitive derived data; enforce policy gate between retrieval and LLM and at export boundary; disallow silent egress; disallow plugin bypass.
  Rationale: Source explicitly sets security posture and policy boundary requirements.
  Consequences:

  * Requires centralized policy enforcement mechanism.
  * Must audit plugin interfaces to prevent bypass.
    Sources: [SRC-095, SRC-096, SRC-097, SRC-019, SRC-028, SRC-029]

* ADR_ID: ADR-0019
  Title: Codex Two-Phase Implementation Process and DO_NOT_SHIP Gates
  Status: Implemented
  Decision: Require Codex PHASE 1 recon output (file-path change plan, migration plan, test plan, rollout flags default off) before PHASE 2 implementation; enforce hard DO_NOT_SHIP regression gates.
  Rationale: Source provides a strict pre-edit prompt and explicit regression gate conditions.
  Consequences:

  * Slows initial edits but reduces uncontrolled risk.
  * Requires CI or equivalent gating mechanism. CI details: tools/run_all_tests.py + tools/gate_pillars.py
    Sources: [SRC-100, SRC-101, SRC-107, SRC-108, SRC-115, SRC-118, SRC-119, SRC-121, SRC-122, SRC-123]

* ADR_ID: ADR-0020
  Title: Determinism Scope Is Explicitly Partial
  Status: Implemented
  Decision: Treat determinism as verified for schemas/contracts/provenance/caching/evidence bundle; treat embedding inference and ANN build determinism as partial unless forced to deterministic mode and/or snapshot/versioned.
  Rationale: Source explicitly declares determinism scope and caveats.
  Consequences:

  * Requires documenting and testing determinism boundaries.
  * May require additional constraints for inference runtimes and ANN build.
    Sources: [SRC-127, SRC-128, SRC-129, SRC-130]

# 4. Grounding Data (Few-Shot Samples)

Grounding_Samples:

* Sample_ID: Sample_Table_STATE_SPAN_WINDOWING
  Applies_To_Modules: [MOD-008, MOD-005, MOD-012]
  Sources: [SRC-070, SRC-082, SRC-083]
  Columns:

  * session_id
  * mode
  * ts_start_ms
  * ts_end_ms
  * derived_state_id
    Rows:
  * session_id: "00000000-0000-0000-0000-000000000001"
    mode: "fixed_duration"
    ts_start_ms: 1000
    ts_end_ms: 6000
    derived_state_id: "00000000-0000-0000-0000-000000000101"
  * session_id: "00000000-0000-0000-0000-000000000001"
    mode: "fixed_duration"
    ts_start_ms: 6000
    ts_end_ms: 11000
    derived_state_id: "00000000-0000-0000-0000-000000000102"
  * session_id: "00000000-0000-0000-0000-000000000001"
    mode: "heuristic_app_window_change"
    ts_start_ms: 11000
    ts_end_ms: 15000
    derived_state_id: "00000000-0000-0000-0000-000000000103"

* Sample_ID: Sample_Table_Z_POOLING
  Applies_To_Modules: [MOD-008]
  Sources: [SRC-071, SRC-072, SRC-073]
  Columns:

  * span_state_id
  * vision_pooling
  * text_pooling
  * projection
  * z_dim
  * z_dtype
    Rows:
  * span_state_id: "00000000-0000-0000-0000-000000000101"
    vision_pooling: "hash(image_sha256) (fallback; no region embeddings)"
    text_pooling: "embed(normalized_text) over all tokens"
    projection: "deterministic hash projection (config hash)"
    z_dim: 768
    z_dtype: "f16"
  * span_state_id: "00000000-0000-0000-0000-000000000102"
    vision_pooling: "hash(image_sha256) (fallback; no region embeddings)"
    text_pooling: "embed(normalized_text) over all tokens"
    projection: "deterministic hash projection (config hash)"
    z_dim: 768
    z_dtype: "f16"
  * span_state_id: "00000000-0000-0000-0000-000000000103"
    vision_pooling: "hash(image_sha256) (fallback; no region embeddings)"
    text_pooling: "embed(normalized_text) over all tokens"
    projection: "deterministic hash projection (config hash)"
    z_dim: 768
    z_dtype: "f16"

* Sample_ID: Sample_Table_STATE_EDGE
  Applies_To_Modules: [MOD-008, MOD-016, MOD-012]
  Sources: [SRC-074, SRC-075, SRC-084, SRC-093]
  Columns:

  * from_state_id
  * to_state_id
  * delta_rule
  * pred_error_rule
  * pred_error_value
    Rows:
  * from_state_id: "00000000-0000-0000-0000-000000000101"
    to_state_id: "00000000-0000-0000-0000-000000000102"
    delta_rule: "z_t - z_(t-1)"
    pred_error_rule: "1 - cosine(z_t, z_(t-1))"
    pred_error_value: 0.05
  * from_state_id: "00000000-0000-0000-0000-000000000102"
    to_state_id: "00000000-0000-0000-0000-000000000103"
    delta_rule: "z_t - z_(t-1)"
    pred_error_rule: "1 - cosine(z_t, z_(t-1))"
    pred_error_value: 0.42
  * from_state_id: "00000000-0000-0000-0000-000000000103"
    to_state_id: "00000000-0000-0000-0000-000000000104"
    delta_rule: "z_t - z_(t-1) (raw)"
    pred_error_rule: "1 - cosine(z_t, z_(t-1))"
    pred_error_value: 0.12

* Sample_ID: Sample_Table_VECTOR_QUERY_TOPK
  Applies_To_Modules: [MOD-009, MOD-012]
  Sources: [SRC-083, SRC-091, SRC-067]
  Columns:

  * query_id
  * model_version
  * filter_app
  * topk
  * hit_state_id
  * score
    Rows:
  * query_id: "00000000-0000-0000-0000-00000000A001"
    model_version: "model.v1"
    filter_app: "com.example.app"
    topk: 3
    hit_state_id: "00000000-0000-0000-0000-000000000101"
    score: 0.91
  * query_id: "00000000-0000-0000-0000-00000000A002"
    model_version: "model.v1"
    filter_app: "com.example.app"
    topk: 3
    hit_state_id: "00000000-0000-0000-0000-000000000102"
    score: 0.88
  * query_id: "00000000-0000-0000-0000-00000000A003"
    model_version: "model.v2"
    filter_app: "com.example.app"
    topk: 3
    hit_state_id: "filtered (model_version mismatch)"
    score: 0.0

* Sample_ID: Sample_Table_EVIDENCE_BUNDLE
  Applies_To_Modules: [MOD-011, MOD-012, MOD-014]
  Sources: [SRC-058, SRC-059, SRC-085]
  Columns:

  * query_id
  * hit_state_id
  * evidence_media_id
  * evidence_ts_start_ms
  * evidence_ts_end_ms
  * can_export_text
    Rows:
  * query_id: "00000000-0000-0000-0000-00000000B001"
    hit_state_id: "00000000-0000-0000-0000-000000000101"
    evidence_media_id: "00000000-0000-0000-0000-00000000C001"
    evidence_ts_start_ms: 1000
    evidence_ts_end_ms: 1500
    can_export_text: false
  * query_id: "00000000-0000-0000-0000-00000000B002"
    hit_state_id: "00000000-0000-0000-0000-000000000102"
    evidence_media_id: "00000000-0000-0000-0000-00000000C002"
    evidence_ts_start_ms: 6500
    evidence_ts_end_ms: 7000
    can_export_text: true
  * query_id: "00000000-0000-0000-0000-00000000B003"
    hit_state_id: "00000000-0000-0000-0000-000000000103"
    evidence_media_id: "00000000-0000-0000-0000-00000000C003"
    evidence_ts_start_ms: 12000
    evidence_ts_end_ms: 12500
    can_export_text: false

* Sample_ID: Sample_Table_POLICY_GATE
  Applies_To_Modules: [MOD-013, MOD-014, MOD-011]
  Sources: [SRC-028, SRC-096, SRC-088, SRC-097]
  Columns:

  * scenario
  * can_show_raw_media
  * can_export_text
  * required_behavior
    Rows:
  * scenario: "default_local_only_no_export"
    can_show_raw_media: false
    can_export_text: false
    required_behavior: "answer based on permitted summaries only; explicitly state limitation"
  * scenario: "text_export_allowed_media_blocked"
    can_show_raw_media: false
    can_export_text: true
    required_behavior: "include extracted_text_snippets; do not attach raw media"
  * scenario: "media_and_text_allowed"
    can_show_raw_media: true
    can_export_text: true
    required_behavior: "include permitted payloads; still cite EvidenceRef.media_id+ts"

* Sample_ID: Sample_Table_LLM_CITATIONS
  Applies_To_Modules: [MOD-014]
  Sources: [SRC-086, SRC-099, SRC-123]
  Columns:

  * hits_empty
  * required_output_shape
  * example_answer_snippet
    Rows:
  * hits_empty: true
    required_output_shape: "literal_no_evidence"
    example_answer_snippet: "no evidence"
  * hits_empty: false
    required_output_shape: "answer_with_inline_citations"
    example_answer_snippet: "Observed X at time Y. [media_id=000...C002 ts=6500-7000]"
  * hits_empty: false
    required_output_shape: "do_not_ship_if_missing_citations"
    example_answer_snippet: "INVALID (missing citations)"

* Sample_ID: Sample_Table_CACHE_KEY_AND_IDS
  Applies_To_Modules: [MOD-018, MOD-004, MOD-008]
  Sources: [SRC-089, SRC-048, SRC-031]
  Columns:

  * plugin_id
  * plugin_version
  * model_version
  * config_hash
  * input_artifact_ids
  * cache_key
  * derived_state_id
    Rows:
  * plugin_id: "state.jepa_like.v1"
    plugin_version: "1.0.0"
    model_version: "model.v1"
    config_hash: "deadbeef"
    input_artifact_ids: ["00000000-0000-0000-0000-00000000D001"]
    cache_key: "82507f89aca68af8f3a19d6f005a8a1b81710a378c8b082e74f649b3834139ed"
    derived_state_id: "00000000-0000-0000-0000-000000000101"
  * plugin_id: "state.jepa_like.v1"
    plugin_version: "1.0.0"
    model_version: "model.v1"
    config_hash: "deadbeef"
    input_artifact_ids: ["00000000-0000-0000-0000-00000000D001"]
    cache_key: "82507f89aca68af8f3a19d6f005a8a1b81710a378c8b082e74f649b3834139ed"
    derived_state_id: "00000000-0000-0000-0000-000000000101"
  * plugin_id: "state.jepa_like.v1"
    plugin_version: "1.0.0"
    model_version: "model.v2"
    config_hash: "deadbeef"
    input_artifact_ids: ["00000000-0000-0000-0000-00000000D001"]
    cache_key: "23451689a50e875060cecd16ae3cfdfd337574e6a89f5f1e9d5d6aaf1ed276e9"
    derived_state_id: "different (model_version change)"
