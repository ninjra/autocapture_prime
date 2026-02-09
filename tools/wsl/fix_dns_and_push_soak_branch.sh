#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"

branch="$(git branch --show-current 2>/dev/null || true)"
if [[ -z "$branch" ]]; then
  echo "ERROR: not on a git branch" >&2
  exit 2
fi

if ! getent hosts github.com >/dev/null 2>&1; then
  echo "WSL DNS looks broken (github.com not resolvable). Attempting fix via /etc/resolv.conf..." >&2
  echo "This will prompt for sudo." >&2
  sudo ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf
fi

if ! getent hosts github.com >/dev/null 2>&1; then
  echo "ERROR: github.com still not resolvable after resolv.conf fix." >&2
  echo "Current /etc/resolv.conf:" >&2
  (ls -l /etc/resolv.conf && sed -n '1,120p' /etc/resolv.conf) >&2 || true
  exit 3
fi

git fetch origin

# Keep branch current with origin/main (merge, fail loud on conflicts).
if git show-ref --verify --quiet refs/remotes/origin/main; then
  counts="$(git rev-list --left-right --count origin/main...HEAD 2>/dev/null || echo '')"
  behind="$(echo "$counts" | awk '{print $1}')"
  if [[ -n "${behind:-}" ]] && [[ "$behind" != "0" ]]; then
    echo "Merging origin/main into $branch (behind=$behind)..." >&2
    git merge --no-edit origin/main
  fi
fi

git push -u origin "$branch"
