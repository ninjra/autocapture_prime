#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 '<bash command>'" >&2
  exit 2
fi

LINTER="/home/justi/.codex/skills/shell-lint-ps-wsl/scripts/shell-lint.mjs"
CMD="$1"

if command -v node >/dev/null 2>&1; then
  printf '%s\n' "${CMD}" | node "${LINTER}" --shell bash >/dev/null
fi

bash -lc "${CMD}"
