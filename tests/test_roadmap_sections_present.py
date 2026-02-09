from __future__ import annotations

from pathlib import Path


def test_roadmap_contains_all_phases() -> None:
    repo = Path(__file__).resolve().parents[1]
    text = (repo / "docs/roadmap.md").read_text(encoding="utf-8")
    for needle in [
        "# Roadmap (Adversarial Redesign Phases)",
        "## Phase 0 (2026-02-06 to 2026-02-20)",
        "## Phase 1 (2026-02-21 to 2026-03-31)",
        "## Phase 2 (2026-04-01 to 2026-05-31)",
        "## Phase 3 (2026-06-01 to 2026-07-31)",
    ]:
        assert needle in text, f"docs/roadmap.md missing: {needle}"

