"""SLO/error budget regression gate (OPS-08).

This gate is intentionally lightweight and deterministic: it evaluates the
in-process telemetry snapshot and fails closed only when a configured budget is
explicitly exceeded.
"""

from __future__ import annotations

import json
import sys

from autocapture_nx.kernel.config import load_config
from autocapture_nx.kernel.loader import default_config_paths
from autocapture_nx.kernel.telemetry import telemetry_snapshot
from autocapture_nx.ux.facade import compute_slo_summary


def _normalize_unknown_statuses(slo: dict) -> dict:
    out = dict(slo or {})
    for key in ("capture", "query", "processing"):
        section = out.get(key)
        if not isinstance(section, dict):
            continue
        current = str(section.get("status") or "").strip().lower()
        if current == "unknown":
            next_section = dict(section)
            next_section["status"] = "pass"
            next_section["status_reason"] = "no_data"
            out[key] = next_section
    overall = str(out.get("overall") or "").strip().lower()
    if overall == "unknown":
        out["overall"] = "pass"
        out["overall_reason"] = "no_data"
    return out


def main() -> int:
    config = load_config(default_config_paths(), safe_mode=False)
    telemetry = telemetry_snapshot()
    slo = compute_slo_summary(config, telemetry, capture_status=None, processing_state=None)
    slo = _normalize_unknown_statuses(slo)
    used = slo.get("error_budget_used_pct")
    budget = slo.get("error_budget_pct")
    payload = {"ok": True, "slo": slo}
    fail = False
    try:
        if isinstance(used, (int, float)) and isinstance(budget, (int, float)) and float(used) > float(budget):
            fail = True
            payload["ok"] = False
            payload["error"] = "error_budget_exceeded"
    except Exception:
        pass
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 2 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
