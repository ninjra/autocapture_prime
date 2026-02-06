"""Gate: doctor checks must pass."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autocapture_nx.kernel.loader import Kernel, default_config_paths  # noqa: E402


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    base = root / ".dev" / "doctor_data"
    base.mkdir(parents=True, exist_ok=True)
    previous = os.environ.get("AUTOCAPTURE_DATA_DIR")
    result = 0
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
        try:
            kernel = Kernel(default_config_paths(), safe_mode=True)
            kernel.boot()
            checks = kernel.doctor()
            failures = [check for check in checks if not check.ok]
            for check in failures:
                print(f"FAIL {check.name}: {check.detail}")
            if failures:
                result = 1
            else:
                print("OK: doctor gate")
                result = 0
        finally:
            if previous is None:
                os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
            else:
                os.environ["AUTOCAPTURE_DATA_DIR"] = previous
    return result


if __name__ == "__main__":
    raise SystemExit(main())
