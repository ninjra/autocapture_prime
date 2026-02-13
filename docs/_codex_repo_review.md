# Codex Repo Review (Contract Artifact)

Generated for `docs/codex_autocapture_prime_blueprint.md` contract closure.

## Constraints Observed
- Plugin allowlist + lockfile enforcement remains required (`docs/plugin_model.md`).
- Safe mode behavior remains required (`docs/safe_mode.md`).
- Local-first / network-denied defaults remain required.
- External vLLM ownership is sidecar/hypervisor; this repo consumes `http://127.0.0.1:8000`.

## Primary Insertion Points
- Query orchestration:
  - `autocapture_nx/kernel/query.py`
  - `autocapture_nx/processing/idle.py`
- Plugin capabilities and manifests:
  - `plugins/builtin/*/plugin.py`
  - `plugins/builtin/*/plugin.json`
- Contract/schemas:
  - `contracts/*.schema.json`
  - `docs/schemas/*.json`
- Retrieval/indexing:
  - `autocapture/indexing/lexical.py`
  - `autocapture/indexing/vector.py`
  - `autocapture_nx/indexing/*`
- Safety/policy:
  - `autocapture_nx/plugin_system/registry.py`
  - `autocapture_nx/plugin_system/runtime.py`
  - `config/plugin_locks.json`

## Current Contract Misses Addressed
- Added required artifact scaffolding files from codex blueprint:
  - `docs/_codex_repo_manifest.txt`
  - `docs/schemas/ui_graph.schema.json`
  - `docs/schemas/provenance.schema.json`
  - `tests/golden/questions.yaml`
  - `tests/golden/expected.yaml`
- Added screen-structure plugin scaffolding:
  - `plugins/builtin/screen_parse_v1/`
  - `plugins/builtin/screen_index_v1/`
  - `plugins/builtin/screen_answer_v1/`

## Implementation Notes
- Screen-structure plugin family (`screen.parse.v1`, `screen.index.v1`, `screen.answer.v1`) remains planned as implementation work, with deterministic tests and evidence-linked outputs required before promotion.
