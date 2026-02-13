"""Gate: acceptance criteria bullets must have deterministic validators.

This is the minimal enforcement hook for the "4 pillars" effort:
- Accuracy/Citeability: we can point from each item to runnable validators.
- Security/Performance: gate itself is fast and deterministic.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from tools.traceability.validate_traceability import validate_traceability  # noqa: E402


def main() -> int:
    repo_root = _REPO_ROOT
    traceability_path = repo_root / "tools" / "traceability" / "traceability.json"
    ok, issues = validate_traceability(repo_root, traceability_path)
    if ok:
        print("OK: acceptance coverage")
        return 0
    for issue in issues[:80]:
        print(f"{issue.code}: {issue.detail}")
    print(f"FAIL: acceptance coverage (issues={len(issues)})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
