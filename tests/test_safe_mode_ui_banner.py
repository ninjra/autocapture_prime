from __future__ import annotations

from pathlib import Path


def test_safe_mode_banner_present_in_ui() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "autocapture" / "web" / "ui" / "index.html").read_text(encoding="utf-8")
    assert "id=\"safeModeCard\"" in html
    assert "data-safe-mode-banner" in html


def test_safe_mode_banner_is_wired_in_app_js() -> None:
    root = Path(__file__).resolve().parents[1]
    js = (root / "autocapture" / "web" / "ui" / "app.js").read_text(encoding="utf-8")
    assert "renderSafeModeCard" in js
    assert "safeModeCard" in js

