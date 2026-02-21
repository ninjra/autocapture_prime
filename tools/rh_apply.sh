#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
prompt_file="${repo_root}/docs/handoffs/research_hypervisor_codex_prompt.txt"
hypervisor_repo="/mnt/d/projects/hypervisor"

if [[ ! -f "${prompt_file}" ]]; then
  echo "{\"ok\":false,\"error\":\"missing_prompt_file\",\"path\":\"${prompt_file}\"}"
  exit 2
fi
if [[ ! -d "${hypervisor_repo}" ]]; then
  echo "{\"ok\":false,\"error\":\"missing_hypervisor_repo\",\"path\":\"${hypervisor_repo}\"}"
  exit 2
fi

"${repo_root}/tools/rh.sh" >/tmp/rh_last.json || true
cd "${hypervisor_repo}"
codex "$(cat "${prompt_file}")"
