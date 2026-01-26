"""Run the full local test + invariant suite in a single command."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable


def _run(cmd: list[str], env: dict[str, str]) -> int:
    result = subprocess.run(cmd, env=env)
    if result.returncode != 0:
        print(f"FAILED: {' '.join(cmd)}")
    return result.returncode


def _commands() -> Iterable[list[str]]:
    py = sys.executable
    return [
        [py, "tools/gate_deps_lock.py"],
        [py, "tools/gate_canon.py"],
        [py, "tools/gate_concurrency.py"],
        [py, "tools/gate_ledger.py"],
        [py, "tools/gate_perf.py"],
        [py, "tools/gate_security.py"],
        [py, "tools/gate_static.py"],
        [py, "tools/gate_doctor.py"],
        [py, "-m", "autocapture_nx", "doctor"],
        [py, "-m", "autocapture_nx", "--safe-mode", "doctor"],
        [py, "-m", "unittest", "tests/test_blueprint_spec_validation.py", "-q"],
        [py, "-m", "unittest", "discover", "-s", "tests", "-q"],
    ]


def main() -> int:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    root = Path(__file__).resolve().parents[1]
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
    for cmd in _commands():
        code = _run(cmd, env)
        if code != 0:
            return code
    print("OK: all tests and invariants passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
