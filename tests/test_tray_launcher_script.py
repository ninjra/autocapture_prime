from pathlib import Path


def test_launch_tray_script_avoids_colon_var_parsing():
    script = Path("ops/dev/launch_tray.ps1").read_text(encoding="utf-8")
    assert "$host:$port" not in script
    assert "$host:$port/" not in script
    assert "$bindHost:$bindPort" not in script
    assert "$bindHost:$bindPort/" not in script


def test_launch_tray_script_logs():
    script = Path("ops/dev/launch_tray.ps1").read_text(encoding="utf-8")
    assert "tray_launcher.latest.log" in script
    assert "tray_launcher_" in script


def test_launch_tray_opens_log_on_error():
    script = Path("ops/dev/launch_tray.ps1").read_text(encoding="utf-8")
    assert "notepad.exe" in script


def test_shortcut_uses_noexit():
    script = Path("ops/dev/create_tray_shortcut.ps1").read_text(encoding="utf-8")
    assert "-NoExit" in script


def test_launcher_reads_user_config():
    script = Path("ops/dev/launch_tray.ps1").read_text(encoding="utf-8")
    assert "config\\user.json" in script


def test_launcher_sets_pythonpath_and_pid():
    script = Path("ops/dev/launch_tray.ps1").read_text(encoding="utf-8")
    assert "PYTHONPATH" in script
    assert "tray.pid" in script


def test_launcher_captures_process_log():
    script = Path("ops/dev/launch_tray.ps1").read_text(encoding="utf-8")
    assert "tray_process.out.log" in script
    assert "tray_process.err.log" in script
    assert "tray_process.log" not in script


def test_launcher_root_resolution():
    script = Path("ops/dev/launch_tray.ps1").read_text(encoding="utf-8")
    assert "..\\..\"))" in script or "..\\..\"))" in script


def test_launcher_skips_wsl_venv():
    script = Path("ops/dev/launch_tray.ps1").read_text(encoding="utf-8")
    assert "pyvenv.cfg" in script
    assert "home\\s*=\\s*/" in script


def test_launcher_avoids_host_assignment():
    script = Path("ops/dev/launch_tray.ps1").read_text(encoding="utf-8")
    assert "$host =" not in script
    assert "$Host =" not in script


def test_launcher_has_selftest_and_smoketest():
    script = Path("ops/dev/launch_tray.ps1").read_text(encoding="utf-8")
    assert "SelfTest" in script
    assert "SmokeTest" in script
    assert "AUTOCAPTURE_TRAY_SMOKE" in script


def test_launcher_has_windows_venv_fallback():
    script = Path("ops/dev/launch_tray.ps1").read_text(encoding="utf-8")
    assert ".venv_win" in script


def test_launcher_has_log_helper():
    script = Path("ops/dev/launch_tray.ps1").read_text(encoding="utf-8")
    assert "Write-LogLine" in script


def test_launcher_sets_python_env_override():
    script = Path("ops/dev/launch_tray.ps1").read_text(encoding="utf-8")
    assert "AUTOCAPTURE_PYTHON_EXE" in script


def test_launcher_module_check_redirects_error():
    script = Path("ops/dev/launch_tray.ps1").read_text(encoding="utf-8")
    assert "Module check failed" in script
