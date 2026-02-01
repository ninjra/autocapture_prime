"""Environment normalization for deterministic kernel behavior."""

from __future__ import annotations

import locale
import os
import time
from typing import Any


def apply_runtime_determinism(config: dict[str, Any]) -> None:
    runtime = config.get("runtime", {}) if isinstance(config, dict) else {}
    time_cfg = config.get("time", {}) if isinstance(config, dict) else {}
    tz = runtime.get("timezone") or time_cfg.get("timezone") or "UTC"
    try:
        os.environ["TZ"] = str(tz)
        if hasattr(time, "tzset"):
            time.tzset()
    except Exception:
        pass

    for candidate in ("C.UTF-8", "C"):
        try:
            locale.setlocale(locale.LC_ALL, candidate)
            break
        except Exception:
            continue
