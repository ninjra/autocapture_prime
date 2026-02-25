from __future__ import annotations

import json
import pathlib
import subprocess
import sys


def _write_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_gate_golden_pipeline_triplet_passes_strict(tmp_path: pathlib.Path) -> None:
    popup = tmp_path / "popup.json"
    q40 = tmp_path / "q40.json"
    temporal = tmp_path / "temporal.json"
    out = tmp_path / "out.json"

    _write_json(
        popup,
        {
            "ok": True,
            "sample_count": 10,
            "accepted_count": 10,
            "failed_count": 0,
        },
    )
    _write_json(
        q40,
        {
            "ok": True,
            "matrix_total": 40,
            "matrix_evaluated": 40,
            "matrix_skipped": 0,
            "matrix_failed": 0,
        },
    )
    _write_json(
        temporal,
        {
            "ok": True,
            "counts": {
                "evaluated": 40,
                "skipped": 0,
                "failed": 0,
            },
        },
    )

    cp = subprocess.run(
        [
            sys.executable,
            "tools/gate_golden_pipeline_triplet.py",
            "--popup-report",
            str(popup),
            "--q40-report",
            str(q40),
            "--temporal-report",
            str(temporal),
            "--output",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert cp.returncode == 0, cp.stdout + cp.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["failure_reasons"] == []


def test_gate_golden_pipeline_triplet_fails_on_popup_regression(tmp_path: pathlib.Path) -> None:
    popup = tmp_path / "popup.json"
    q40 = tmp_path / "q40.json"
    temporal = tmp_path / "temporal.json"
    out = tmp_path / "out.json"

    _write_json(
        popup,
        {
            "ok": True,
            "sample_count": 10,
            "accepted_count": 0,
            "failed_count": 10,
        },
    )
    _write_json(
        q40,
        {
            "ok": True,
            "matrix_total": 40,
            "matrix_evaluated": 40,
            "matrix_skipped": 0,
            "matrix_failed": 0,
        },
    )
    _write_json(
        temporal,
        {
            "ok": True,
            "counts": {
                "evaluated": 40,
                "skipped": 0,
                "failed": 0,
            },
        },
    )

    cp = subprocess.run(
        [
            sys.executable,
            "tools/gate_golden_pipeline_triplet.py",
            "--popup-report",
            str(popup),
            "--q40-report",
            str(q40),
            "--temporal-report",
            str(temporal),
            "--output",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert cp.returncode != 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert "popup.accepted_count_mismatch" in payload["failure_reasons"]
    assert "popup.failed_count_nonzero" in payload["failure_reasons"]

