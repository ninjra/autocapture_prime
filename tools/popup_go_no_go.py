#!/usr/bin/env python3
"""Strict popup go/no-go probe.

Checks popup/bridge health and runs strict popup regression in one step.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _http_json(*, url: str, timeout_s: float) -> dict[str, Any]:
    req = Request(str(url), method="GET")
    try:
        with urlopen(req, timeout=float(timeout_s)) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw.strip() else {}
            return {"ok": True, "status": int(getattr(resp, "status", 200) or 200), "json": parsed}
    except HTTPError as exc:
        return {"ok": False, "status": int(exc.code), "error": f"http_error:{exc.code}", "json": {}}
    except URLError as exc:
        return {"ok": False, "status": 0, "error": f"url_error:{exc.reason}", "json": {}}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": f"request_failed:{type(exc).__name__}:{exc}", "json": {}}


def _check_health(name: str, url: str, timeout_s: float) -> dict[str, Any]:
    out = _http_json(url=url, timeout_s=timeout_s)
    payload = out.get("json", {}) if isinstance(out.get("json", {}), dict) else {}
    service_ok = bool(out.get("ok", False)) and int(out.get("status", 0) or 0) == 200 and bool(payload.get("ok", False))
    return {
        "name": name,
        "ok": bool(service_ok),
        "url": str(url),
        "http_ok": bool(out.get("ok", False)),
        "http_status": int(out.get("status", 0) or 0),
        "http_error": str(out.get("error") or ""),
        "payload": payload,
    }


def _run_regression(*, root: Path, python_bin: str, timeout_s: float, out: Path, misses: Path) -> dict[str, Any]:
    cmd = [
        python_bin,
        str(root / "tools" / "run_popup_blind_acceptance.py"),
        "--cases",
        str(root / "docs" / "query_eval_cases_popup_regression.json"),
        "--all-cases",
        "--timeout-s",
        str(timeout_s),
        "--out",
        str(out),
        "--misses-out",
        str(misses),
        "--strict",
    ]
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
    return {
        "name": "popup_regression_strict",
        "ok": int(proc.returncode) == 0,
        "returncode": int(proc.returncode),
        "cmd": cmd,
        "stdout_tail": str(proc.stdout or "")[-2000:],
        "stderr_tail": str(proc.stderr or "")[-2000:],
        "report": str(out),
        "misses": str(misses),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _compact_regression_summary(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if not payload:
        return {
            "sample_count": 0,
            "accepted_count": 0,
            "failed_count": 0,
            "latency_p50_ms": 0.0,
            "latency_p95_ms": 0.0,
            "top_failure_class": "",
            "top_failure_key": "",
        }
    return {
        "sample_count": int(payload.get("sample_count", 0) or 0),
        "accepted_count": int(payload.get("accepted_count", 0) or 0),
        "failed_count": int(payload.get("failed_count", 0) or 0),
        "latency_p50_ms": float(payload.get("latency_p50_ms", 0.0) or 0.0),
        "latency_p95_ms": float(payload.get("latency_p95_ms", 0.0) or 0.0),
        "top_failure_class": str(payload.get("top_failure_class") or ""),
        "top_failure_key": str(payload.get("top_failure_key") or ""),
    }


def _mtime_ns(path: Path) -> int | None:
    try:
        return int(path.stat().st_mtime_ns)
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strict popup go/no-go probe.")
    parser.add_argument("--base-url", default=os.environ.get("AUTOCAPTURE_WEB_BASE_URL", "http://127.0.0.1:8787"))
    parser.add_argument("--bridge-url", default=os.environ.get("AUTOCAPTURE_QUERY_BRIDGE_BASE_URL", "http://127.0.0.1:8788"))
    parser.add_argument("--timeout-s", type=float, default=float(os.environ.get("AUTOCAPTURE_POPUP_ACCEPT_TIMEOUT_S", "10")))
    parser.add_argument("--out", default="artifacts/query_acceptance/popup_go_no_go_latest.json")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when any check fails.")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    py = str(root / ".venv" / "bin" / "python3")
    if not Path(py).exists():
        py = os.environ.get("PYTHON", "python3")

    report = root / "artifacts" / "query_acceptance" / "popup_regression_latest.json"
    misses = root / "artifacts" / "query_acceptance" / "popup_regression_misses_latest.json"

    checks = [
        _check_health("popup_health", f"{str(args.base_url).rstrip('/')}/health", float(args.timeout_s)),
        _check_health("query_bridge_health", f"{str(args.bridge_url).rstrip('/')}/health", float(args.timeout_s)),
    ]
    compact_summary = {
        "sample_count": 0,
        "accepted_count": 0,
        "failed_count": 0,
        "latency_p50_ms": 0.0,
        "latency_p95_ms": 0.0,
        "top_failure_class": "",
        "top_failure_key": "",
    }
    if all(bool(check.get("ok", False)) for check in checks):
        before_ns = _mtime_ns(report)
        regression_check = _run_regression(
            root=root,
            python_bin=py,
            timeout_s=float(args.timeout_s),
            out=report,
            misses=misses,
        )
        after_ns = _mtime_ns(report)
        if after_ns is not None and (before_ns is None or after_ns > before_ns):
            compact_summary = _compact_regression_summary(report)
        regression_check["compact"] = dict(compact_summary)
        checks.append(
            regression_check
        )
    else:
        checks.append(
            {
                "name": "popup_regression_strict",
                "ok": False,
                "returncode": -1,
                "cmd": [],
                "stdout_tail": "",
                "stderr_tail": "",
                "report": str(report),
                "misses": str(misses),
                "error": "prereq_health_failed",
                "compact": dict(compact_summary),
            }
        )

    ok = all(bool(check.get("ok", False)) for check in checks)
    payload = {
        "schema_version": 1,
        "record_type": "derived.eval.popup_go_no_go",
        "ts_utc": _utc_iso(),
        "ok": bool(ok),
        "base_url": str(args.base_url),
        "bridge_url": str(args.bridge_url),
        "compact_summary": dict(compact_summary),
        "checks": checks,
    }
    out_path = root / str(args.out)
    _write_json(out_path, payload)
    print(
        json.dumps(
            {
                "ok": bool(ok),
                "output": str(out_path),
                "failed_count": int(compact_summary.get("failed_count", 0) or 0),
                "top_failure_class": str(compact_summary.get("top_failure_class") or ""),
                "top_failure_key": str(compact_summary.get("top_failure_key") or ""),
                "latency_p50_ms": float(compact_summary.get("latency_p50_ms", 0.0) or 0.0),
                "latency_p95_ms": float(compact_summary.get("latency_p95_ms", 0.0) or 0.0),
            },
            sort_keys=True,
        )
    )
    if bool(args.strict) and not bool(ok):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
