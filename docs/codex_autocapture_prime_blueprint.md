# Codex CLI Implementation Blueprint — Autocapture Prime (ninjra/autocapture_prime)

Source repo: https://github.com/ninjra/autocapture_prime (branch: dev-harness)  
TS: 2026-02-12 21:48:09 MST

## 0) Hard constraints (must follow)
Repo evidence:
- README: https://github.com/ninjra/autocapture_prime/blob/dev-harness/README.md
- Plugin model + lockfile: https://github.com/ninjra/autocapture_prime/blob/dev-harness/docs/plugin_model.md
- Safe mode: https://github.com/ninjra/autocapture_prime/blob/dev-harness/docs/safe_mode.md

Constraints:
- Plugin allowlist + hash lockfile must remain enforced (fail closed per plugin_model.md).
- Safe mode behavior must remain intact.
- Default posture should remain local-first and network-denied unless explicitly enabled.

## 1) What to implement (from recommended ideas)
### 1.1 “Screen structure layer” plugin family (UI parsing → graph → evidence)
Goal: Make screenshot reasoning non-OCR-only by building a structured scene graph:
- windows/apps/tabs/panels
- text blocks + bounding boxes
- interactive affordances (buttons, inputs) where detectable
- relationships: containment, adjacency

Implement capabilities:
- `screen.parse.v1` → returns `ui_graph.json` with bbox + tokens + hierarchy
- `screen.index.v1` → chunk + embed structured nodes into your retrieval store
- `screen.answer.v1` → answer questions using retrieved graph nodes, with provenance pointers

Deliverables:
- New plugin(s) under `plugins/` with `plugin.json` manifests.
- Add schemas:
  - `docs/schemas/ui_graph.schema.json`
  - `docs/schemas/provenance.schema.json`

### 1.2 Multimodal RAG evidence objects (retrieval + citations by construction)
Define a unified “evidence object”:
- `evidence_id`, `type` (text|ui_node|image_region)
- `source` (frame_id, file_id)
- `bbox` (optional)
- `hash` (sha256 of canonical bytes)

Enforce: Answer outputs must reference evidence ids for each factual claim.

### 1.3 Evaluation harness (golden screenshots + grounding checks)
Add `tests/golden/`:
- `questions.yaml`
- `expected.yaml` with:
  - required facts
  - required evidence references (bbox/node ids)

Add a CLI runner that validates:
- schema validity
- evidence presence
- optional numeric/string checks

## 2) Codex execution steps (must scan full repo)
Codex MUST:
1) Check out `dev-harness`.
2) Enumerate all files:
   - `git ls-files` → write to `docs/_codex_repo_manifest.txt`
3) Read all core docs and contracts:
   - `docs/plugin_model.md`, `docs/safe_mode.md`, `docs/configuration.md`, `contracts/*`
4) Identify current capture/index/store components and where a UI-graph plugin fits.
5) Produce `docs/_codex_repo_review.md` with insertion points and constraints.

Stop if the scan cannot be completed.

## 3) Implementation plan (minimal-risk)
### Phase A — schemas + plugin contract
- Add JSON schemas for ui_graph and provenance.
- Extend plugin SDK types to include bbox + evidence references.

### Phase B — `screen.parse.v1`
- Deterministic parsing first:
  - OCR blocks + layout grouping
  - window/tab detection heuristics
- Output:
  - `ui_graph.json`
  - `ui_graph.md` (human-readable)

### Phase C — `screen.index.v1`
- Chunk ui nodes by hierarchy.
- Store embeddings keyed by node ids.

### Phase D — `screen.answer.v1`
- Require evidence references in output.
- Return “insufficient evidence” when evidence is missing.

### Phase E — evaluation harness
- Add golden corpus runner and integrate into existing test scripts.

## 4) Tests (must add)
- Schema validation for ui_graph + provenance.
- Safe mode: only default pack loads unless explicitly updated.
- Lockfile hash enforcement includes new plugin files.
- Golden corpus tests enforce evidence references.

## 5) Acceptance criteria (objective)
- New plugins pass plugin validation and appear in `doctor` output.
- Answers include evidence references for factual claims.
- Safe mode continues to boot with defaults only.
- Lockfile contains hashes for new plugin files.

## 6) Evidence labels
- QUOTE: Plugin allowlist + locks: https://github.com/ninjra/autocapture_prime/blob/dev-harness/docs/plugin_model.md
- QUOTE: Safe mode behavior: https://github.com/ninjra/autocapture_prime/blob/dev-harness/docs/safe_mode.md
- QUOTE: Repo entrypoints and tests: https://github.com/ninjra/autocapture_prime/blob/dev-harness/README.md
- NO EVIDENCE: External UI parsing research is not re-fetched here.

## 7) Determinism notes
Keep parsing deterministic by:
- stable node ordering (top-to-bottom, left-to-right)
- stable id generation (hash of bbox+text+frame_id)
