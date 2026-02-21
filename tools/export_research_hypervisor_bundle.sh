#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$ROOT/artifacts/handoffs/research_to_hypervisor_${STAMP}"

mkdir -p "$OUT_DIR/autocapture/research" "$OUT_DIR/plugins/builtin/research_default" "$OUT_DIR/docs"

cp -f "$ROOT/autocapture/research/"*.py "$OUT_DIR/autocapture/research/"
cp -f "$ROOT/plugins/builtin/research_default/plugin.py" "$OUT_DIR/plugins/builtin/research_default/"
cp -f "$ROOT/plugins/builtin/research_default/plugin.json" "$OUT_DIR/plugins/builtin/research_default/"
cp -f "$ROOT/docs/handoffs/research_hypervisor_migration.md" "$OUT_DIR/docs/"
cp -f "$ROOT/docs/handoffs/research_hypervisor_codex_prompt.txt" "$OUT_DIR/docs/"

cat > "$OUT_DIR/README.md" <<'EOF'
# Research Migration Bundle (autocapture_prime -> hypervisor)

This bundle contains the research subsystem extracted from autocapture_prime.

Included:
- autocapture/research/*.py
- plugins/builtin/research_default/plugin.py
- plugins/builtin/research_default/plugin.json
- docs/research_hypervisor_migration.md
- docs/research_hypervisor_codex_prompt.txt

Usage:
1. Copy into hypervisor repo.
2. Ask Codex in hypervisor to execute the migration prompt file.
EOF

echo "{\"ok\":true,\"out_dir\":\"$OUT_DIR\"}"
