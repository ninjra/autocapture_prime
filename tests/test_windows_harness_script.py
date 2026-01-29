from pathlib import Path


def test_run_all_tests_invokes_tray_launcher_checks():
    script = Path("tools/run_all_tests.ps1").read_text(encoding="utf-8")
    assert "tray_launcher_selftest" in script
    assert "tray_launcher_smoketest" in script


def test_run_all_tests_avoids_cmdline_quoting_hack():
    script = Path("tools/run_all_tests.ps1").read_text(encoding="utf-8")
    assert '2>&1"' not in script
    assert "cmd /c" not in script


def test_run_all_tests_defaults_windows_venv():
    script = Path("tools/run_all_tests.ps1").read_text(encoding="utf-8")
    assert ".venv_win" in script
