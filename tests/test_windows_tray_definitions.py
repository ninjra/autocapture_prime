from pathlib import Path


def test_windows_tray_lresult_fallback():
    script = Path("autocapture_nx/windows/tray.py").read_text(encoding="utf-8")
    assert "LRESULT" in script
    assert "getattr" in script


def test_windows_tray_cursor_fallbacks():
    script = Path("autocapture_nx/windows/tray.py").read_text(encoding="utf-8")
    assert "HCURSOR" in script
    assert "HICON" in script
    assert "HBRUSH" in script


def test_windows_tray_wparam_lparam_fallbacks():
    script = Path("autocapture_nx/windows/tray.py").read_text(encoding="utf-8")
    assert "WPARAM" in script
    assert "LPARAM" in script
