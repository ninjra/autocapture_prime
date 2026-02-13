from __future__ import annotations

import types

import pytest

from autocapture_nx.storage.retention import evaluate_disk_pressure, should_pause_capture


def test_disk_pressure_hard_watermark_halts(monkeypatch: pytest.MonkeyPatch) -> None:
    # Hard watermark is expressed in MB. If free_bytes <= hard_mb, we must hard-halt.
    cfg = {
        "storage": {
            "data_dir": ".",
            "disk_pressure": {"watermark_hard_mb": 100, "watermark_soft_mb": 0, "warn_free_gb": 200, "soft_free_gb": 100, "critical_free_gb": 50},
        }
    }

    def fake_usage(_path):
        # 50MB free, under hard watermark (100MB).
        return types.SimpleNamespace(total=10_000_000_000, used=9_950_000_000, free=50 * 1024 * 1024)

    monkeypatch.setattr("shutil.disk_usage", fake_usage)
    decision = evaluate_disk_pressure(cfg, data_dir=".")
    assert decision.level == "critical"
    assert decision.hard_halt is True
    assert should_pause_capture(decision) is True


def test_disk_pressure_soft_level_does_not_hard_halt(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {
        "storage": {
            "data_dir": ".",
            "disk_pressure": {"watermark_hard_mb": 0, "watermark_soft_mb": 100, "warn_free_gb": 200, "soft_free_gb": 100, "critical_free_gb": 50},
        }
    }

    def fake_usage(_path):
        # 50MB free, under soft watermark (100MB) but no hard watermark set.
        return types.SimpleNamespace(total=10_000_000_000, used=9_950_000_000, free=50 * 1024 * 1024)

    monkeypatch.setattr("shutil.disk_usage", fake_usage)
    decision = evaluate_disk_pressure(cfg, data_dir=".")
    assert decision.level == "soft"
    assert decision.hard_halt is False
    assert should_pause_capture(decision) is False

