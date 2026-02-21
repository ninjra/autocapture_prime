from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module(path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, Path(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_health_snapshot_emits_alerts_for_risk_and_db_churn() -> None:
    mod = _load_module("tools/soak/processing_health_snapshot.py", "processing_health_snapshot_tool")
    rows = [
        {
            "sla": {
                "pending_records": 200,
                "completed_records": 0,
                "throughput_records_per_s": 0.0,
                "projected_lag_hours": float("inf"),
                "retention_risk": True,
            },
            "metadata_db_guard": {"ok": False, "reason": "metadata_db_churn_detected"},
        }
    ]
    out = mod.build_health_snapshot(rows, tail=10)
    assert bool(out.get("ok", False))
    alerts = [str(x) for x in (out.get("alerts") or [])]
    assert "retention_risk" in alerts
    assert "metadata_db_unstable" in alerts
    assert "throughput_zero_with_backlog" in alerts
