"""Wrapper to run pillar gates via the codex CLI."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_ALLOW_ENV = {
    "PATH",
    "PYTHONPATH",
    "PYTHONUTF8",
    "AUTOCAPTURE_CONFIG_DIR",
    "AUTOCAPTURE_DATA_DIR",
    "AUTOCAPTURE_PYTHON_EXE",
    "AUTOCAPTURE_TRAY_SMOKE",
    "AUTOCAPTURE_TRAY_BIND_HOST",
    "AUTOCAPTURE_TRAY_BIND_PORT",
    "DEV_BACKEND_CMD",
    "DEV_UI_CMD",
    "DEV_UI_BACKEND_URL",
    "DEV_BACKEND_PORT",
    "DEV_UI_PORT",
}


def _filtered_env(root: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _ALLOW_ENV}
    env.setdefault("PYTHONPATH", str(root))
    env.setdefault("PYTHONUTF8", "1")
    return env


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report_dir = root / "artifacts" / "pillar_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    log_path = report_dir / "gate_pillars.log"
    cmd = [sys.executable, "-m", "autocapture_nx", "codex", "pillar-gates"]
    env = _filtered_env(root)
    result = subprocess.run(cmd, cwd=str(root), env=env, capture_output=True, text=True)
    output = (result.stdout or "") + (result.stderr or "")
    log_path.write_text(output, encoding="utf-8")
    if output:
        sys.stdout.write(output)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
