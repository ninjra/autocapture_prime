"""Run pillar gate suite and emit reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from autocapture.tools import (
    privacy_scanner,
    provenance_gate,
    coverage_gate,
    latency_gate,
    retrieval_sensitivity,
    conflict_gate,
    integrity_gate,
)


REPORT_DIR = Path("artifacts/pillar_reports")


def _write_report(name: str, report: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"{name}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def _run_gate(name: str, fn: Callable[[], dict]) -> bool:
    report = fn()
    _write_report(name, report)
    return bool(report.get("ok", False))


def run_all_gates() -> bool:
    results = [
        _run_gate("privacy_scanner", privacy_scanner.run),
        _run_gate("provenance_gate", provenance_gate.run),
        _run_gate("coverage_gate", coverage_gate.run),
        _run_gate("latency_gate", latency_gate.run),
        _run_gate("retrieval_sensitivity", retrieval_sensitivity.run),
        _run_gate("conflict_gate", conflict_gate.run),
        _run_gate("integrity_gate", integrity_gate.run),
    ]
    return all(results)
