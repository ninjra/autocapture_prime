"""Run unittest test files in isolated subprocesses (resource-stability focused).

Motivation:
  - `python -m unittest discover` runs the whole suite in one process.
  - In constrained environments (notably WSL), memory can accumulate across tests,
    leading to OOM / host instability.

This runner executes each `tests/test_*.py` file in a fresh subprocess with an
optional timeout, which bounds per-test-file resource growth and makes it easy
to identify hangs.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _iter_test_files(repo_root: Path) -> list[Path]:
    tests_dir = repo_root / "tests"
    files = sorted(p for p in tests_dir.glob("test_*.py") if p.is_file())
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=float(os.environ.get("AUTO_CAPTURE_UNITTEST_FILE_TIMEOUT_S", "600")),
        help="Per test file timeout in seconds (default: 600 or env AUTO_CAPTURE_UNITTEST_FILE_TIMEOUT_S).",
    )
    parser.add_argument(
        "--start-at",
        default="",
        help="Optional test file basename to start at (e.g. test_config.py).",
    )
    parser.add_argument(
        "--pattern",
        default="test_*.py",
        help="Currently only supports the default top-level tests glob; kept for future compatibility.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    test_files = _iter_test_files(repo_root)
    if not test_files:
        print("ERROR: no test files found under tests/test_*.py", file=sys.stderr)
        return 2

    if args.start_at:
        start_idx = None
        for i, p in enumerate(test_files):
            if p.name == args.start_at:
                start_idx = i
                break
        if start_idx is None:
            print(f"ERROR: --start-at not found: {args.start_at}", file=sys.stderr)
            return 2
        test_files = test_files[start_idx:]

    py = sys.executable
    timeout_s = args.timeout_s

    for path in test_files:
        rel = path.relative_to(repo_root)
        # Use unittest discovery per-file to mirror the repo's existing
        # `unittest discover` behavior:
        # - Import the module (catching import-time failures).
        # - Run only unittest.TestCase-derived tests.
        # - Do NOT fail with exit=5 when the file contains zero unittest tests
        #   (common here because some tests are pytest-style).
        cmd = [py, "-m", "unittest", "discover", "-s", "tests", "-p", path.name, "-q"]
        print(f"[shard] {rel}")
        try:
            result = subprocess.run(cmd, cwd=repo_root, env=os.environ.copy(), timeout=timeout_s)
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT: {rel} (>{timeout_s}s)", file=sys.stderr)
            return 124
        if result.returncode == 5:
            # `unittest` uses exit code 5 when discovery yields no tests.
            # This repo contains some pytest-style `test_*.py` files that
            # intentionally do not contribute to the unittest suite.
            continue
        if result.returncode != 0:
            print(f"FAILED: {rel} (exit={result.returncode})", file=sys.stderr)
            return result.returncode

    print("OK: sharded unittest run passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
