#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


def main() -> int:
    py = str(REPO_ROOT / ".venv" / "bin" / "python")
    if not Path(py).exists():
        py = sys.executable

    checks = [
        [py, "tools/gate_chronicle_contract_drift.py"],
        [py, "tools/chronicle_codegen.py", "--check"],
    ]
    for cmd in checks:
        rc, out = _run(cmd)
        sys.stdout.write(out)
        if rc != 0:
            return rc

    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "preflight.yml"
        spool = REPO_ROOT / "tests" / "fixtures" / "chronicle_spool"
        store = Path(td) / "store"
        cfg.write_text(
            "\n".join(
                [
                    "spool:",
                    f"  root_dir_linux: {spool}",
                    "storage:",
                    f"  root_dir: {store}",
                    "vllm:",
                    "  base_url: http://127.0.0.1:8000",
                ]
            ),
            encoding="utf-8",
        )
        cmd = [py, "tools/preflight_runtime.py", "--config", str(cfg), "--skip-gpu", "--skip-vllm"]
        rc, out = _run(cmd)
        sys.stdout.write(out)
        if rc != 0:
            return rc
    print("OK: chronicle stack gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
