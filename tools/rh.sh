#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exporter="${repo_root}/tools/export_research_hypervisor_bundle.sh"
prompt_file="${repo_root}/docs/handoffs/research_hypervisor_codex_prompt.txt"

if [[ ! -x "${exporter}" ]]; then
  echo "{\"ok\":false,\"error\":\"missing_exporter\",\"path\":\"${exporter}\"}"
  exit 2
fi

out_json="$("${exporter}")"
out_dir="$(printf '%s' "${out_json}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("out_dir",""))')"
if [[ -z "${out_dir}" ]]; then
  echo "{\"ok\":false,\"error\":\"bundle_export_failed\",\"raw\":${out_json@Q}}"
  exit 2
fi

if [[ ! -f "${prompt_file}" ]]; then
  echo "{\"ok\":false,\"error\":\"missing_prompt_file\",\"path\":\"${prompt_file}\"}"
  exit 2
fi

cmd="cd /mnt/d/projects/hypervisor && codex \"\$(cat ${prompt_file})\""
python3 - "$out_dir" "$cmd" <<'PY'
import json
import sys

bundle = sys.argv[1]
cmd = sys.argv[2]
print(json.dumps({"ok": True, "bundle": bundle, "hypervisor_codex_cmd": cmd}))
PY
