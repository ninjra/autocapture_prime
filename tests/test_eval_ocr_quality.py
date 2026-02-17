from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(args: list[str]) -> tuple[int, dict[str, object]]:
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, str(repo_root / "tools" / "eval_ocr_quality.py"), *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(str(proc.stdout or "{}"))
    return int(proc.returncode), payload


def test_eval_ocr_quality_passes_fixture(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixture = repo_root / "tests" / "fixtures" / "ocr_quality_cases.json"
    out = tmp_path / "ocr_quality.json"
    rc, payload = _run(
        [
            "--fixture",
            str(fixture),
            "--output",
            str(out),
            "--max-mean-cer",
            "0.20",
            "--max-mean-wer",
            "0.40",
        ]
    )
    assert rc == 0
    assert payload.get("ok") is True
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["summary"]["ok"] is True
    assert int(report["cases_total"]) == 3


def test_eval_ocr_quality_fails_with_strict_thresholds(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixture = repo_root / "tests" / "fixtures" / "ocr_quality_cases.json"
    out = tmp_path / "ocr_quality_fail.json"
    rc, payload = _run(
        [
            "--fixture",
            str(fixture),
            "--output",
            str(out),
            "--max-mean-cer",
            "0.0001",
            "--max-mean-wer",
            "0.0001",
        ]
    )
    assert rc == 1
    assert payload.get("ok") is False
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["summary"]["ok"] is False
