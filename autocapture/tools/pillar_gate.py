"""Run pillar gate suite and emit deterministic reports."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from autocapture.pillars.reporting import CheckResult, PillarResult, write_reports


def _iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_id(now: str, pid: int) -> str:
    digest = hashlib.sha256(f"{now}{pid}".encode("utf-8")).hexdigest()[:8]
    return f"{now}-{digest}"


def _run_check(
    name: str,
    cmd: list[str],
    *,
    env: dict[str, str],
    artifacts: Iterable[str] = (),
    timeout_s: int | None = None,
) -> CheckResult:
    started = time.perf_counter()
    status = "pass"
    detail = None
    ok = False
    try:
        result = subprocess.run(cmd, env=env, timeout=timeout_s)
        ok = result.returncode == 0
        status = "pass" if ok else "fail"
        if not ok:
            detail = f"exit={result.returncode}"
    except subprocess.TimeoutExpired:
        status = "error"
        detail = "timeout"
        ok = False
    except Exception as exc:
        status = "error"
        detail = str(exc)
        ok = False
    duration_ms = int(max(0.0, (time.perf_counter() - started) * 1000.0))
    return CheckResult(
        name=name,
        ok=ok,
        status=status,
        duration_ms=duration_ms,
        detail=detail,
        artifacts=list(artifacts),
    )


def _pillar(
    pillar: str,
    checks: list[CheckResult],
    *,
    started_ts: str,
) -> PillarResult:
    finished_ts = _iso_utc()
    duration_ms = sum(check.duration_ms for check in checks)
    ok = all(check.ok for check in checks)
    return PillarResult(
        pillar=pillar,
        ok=ok,
        duration_ms=duration_ms,
        started_ts_utc=started_ts,
        finished_ts_utc=finished_ts,
        checks=checks,
    )


def run_all_gates(
    *,
    artifacts_dir: str | Path = "artifacts",
    config_dir: str | None = None,
    deterministic_fixtures: bool = False,
) -> int:
    now = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    run_id = _run_id(now, os.getpid())
    root = Path(artifacts_dir)
    perf_dir = root / "perf"
    retrieval_dir = root / "retrieval"
    security_dir = root / "security"
    provenance_dir = root / "provenance"
    for d in (perf_dir, retrieval_dir, security_dir, provenance_dir):
        d.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(Path(__file__).resolve().parents[2]))
    if deterministic_fixtures:
        env["AUTOCAPTURE_DETERMINISTIC_FIXTURES"] = "1"
    if config_dir:
        env["AUTOCAPTURE_CONFIG_DIR"] = str(config_dir)

    py = sys.executable
    pillar_results: list[PillarResult] = []

    started = _iso_utc()
    p1_checks = [
        _run_check(
            "gate_perf",
            [py, "tools/gate_perf.py"],
            env=env,
            artifacts=[str(perf_dir)],
        )
    ]
    pillar_results.append(_pillar("P1", p1_checks, started_ts=started))

    started = _iso_utc()
    p2_checks = [
        _run_check(
            "retrieval_golden",
            [py, "-m", "unittest", "tests/test_retrieval_golden.py", "-q"],
            env=env,
            artifacts=[str(retrieval_dir)],
        ),
        _run_check(
            "state_layer_golden",
            [py, "tools/state_layer_eval.py"],
            env=env,
            artifacts=[str(retrieval_dir)],
        ),
        _run_check(
            "sanitizer_ner_cases",
            [py, "-m", "unittest", "tests/test_sanitizer_ner_cases.py", "-q"],
            env=env,
            artifacts=[str(retrieval_dir)],
        ),
    ]
    pillar_results.append(_pillar("P2", p2_checks, started_ts=started))

    started = _iso_utc()
    p3_checks = [
        _run_check(
            "gate_security",
            [py, "tools/gate_security.py"],
            env=env,
            artifacts=[str(security_dir)],
        ),
    ]
    pillar_results.append(_pillar("P3", p3_checks, started_ts=started))

    started = _iso_utc()
    p4_checks = [
        _run_check(
            "provenance_chain",
            [py, "-m", "unittest", "tests/test_provenance_chain.py", "-q"],
            env=env,
            artifacts=[str(provenance_dir)],
        ),
        _run_check(
            "acceptance_coverage",
            [py, "tools/gate_acceptance_coverage.py"],
            env=env,
            artifacts=[str(provenance_dir)],
        ),
        _run_check(
            "doctor_anchor_boundary",
            [py, "-m", "unittest", "tests/test_doctor_anchor_boundary.py", "-q"],
            env=env,
            artifacts=[str(provenance_dir)],
        ),
        _run_check(
            "verify_archive_cli",
            [py, "-m", "unittest", "tests/test_verify_archive_cli.py", "-q"],
            env=env,
            artifacts=[str(provenance_dir)],
        ),
    ]
    pillar_results.append(_pillar("P4", p4_checks, started_ts=started))

    write_reports(run_id, pillar_results, artifacts_dir=root / "pillar_reports")

    any_error = any(any(check.status == "error" for check in pillar.checks) for pillar in pillar_results)
    if any_error:
        return 2
    if not all(pillar.ok for pillar in pillar_results):
        return 1
    return 0
