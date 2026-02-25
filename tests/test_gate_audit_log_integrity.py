from __future__ import annotations

import json
from pathlib import Path

from autocapture_nx.kernel.audit import append_audit_event
from tools import gate_audit_log_integrity as mod


def test_evaluate_audit_log_passes_for_valid_append_only_rows(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    append_audit_event(action="stage1.marker.write", actor="unit", outcome="ok", details={"x": 1}, log_path=log_path)
    append_audit_event(action="retention.marker.write", actor="unit", outcome="ok", details={"x": 2}, log_path=log_path)
    out = mod.evaluate_audit_log(path=log_path, allow_missing=False)
    assert out["ok"] is True
    assert (out.get("issues") or {}) == {}
    assert int((out.get("counts") or {}).get("valid", 0) or 0) == 2


def test_evaluate_audit_log_fails_on_invalid_json(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    log_path.write_text("{bad json}\n", encoding="utf-8")
    out = mod.evaluate_audit_log(path=log_path, allow_missing=False)
    assert out["ok"] is False
    assert int((out.get("issues") or {}).get("invalid_json", 0) or 0) == 1


def test_main_writes_output_payload(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    out_path = tmp_path / "gate.json"
    append_audit_event(action="config.profile.change", actor="unit", outcome="ok", details={"profile": "golden"}, log_path=log_path)
    rc = mod.main(["--log", str(log_path), "--output", str(out_path)])
    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert str(payload.get("overall_chain_hash") or "") != ""


def test_timestamp_regression_is_warning_not_blocking(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    log_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema_version": 1,
                        "ts_utc": "2026-02-25T10:00:01Z",
                        "action": "a",
                        "actor": "unit",
                        "outcome": "ok",
                    }
                ),
                json.dumps(
                    {
                        "schema_version": 1,
                        "ts_utc": "2026-02-25T10:00:00Z",
                        "action": "b",
                        "actor": "unit",
                        "outcome": "ok",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out = mod.evaluate_audit_log(path=log_path, allow_missing=False)
    assert out["ok"] is True
    assert int((out.get("warnings") or {}).get("timestamp_regression", 0) or 0) == 1
