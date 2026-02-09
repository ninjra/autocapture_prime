from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_text(relpath: str) -> str:
    path = _repo_root() / relpath
    assert path.exists(), f"missing: {relpath}"
    return path.read_text(encoding="utf-8")


def _assert_contains_all(text: str, needles: list[str], *, relpath: str) -> None:
    missing = [n for n in needles if n not in text]
    assert not missing, f"{relpath} missing expected sections/phrases: {missing}"


def test_operator_runbook_has_required_sections() -> None:
    md = _read_text("docs/runbook.md")
    _assert_contains_all(
        md,
        [
            "# Operator Runbook",
            "## Backup and Restore",
            "## Safe Mode Triage",
            "## Plugin Rollback",
            "## Disk Pressure",
            "## Integrity Verification",
            "## Diagnostics",
        ],
        relpath="docs/runbook.md",
    )


def test_safe_mode_doc_has_required_sections() -> None:
    md = _read_text("docs/safe_mode.md")
    _assert_contains_all(
        md,
        [
            "# Safe Mode",
            "## How To Check Safe Mode",
            "## Common Reasons",
            "## Deterministic Next Steps (Checklist)",
            "Fail closed",
        ],
        relpath="docs/safe_mode.md",
    )

