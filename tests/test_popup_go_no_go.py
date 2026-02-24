from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tools import popup_go_no_go as mod


def test_go_no_go_passes_when_health_and_regression_pass(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "go_no_go.json"

    def _fake_http_json(*, url: str, timeout_s: float):  # noqa: ANN001
        return {"ok": True, "status": 200, "json": {"ok": True}}

    def _fake_run(*args, **kwargs):  # noqa: ANN001
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(mod, "_http_json", _fake_http_json)
    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    rc = mod.main(["--out", str(out), "--strict"])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    checks = payload.get("checks", [])
    assert isinstance(checks, list)
    assert len(checks) == 3
    assert all(bool(item.get("ok", False)) for item in checks)
    compact = payload.get("compact_summary", {})
    assert isinstance(compact, dict)
    assert int(compact.get("failed_count", 0) or 0) == 0


def test_go_no_go_fails_fast_on_bad_health(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "go_no_go.json"

    def _fake_http_json(*, url: str, timeout_s: float):  # noqa: ANN001
        if "8788" in url:
            return {"ok": True, "status": 200, "json": {"ok": False}}
        return {"ok": True, "status": 200, "json": {"ok": True}}

    monkeypatch.setattr(mod, "_http_json", _fake_http_json)
    rc = mod.main(["--out", str(out), "--strict"])
    assert rc == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    checks = payload.get("checks", [])
    assert isinstance(checks, list)
    regression = [item for item in checks if str(item.get("name") or "") == "popup_regression_strict"]
    assert len(regression) == 1
    assert regression[0]["ok"] is False
    assert str(regression[0].get("error") or "") == "prereq_health_failed"
    compact = regression[0].get("compact", {})
    assert isinstance(compact, dict)
    assert int(compact.get("failed_count", 0) or 0) == 0


def test_compact_regression_summary_reads_report(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "sample_count": 10,
                "accepted_count": 7,
                "failed_count": 3,
                "latency_p50_ms": 1234.5,
                "latency_p95_ms": 2345.6,
                "top_failure_class": "answer_quality",
                "top_failure_key": "state_not_ok",
            }
        ),
        encoding="utf-8",
    )
    compact = mod._compact_regression_summary(report)  # noqa: SLF001
    assert int(compact.get("sample_count", 0) or 0) == 10
    assert int(compact.get("accepted_count", 0) or 0) == 7
    assert int(compact.get("failed_count", 0) or 0) == 3
    assert float(compact.get("latency_p95_ms", 0.0) or 0.0) > float(compact.get("latency_p50_ms", 0.0) or 0.0)
    assert str(compact.get("top_failure_class") or "") == "answer_quality"
    assert str(compact.get("top_failure_key") or "") == "state_not_ok"
