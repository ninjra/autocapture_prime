# Autocapture MX Evidence Bundle

Captured: 2026-01-26 (local, WSL)
Branch: autocaptureprime/mx-replace
Repo root: /mnt/d/projects/autocapture_prime

Authoritative sources
- docs/spec/autocapture_mx_spec.yaml
- docs/mx_gap_matrix.md
- docs/autocapture_mx_blueprint.md

Environment
- OS: WSL2 Linux (Windows 11 host)
- python3: Python 3.12.3
- pip: pip 24.0 (python 3.12)
- python (bare) is not available; use python3

Packaging and CLI wiring (pyproject.toml)
Command:
```
sed -n '1,120p' pyproject.toml
```
Excerpt:
```
[project]
name = "autocapture_nx"
...
[project.scripts]
autocapture = "autocapture_nx.cli:main"
...
[tool.setuptools]
packages = [
  "autocapture",
  "autocapture.config",
  "autocapture.core",
  "autocapture.codex",
  "autocapture.tools",
  "autocapture.plugins",
  "autocapture.memory",
  "autocapture.ux",
  "autocapture.runtime",
  "autocapture.storage",
  "autocapture.pillars",
  "autocapture.capture",
  "autocapture.ingest",
  "autocapture.indexing",
  "autocapture.retrieval",
  "autocapture.web",
  "autocapture.gateway",
  "autocapture.promptops",
  "autocapture.training",
  "autocapture.research",
  "autocapture.rules",
  "autocapture_nx",
  "autocapture_nx.kernel",
  "autocapture_nx.plugin_system",
  "autocapture_nx.windows",
]
```

Test runner evidence
Command:
```
python3 tools/run_all_tests.py
```
Excerpt:
```
----------------------------------------------------------------------
Ran 104 tests in 7.793s

OK (skipped=7)
OK: all tests and invariants passed
```

Appendix A spec snapshot (plugins + gateway)
Command:
```
sed -n '1,200p' docs/spec/autocapture_mx_spec.yaml
```
Excerpt:
```
  - id: MX-PLUGSET-0001
    validators:
      - type: plugins_have_ids
        required_plugin_ids:
          - mx.core.capture_win
          - mx.core.storage_sqlite
          - mx.core.ocr_local
          - mx.core.llm_local
          - mx.core.llm_openai_compat
          - mx.core.embed_local
          - mx.core.vector_local
          - mx.core.retrieval_tiers
          - mx.core.compression_and_verify
          - mx.core.egress_sanitizer
          - mx.core.export_import
          - mx.core.web_ui
          - mx.prompts.default
          - mx.training.default
          - mx.research.default
...
  - id: MX-GATEWAY-0001
    artifacts:
      - autocapture/gateway/app.py
      - autocapture/gateway/router.py
      - autocapture/gateway/schemas.py
```

Gap matrix baseline snapshot
Command:
```
sed -n '1,80p' docs/mx_gap_matrix.md
```
Excerpt:
```
Baseline date: 2026-01-25
...
### MX-CONFIG-0001 - Configuration loader with safe defaults (offline, cloud disabled)
Status: PARTIAL
...
### MX-PLUGSET-0001 - Built-in plugin set covers essential kinds and is enabled by default
Status: MISSING
```

Blueprint extension kinds snapshot
Command:
```
sed -n '260,320p' docs/autocapture_mx_blueprint.md
```
Excerpt:
```
MX supports (at minimum) the following kinds (superset of Ninjra's list):
...
- `spans_v2.backend`
...
MX extensions (required):
- `capture.source`
- `capture.encoder`
- `activity.signal`
- `egress.sanitizer`
- `export.bundle`
- `import.bundle`
- `storage.blob_backend`
- `storage.media_backend`
```

Risk scans (privacy, overwrite, network)
Command:
```
rg -n '\{"key"\s*:\s*str\(key\)\}' -S . || true
```
Excerpt:
```
(no matches)
```

Command:
```
rg -n "INSERT OR REPLACE|open\\(.*,\"w\"\\)" -S . || true
```
Excerpt:
```
./plugins/builtin/storage_sqlcipher/plugin.py:50:            "INSERT OR REPLACE INTO metadata (id, payload) VALUES (?, ?)",
./plugins/builtin/storage_sqlcipher/plugin.py:73:            "INSERT OR REPLACE INTO entity_map (token, value, kind) VALUES (?, ?, ?)",
```

Command:
```
rg -n "\\bsocket\\b|subprocess\\.|requests\\.|httpx\\." -S autocapture autocapture_plugins || true
```
Excerpt:
```
autocapture/codex/validators.py:32:def _run_command(command: Iterable[str]) -> subprocess.CompletedProcess:
autocapture/codex/validators.py:36:    return subprocess.run(cmd, env=env, capture_output=True, text=True)
autocapture/codex/validators.py:54:    result = subprocess.run(
autocapture/core/http.py:59:            with httpx.Client(timeout=self.timeout_s) as client:
```

Group A CLI checks
Command:
```
python3 -m autocapture_nx plugins list --json
```
Observed:
- JSON keys: plugins, extensions
- plugins count: 44
- extensions count: 25

Command:
```
python3 -m autocapture_nx codex validate --json
```
Observed:
- Exit code: 0
- Summary: 39/39 passed

Command:
```
python3 tools/run_all_tests.py
```
Observed:
- Exit code: 0
- Output: OK: all tests and invariants passed (106 tests, 7 skipped)

Command:
```
python3 -m autocapture_nx provenance verify
```
Observed:
- Exit code: 0
- Output: OK ledger_missing: data/ledger.ndjson
