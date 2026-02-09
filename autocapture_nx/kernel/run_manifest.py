"""Run manifest helpers.

META-09: record determinism inputs explicitly (tz/locale/RNG seeds) so replay is auditable.
"""

from __future__ import annotations

import locale
from dataclasses import dataclass
from typing import Any

from autocapture_nx.kernel.rng import RNGService


def _locale_name() -> str:
    try:
        lang, enc = locale.getlocale()
        if lang and enc:
            return f"{lang}.{enc}"
        if lang:
            return str(lang)
    except Exception:
        pass
    # Fall back to the deterministic locale we attempt to set in determinism.py.
    return "C"


def determinism_inputs(config: dict[str, Any]) -> dict[str, Any]:
    runtime = config.get("runtime", {}) if isinstance(config, dict) else {}
    time_cfg = config.get("time", {}) if isinstance(config, dict) else {}
    tz = str(runtime.get("timezone") or time_cfg.get("timezone") or "UTC")
    rng = RNGService.from_config(config)
    run_seed = 0
    run_seed_hex = "0000000000000000"
    try:
        seed = rng.seed_for_plugin("__manifest__")
        run_seed = int(seed.run_seed)
        run_seed_hex = f"{int(seed.run_seed):016x}"
    except Exception:
        run_seed = 0
        run_seed_hex = "0000000000000000"
    return {
        "timezone": tz,
        "locale": _locale_name(),
        "rng": {
            "enabled": bool(rng.enabled),
            "strict": bool(rng.strict),
            "run_seed": int(run_seed),
            "run_seed_hex": str(run_seed_hex),
        },
    }

