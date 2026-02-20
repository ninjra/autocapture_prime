from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "autocapture_prime_4pillars_optimization.md"
CLI_PATH = REPO_ROOT / "autocapture_nx" / "cli.py"

BACKLOG_IDS = [
    "QRY-001",
    "QRY-002",
    "EVAL-001",
    "ATTR-001",
    "WSL-001",
    "SEC-001",
    "SEC-002",
    "CAP-001",
    "AUD-001",
    "INP-001",
]


def _rg_count(term: str, scope: list[str] | None = None) -> int:
    paths = scope or ["docs", "tools", "autocapture", "autocapture_nx", "plugins", "tests", "config", "contracts"]
    cmd = ["rg", "-n", "--fixed-strings", term, *paths]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        return 0
    out = proc.stdout.strip()
    if not out:
        return 0
    return len(out.splitlines())


def _rg_lines(term: str, scope: list[str] | None = None, limit: int = 20) -> list[str]:
    paths = scope or ["docs", "tools", "autocapture", "autocapture_nx", "plugins", "tests", "config", "contracts"]
    cmd = ["rg", "-n", "--fixed-strings", term, *paths]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        return []
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return lines[:limit]


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    evidence: list[str]


def _check_backlog_ids() -> CheckResult:
    missing: list[str] = []
    evidence: list[str] = []
    for item_id in BACKLOG_IDS:
        lines = _rg_lines(item_id)
        if len(lines) <= 1:
            missing.append(item_id)
        evidence.extend(lines[:2])
    ok = len(missing) == 0
    detail = "all backlog ids referenced beyond source doc" if ok else f"ids_only_in_source={missing}"
    return CheckResult("backlog_id_tracking", ok, detail, evidence[:20])


def _check_cli_commands() -> CheckResult:
    text = CLI_PATH.read_text(encoding="utf-8")
    has_setup = 'add_parser("setup")' in text
    has_gate = 'add_parser("gate")' in text
    ok = has_setup and has_gate
    detail = f"has_setup={has_setup} has_gate={has_gate}"
    evidence = _rg_lines("add_parser(", scope=["autocapture_nx/cli.py"], limit=10)
    return CheckResult("doc_cli_commands_exist", ok, detail, evidence)


def _check_profile_strings() -> CheckResult:
    has_personal_windows_4090 = _rg_count("personal_windows_4090", ["config", "tools", "autocapture_nx", "autocapture", "docs"]) > 1
    has_personal_4090 = _rg_count("personal_4090", ["config", "tools", "autocapture_nx", "autocapture", "docs"]) > 1
    ok = has_personal_windows_4090 or has_personal_4090
    detail = f"personal_windows_4090={has_personal_windows_4090} personal_4090={has_personal_4090}"
    evidence = _rg_lines("personal_4090", ["config", "tools", "autocapture_nx", "autocapture", "docs"], limit=10)
    evidence.extend(_rg_lines("personal_windows_4090", ["config", "tools", "autocapture_nx", "autocapture", "docs"], limit=10))
    return CheckResult("profile_defined", ok, detail, evidence[:20])


def _check_strict_rerun_gate() -> CheckResult:
    has_runner = _rg_count("run_golden_qh_cycle.sh", ["tools", "docs", "tests"]) > 0
    has_drift = _rg_count("confidence-drift-tolerance-pct", ["tools", "docs", "tests"]) > 0
    lines = _rg_lines("run_golden_qh_cycle.sh", ["tools", "docs", "tests"], limit=10)
    lines.extend(_rg_lines("confidence-drift-tolerance-pct", ["tools", "docs", "tests"], limit=10))
    ok = bool(has_runner and has_drift)
    detail = "drift/rerun gate evidence found" if ok else "no deterministic drift/rerun evidence found"
    return CheckResult("strict_rerun_drift_gate", ok, detail, lines[:20])


def _check_observation_graph_required() -> CheckResult:
    profile_lines = _rg_lines(
        "builtin.observation.graph",
        ["config/profiles", "tools/process_single_screenshot.py", "autocapture_nx/cli.py", "docs/reports"],
        limit=20,
    )
    required_lines = _rg_lines(
        "required_plugin_gate_failed",
        ["tools", "autocapture_nx", "tests"],
        limit=20,
    )
    fail_close_lines = [line for line in profile_lines + required_lines if "required" in line.lower() or "fail" in line.lower()]
    ok = len(fail_close_lines) > 0
    detail = "explicit required/fail-close evidence found" if ok else "no explicit fail-close requirement evidence"
    return CheckResult("observation_graph_fail_closed", ok, detail, (profile_lines + required_lines)[:20])


def main() -> None:
    if not DOC_PATH.exists():
        payload: dict[str, Any] = {"ok": False, "error": "missing_source_doc", "path": str(DOC_PATH)}
        print(json.dumps(payload, indent=2))
        raise SystemExit(2)

    stat = DOC_PATH.stat()
    checks = [
        _check_backlog_ids(),
        _check_cli_commands(),
        _check_profile_strings(),
        _check_strict_rerun_gate(),
        _check_observation_graph_required(),
    ]
    ok = all(item.ok for item in checks)
    payload = {
        "ok": ok,
        "source_doc": str(DOC_PATH.relative_to(REPO_ROOT)),
        "source_doc_mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "checks": [asdict(item) for item in checks],
    }
    print(json.dumps(payload, indent=2))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
