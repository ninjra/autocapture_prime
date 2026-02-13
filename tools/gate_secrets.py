#!/usr/bin/env python3
"""Fail if repo-tracked files appear to contain secrets.

This is a lightweight, heuristic gate meant to catch obvious mistakes:
- API keys (e.g., OpenAI `sk-...`)
- AWS access keys
- Private key headers
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from autocapture_nx.kernel.redaction import redact_text


def _git_ls_files(repo_root: Path) -> list[str]:
    out = subprocess.check_output(["git", "ls-files"], cwd=str(repo_root))
    return [line.strip() for line in out.decode("utf-8", errors="replace").splitlines() if line.strip()]


def _is_text_file(path: Path) -> bool:
    # Fast heuristic: treat common binaries as non-text.
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".mp4", ".sqlite", ".db"}:
        return False
    return True


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    # Allowlist files that intentionally contain "secret-shaped" strings for
    # redaction/validator tests. Keep this list tight to avoid masking real leaks.
    allowlisted = {
        "tests/test_log_redaction.py",
    }
    findings: list[tuple[str, str]] = []
    for rel in _git_ls_files(repo_root):
        if rel in allowlisted:
            continue
        p = (repo_root / rel).resolve()
        if not p.exists() or not p.is_file():
            continue
        if not _is_text_file(p):
            continue
        try:
            if p.stat().st_size > 2_000_000:
                continue
        except Exception:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        redacted = redact_text(text)
        if redacted != text:
            findings.append((rel, "redaction_patterns_matched"))
    if not findings:
        print("OK: secrets gate")
        return 0
    for rel, code in findings[:200]:
        print(f"secret:{code}:{rel}")
    print(f"FAIL: secrets gate (findings={len(findings)})")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
