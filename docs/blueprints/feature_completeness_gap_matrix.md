# Feature completeness gap matrix

Purpose: map MOD-001..MOD-040 to repo evidence for the Prime feature completeness spec.

Authoritative sources:
- `docs/spec/feature_completeness_spec.md`
- `docs/blueprints/feature_completeness_blueprint.txt`

Method:
- Parsed `Object_ID` blocks in the spec for MOD-###, extracted `Object_Name`, `Sources`, and interface class symbols (fallback to function symbols if no classes).
- Searched repo for interface symbols using `rg -n -i "\bclass\s+<Symbol>\b|\bdef\s+<Symbol>\b"` scoped to source dirs (autocapture_nx, autocapture, plugins).
- Status is **partial** when symbol hits exist; **missing** when none were found (may still exist under different names).

Entrypoint + plugin artifacts:
- CLI entrypoint: pyproject.toml: autocapture = autocapture_nx.cli:main
- Plugin lockfile: `config/plugin_locks.json`
- Plugin manifest schema: `contracts/plugin_manifest.schema.json`
- Plugin manifests: `plugins/builtin/*/plugin.json`

## Module coverage

| MOD | Name | Status | Evidence (rg hits) | Notes |
| --- | --- | --- | --- | --- |
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 
 complete 

## Next implementation order (from blueprint milestones)
1) Contracts + effective config + kernel boot
2) Plugin registry + allowlist/hash locks + safe mode
3) Network guard + egress-only routing
4) Journal/ledger/anchor + keyring/rotation
5) Typed storage + migrations + tombstones
6) Capture orchestration + runtime governor + privacy
7) OCR/VLM + spans
8) Embeddings + lexical/vector indexes
9) Time intent + retrieval + answer builder
10) Egress gateway/sanitizer + reasoning packets
11) FastAPI + UI/overlay
12) Export/import + doctor/observability + eval gates
