**Title:** DAG Batch Pipeline + Canonical Model Output Records + JEPA Landscape Index
**Context:** Mode B moves capture/ingest to a Windows sidecar, leaving this repo responsible for processing and query. As evidence volume increases, one-shot per-frame extraction and ad-hoc derived records make it harder to guarantee performance, reproducibility, and citeability.
**Decision:**
* Add a DAG-style batch pipeline for processing: ingest -> normalize -> fan-out to model workers -> postprocess -> persist -> index.
* Treat OCR/VLM/LLM/embedding models as long-lived, localhost-only servers (vLLM where appropriate), invoked as stateless workers by the scheduler.
* Standardize every model output into a canonical record:
  * `{sample_id, modality, model_id, prompt_hash, output_json, emb_vectors[], metrics, provenance}`
* Store derived facts in two tiers:
  * Parquet/Arrow for durable, replayable facts.
  * Vector neighborhood index for landscape construction and retrieval.
* Pin reproducibility inputs (dataset version, model version, prompts, decoder params, embedding normalization) and persist provenance hashes to make landscape rebuilds deterministic.

**Consequences:**
* Performance: batch scheduling amortizes overhead and enables GPU saturation while respecting foreground gating and CPU/RAM budgets.
* Accuracy: multi-model fan-out becomes explicit, with consistent postprocessing and metrics.
* Security: model servers remain localhost-only; external inputs remain untrusted; PolicyGate and sandboxing continue to apply at boundaries.
* Citeability: canonical records make provenance and prompt/model digests explicit; queries can cite stable record ids and hashes.

**Sources:** [SRC-015, SRC-016, SRC-024, SRC-025, SRC-001]

---

