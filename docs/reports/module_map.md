# Module map (current repo)

## Kernel / core orchestration
- `autocapture_nx/kernel/` (config, crypto, hashing, canonical json, system/query)
- `autocapture_nx/plugin_system/` (plugin registry/host/runtime)
- `autocapture_nx/cli.py` (CLI entrypoint)

## Capture pipeline
- `autocapture/capture/` (pipelines, models, spool)
- `autocapture/ingest/` (ingest pipeline)
- `autocapture/runtime/` (runtime orchestration)
- `autocapture_nx/windows/win_capture.py` (Windows capture)

## Storage
- `autocapture/storage/` (database, media_store, blob_store, archive, keys, sqlcipher)
- `autocapture/storage/migrations/`

## Retrieval / indexing
- `autocapture/retrieval/` (tiers, rerank, fusion, signals)
- `autocapture/indexing/`

## Plugins / policy
- `autocapture/plugins/` (manifest, manager, policy_gate, kinds)
- `plugins/` (repo-level plugin assets)
- `autocapture_plugins/` (additional plugin packages)

## Web / UX
- `autocapture/web/` (FastAPI routes, static assets)
- `autocapture/gateway/` (API app/router/schemas)
- `autocapture/ux/` (UX layer)

## Windows-specific
- `autocapture_nx/windows/` (dpapi, window capture, sandbox)

