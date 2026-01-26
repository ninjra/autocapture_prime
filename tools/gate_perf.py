"""Gate: lightweight performance regression checks."""

from __future__ import annotations

import time

from autocapture_nx.kernel.config import load_config
from autocapture_nx.kernel.loader import Kernel, default_config_paths


def main() -> int:
    paths = default_config_paths()
    config = load_config(paths, safe_mode=True)
    perf_cfg = config.get("performance", {})
    startup_target = int(perf_cfg.get("startup_ms", 1000))
    max_startup_ms = max(startup_target * 5, 3000)

    t0 = time.perf_counter()
    Kernel(paths, safe_mode=True).boot()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    print(f"startup_ms={elapsed_ms:.1f} max_ms={max_startup_ms}")
    if elapsed_ms > max_startup_ms:
        print("FAIL: startup time regression")
        return 1
    print("OK: perf gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
