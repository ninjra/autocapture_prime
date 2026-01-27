"""Run the full local test + invariant suite in a single command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def _run(cmd: list[str], env: dict[str, str]) -> int:
    result = subprocess.run(cmd, env=env)
    if result.returncode != 0:
        print(f"FAILED: {' '.join(cmd)}")
    return result.returncode


def _commands(py: str) -> Iterable[list[str]]:
    return [
        [py, "tools/gate_deps_lock.py"],
        [py, "tools/gate_canon.py"],
        [py, "tools/gate_concurrency.py"],
        [py, "tools/gate_ledger.py"],
        [py, "tools/gate_perf.py"],
        [py, "tools/gate_security.py"],
        [py, "tools/gate_static.py"],
        [py, "tools/gate_vuln.py"],
        [py, "tools/gate_doctor.py"],
        [py, "-m", "autocapture_nx", "doctor"],
        [py, "-m", "autocapture_nx", "--safe-mode", "doctor"],
        [py, "-m", "unittest", "tests/test_blueprint_spec_validation.py", "-q"],
        [py, "-m", "unittest", "discover", "-s", "tests", "-q"],
    ]


def _write_log(log_path: Path, message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    line = f"[{timestamp}] {message}"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")
    print(line)


def _write_report(report_path: Path, log_path: Path, status: str, step: str, exit_code: int, python_exe: str) -> None:
    tail: list[str] = []
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8").splitlines()
        tail = lines[-60:]
    payload = {
        "status": status,
        "failed_step": step,
        "exit_code": exit_code,
        "python": python_exe,
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "log_path": str(log_path),
        "tail": tail,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"REPORT: status={status} failed_step={step} exit_code={exit_code} log_path={log_path}")


def _ensure_venv(repo_root: Path, bootstrap: str) -> Path:
    venv_path = repo_root / ".venv"
    python_path = venv_path / "bin" / "python"
    if python_path.exists():
        return python_path
    subprocess.check_call([bootstrap, "-m", "venv", str(venv_path)])
    return python_path


def _pip_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    tmp_dir = repo_root / ".dev" / "pip_tmp"
    cache_dir = repo_root / ".dev" / "pip_cache"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    env.setdefault("TMPDIR", str(tmp_dir))
    env.setdefault("PIP_CACHE_DIR", str(cache_dir))
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    return env


def _ensure_pip(python_exe: str, repo_root: Path) -> None:
    env = _pip_env(repo_root)
    subprocess.check_call([python_exe, "-m", "ensurepip", "--upgrade"], env=env)
    subprocess.check_call([python_exe, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], env=env)


def _module_exists(python_exe: str, module: str) -> bool:
    result = subprocess.run([python_exe, "-c", f"import {module}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def _ensure_tooling(repo_root: Path, log_path: Path) -> str | None:
    system_py = sys.executable
    if _module_exists(system_py, "ruff") and _module_exists(system_py, "mypy") and _module_exists(system_py, "pip_audit"):
        return None
    tools_venv = repo_root / ".dev" / "tools_venv"
    tool_python = tools_venv / "bin" / "python"
    if not tool_python.exists():
        _write_log(log_path, f"Creating tooling venv at {tools_venv}")
        subprocess.check_call([system_py, "-m", "venv", str(tools_venv)])
    _ensure_pip(str(tool_python), repo_root)

    wheelhouse = os.environ.get("AUTO_CAPTURE_WHEELHOUSE")
    if not wheelhouse:
        candidate = repo_root / "wheels"
        if candidate.exists():
            wheelhouse = str(candidate)
    allow_network = os.environ.get("AUTO_CAPTURE_ALLOW_NETWORK", "1")
    cmd = [str(tool_python), "-m", "pip", "install", "ruff", "mypy", "pip-audit"]
    if wheelhouse:
        cmd.extend(["--no-index", "--find-links", wheelhouse])
    elif allow_network != "1":
        raise SystemExit(
            "Missing ruff/mypy and no wheelhouse found. Set AUTO_CAPTURE_WHEELHOUSE or AUTO_CAPTURE_ALLOW_NETWORK=1."
        )
    env = _pip_env(repo_root)
    _write_log(log_path, "Installing ruff/mypy tooling")
    subprocess.check_call(cmd, env=env)
    return str(tool_python)


def main() -> int:
    env = os.environ.copy()
    root = Path(__file__).resolve().parents[1]
    env.setdefault("PYTHONPATH", str(root))
    test_root = root / ".dev" / "test_env"
    if test_root.exists():
        import shutil

        shutil.rmtree(test_root)
    config_dir = test_root / "config"
    data_dir = test_root / "data"
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    env.setdefault("AUTOCAPTURE_CONFIG_DIR", str(config_dir))
    env.setdefault("AUTOCAPTURE_DATA_DIR", str(data_dir))
    log_path = root / "tools" / "run_all_tests.log"
    report_path = root / "tools" / "run_all_tests_report.json"
    log_path.write_text("", encoding="utf-8")
    print(f"Logging to: {log_path}")
    print(f"Report to: {report_path}")

    try:
        tool_python = _ensure_tooling(root, log_path)
        if tool_python:
            env["AUTO_CAPTURE_TOOL_PYTHON"] = tool_python
    except Exception as exc:
        _write_log(log_path, f"FAILED: tooling ({exc})")
        _write_report(report_path, log_path, "failed", "tooling", 1, str(sys.executable))
        return 1

    for cmd in _commands(sys.executable):
        step = " ".join(cmd[1:]) if len(cmd) > 1 else "command"
        _write_log(log_path, f"Running: {' '.join(cmd)}")
        code = _run(cmd, env)
        if code != 0:
            _write_report(report_path, log_path, "failed", step, code, str(sys.executable))
            return code
    _write_report(report_path, log_path, "ok", "complete", 0, str(sys.executable))
    print("OK: all tests and invariants passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
