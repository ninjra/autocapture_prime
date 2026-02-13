# Autocapture_Prime — Web-updated improvement options (4 pillars) + Codex CLI implementation prompts

## Scope
Repo: https://github.com/ninjra/autocapture_prime

This file focuses on screenshot understanding, grounding, multimodal RAG, evaluation, and provenance.

---

## Web-sourced options to implement (Autocapture-focused)

### A1) ScreenSpot-Pro benchmark + dataset patterns for high-resolution GUI grounding
- Source: https://github.com/likaixin2000/ScreenSpot-Pro-GUI-Grounding
- Use: adopt evaluation protocol and “hard” professional-app coverage mindset for your 7680×2160 workflows.

### A2) ScreenSpot/OSWorld-G style UI decomposition + synthesis grounding methods
- Source: https://osworld-grounding.github.io/
- Use: treat “UI decomposition → element candidates” as a pre-grounding stage.

### A3) OmniParser V2 for UI parsing / interactable element detection
- Source: https://github.com/microsoft/OmniParser
- Use: build a stable UI intermediate representation (IR) per frame; feed to retrieval and answerer.

### A4) GUI-Actor for coordinate-free grounding + verifier
- Sources: https://github.com/microsoft/GUI-Actor and https://www.microsoft.com/en-us/research/publication/gui-actor-coordinate-free-visual-grounding-for-gui-agents/
- Use: action-region candidates + verifier scores; improves robustness to DPI/layout changes.

### A5) UGround (CVPR 2025) for unified grounding / segmentation
- Source: https://github.com/rui-qian/UGround
- Use: when you need pixel-level masks (icons, small targets) rather than bboxes.

### A6) UI-E2I-Synth / UI-I2E-Bench (instruction synthesis for grounding)
- Source: https://microsoft.github.io/FIVE-UI-Evol/
- Use: synthesize instruction variants to stress-test your grounding pipeline and reduce brittleness.

### A7) Multimodal RAG reliability evaluation (RAG-Check)
- Source: https://www.emergentmind.com/papers/2501.03995
- Use: separate retrieval relevance vs answer correctness; prevents “confident wrong.”

### A8) RAG evaluation + benchmark kit (RAGAs + RAGBench)
- Sources: https://aclanthology.org/2024.eacl-demo.16/ and https://github.com/rungalileo/ragbench
- Use: continuous evaluation of your memory QA behaviors.

### A9) Late-interaction retrieval (ColBERT) for higher-precision span retrieval
- Source: https://github.com/stanford-futuredata/ColBERT
- Use: better retrieval for extracted spans from UI + logs.

### A10) Local serving performance: vLLM V1 + optional FlashInfer backend
- Sources: vLLM https://github.com/vllm-project/vllm ; FlashInfer https://github.com/flashinfer-ai/flashinfer
- Use: improve throughput for background processing.

---

## Codex CLI implementation prompts (copy/paste)

### Task A-CORE-01: Frame → UI IR extraction pipeline (OmniParser adapter)
**Goal:** Produce a stable UI-IR per captured frame.
**Deliverables:**
- `ui_ir.json` schema (elements, text, bbox, interactable)
- adapter wrapper calling OmniParser or a stub fallback
- store IR with provenance: `{frame_id, capture_meta, sha256}`
**Acceptance tests:**
- deterministic schema validation
- IR diff test on unchanged screenshots

### Task A-GROUND-01: Grounding stage with verifier (GUI-Actor style contract)
**Goal:** Given instruction, output candidate regions + chosen region with verifier score.
**Deliverables:**
- `grounding_result.json` schema
- adapter stubs (model-agnostic)
- tests for “provenance required”
**Acceptance tests:**
- deterministic fixture run returns stable JSON

### Task A-RAG-01: Multimodal RAG evaluation harness (RAG-Check / RAGAs style)
**Goal:** Add eval runner that scores retrieval relevance and answer correctness.
**Deliverables:**
- `eval_suite/` with fixed screenshot+question corpus
- metrics JSON; trend file; fail thresholds
**Acceptance tests:**
- regression test fails when correctness drops below threshold

### Task A-INDEX-01: Retrieval backend abstraction (dense + ColBERT optional)
**Goal:** Allow switching retrieval engines without changing callers.
**Deliverables:**
- interface: `index.add(doc)`, `search(query)->topk{doc_id, span_id, score}`
- baseline dense (existing) + optional ColBERT adapter stub
**Acceptance tests:**
- recall@k on a fixed query set

### Task A-PERF-01: Background batch scheduler w/ budgets
**Goal:** Batch processing never starves the machine; bounded GPU.
**Deliverables:**
- config: batch size, max gpu mem, max wall time
- job queue and backpressure
**Acceptance tests:**
- synthetic load test proves budgets trip deterministically

---

## Notes on “agents”
For Autocapture_Prime, you can get most benefits without a free-form “agent loop”.
Prefer: **(1) IR extraction → (2) retrieval → (3) constrained answer synthesis → (4) verifier**.
If you later add an “agent,” treat it as a planner whose output is a schema and is always verified and provenance-attached.

