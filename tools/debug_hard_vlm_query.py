#!/usr/bin/env python3
"""Run a query and print display + hard_vlm debug payload."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--query", required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    py = root / ".venv" / "bin" / "python"
    env = dict(**__import__("os").environ)
    env["AUTOCAPTURE_CONFIG_DIR"] = str(args.config_dir)
    env["AUTOCAPTURE_DATA_DIR"] = str(args.data_dir)
    proc = subprocess.run(
        [str(py), "-m", "autocapture_nx", "query", str(args.query)],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(json.dumps({"ok": False, "error": proc.stderr.strip() or proc.stdout.strip()}))
        return 1
    out = json.loads(proc.stdout or "{}")
    display = ((out.get("answer") or {}).get("display") or {}) if isinstance(out, dict) else {}
    hard_vlm = ((out.get("processing") or {}).get("hard_vlm") or {}) if isinstance(out, dict) else {}
    print(json.dumps({"display": display, "hard_vlm": hard_vlm}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
