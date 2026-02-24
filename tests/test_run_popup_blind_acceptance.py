from __future__ import annotations

import json
from pathlib import Path

from tools import run_popup_blind_acceptance as mod


def test_evaluate_popup_payload_accepts_strict_ok() -> None:
    payload = {
        "ok": True,
        "state": "ok",
        "summary": "Calendar: January 2026; selected date=20",
        "citations": [{"locator": {"record_id": "r1"}}],
    }
    out = mod._evaluate_popup_payload(payload)  # noqa: SLF001
    assert out.accepted is True
    assert out.reasons == []


def test_evaluate_popup_payload_rejects_indeterminate_and_missing_citations() -> None:
    payload = {"ok": True, "state": "ok", "summary": "Indeterminate: no data yet.", "citations": []}
    out = mod._evaluate_popup_payload(payload)  # noqa: SLF001
    assert out.accepted is False
    assert "summary_indeterminate" in out.reasons
    assert "citations_missing" in out.reasons


def test_failure_class_transport_vs_answer_quality() -> None:
    transport = mod._failure_class(  # noqa: SLF001
        accepted=False,
        http_ok=False,
        http_status=0,
        http_error="url_error:timed out",
        payload={},
    )
    answer = mod._failure_class(  # noqa: SLF001
        accepted=False,
        http_ok=True,
        http_status=200,
        http_error="",
        payload={"ok": True, "state": "ok"},
    )
    accepted = mod._failure_class(  # noqa: SLF001
        accepted=True,
        http_ok=True,
        http_status=200,
        http_error="",
        payload={"ok": True, "state": "ok"},
    )
    assert transport == "transport"
    assert answer == "answer_quality"
    assert accepted == "none"


def test_read_cases_supports_cases_wrapper(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {"id": "A", "question": "what am i working on"},
                    {"id": "B", "query": "count unread"},
                    {"id": "C", "query": ""},
                ]
            }
        ),
        encoding="utf-8",
    )
    rows = mod._read_cases(path)  # noqa: SLF001
    assert [row["id"] for row in rows] == ["A", "B"]
    assert [row["query"] for row in rows] == ["what am i working on", "count unread"]


def test_main_writes_report_and_misses(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps(
            [
                {"id": "Q1", "query": "query one"},
                {"id": "Q2", "query": "query two"},
            ]
        ),
        encoding="utf-8",
    )
    report = tmp_path / "report.json"
    misses = tmp_path / "misses.json"

    monkeypatch.setattr(mod, "_fetch_popup_token", lambda *args, **kwargs: "tok")

    def _fake_http_json(*, url: str, timeout_s: float, method: str = "GET", headers=None, payload=None):  # noqa: ANN001
        q = str((payload or {}).get("query") or "")
        if q == "query one":
            body = {
                "ok": True,
                "state": "ok",
                "summary": "answer one",
                "citations": [{"locator": {"record_id": "r1"}}],
                "query_run_id": "qry1",
            }
        else:
            body = {
                "ok": True,
                "state": "no_evidence",
                "summary": "Indeterminate: no data.",
                "citations": [],
                "query_run_id": "qry2",
            }
        return {"ok": True, "status": 200, "json": body}

    monkeypatch.setattr(mod, "_http_json", _fake_http_json)
    rc = mod.main(
        [
            "--cases",
            str(cases),
            "--sample-size",
            "2",
            "--seed",
            "7",
            "--out",
            str(report),
            "--misses-out",
            str(misses),
            "--strict",
        ]
    )
    assert rc == 1
    rep = json.loads(report.read_text(encoding="utf-8"))
    assert int(rep.get("sample_count", 0)) == 2
    assert int(rep.get("accepted_count", 0)) == 1
    assert int(rep.get("failed_count", 0)) == 1
    assert int(rep.get("answer_quality_failures_count", 0)) == 1
    assert int(rep.get("transport_failures_count", 0)) == 0
    assert float(rep.get("latency_p95_ms", 0.0) or 0.0) >= float(rep.get("latency_p50_ms", 0.0) or 0.0)
    assert str(rep.get("top_failure_class") or "") == "answer_quality"
    assert str(rep.get("top_failure_key") or "") == "state_not_ok"
    miss = json.loads(misses.read_text(encoding="utf-8"))
    cases_out = miss.get("cases", [])
    assert isinstance(cases_out, list)
    assert len(cases_out) == 1
    assert str(cases_out[0].get("query") or "") in {"query one", "query two"}
    observed = cases_out[0].get("observed", {})
    assert isinstance(observed, dict)
    assert str(observed.get("failure_class") or "") == "answer_quality"
