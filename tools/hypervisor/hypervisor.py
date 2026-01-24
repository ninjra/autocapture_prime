"""Hypervisor orchestration for variant workflows."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class VariantScorecard:
    variant_id: str
    status: str
    p1_latency_ms: float | None
    p2_tests_passed: bool
    p3_security_passed: bool
    p4_artifacts_complete: bool
    notes: str


def _run_cmd(cmd: list[str], cwd: str | None = None) -> tuple[int, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


def _create_variant(variant_id: str, axis: str, dry_run: bool) -> Path | None:
    if dry_run:
        return None
    variants_dir = Path("tools") / "hypervisor" / "variants"
    os.makedirs(variants_dir, exist_ok=True)
    variant_path = variants_dir / variant_id
    branch = f"hv/{axis}/{variant_id}"
    code, output = _run_cmd(["git", "worktree", "add", "-b", branch, str(variant_path), "HEAD"])
    if code != 0:
        raise RuntimeError(f"Failed to create worktree: {output}")
    return variant_path


def _measure_startup_ms(cwd: str | None) -> float | None:
    code, output = _run_cmd(
        [
            sys.executable,
            "-c",
            "import time; from autocapture_nx.kernel.loader import Kernel, default_config_paths; "
            "t0=time.perf_counter(); Kernel(default_config_paths(), safe_mode=False).boot(); "
            "print(int((time.perf_counter()-t0)*1000))",
        ],
        cwd=cwd,
    )
    if code != 0:
        return None
    try:
        return float(output.strip().splitlines()[-1])
    except Exception:
        return None


def _run_doctor(cwd: str | None) -> bool:
    code, _output = _run_cmd([sys.executable, "-m", "autocapture_nx", "doctor"], cwd=cwd)
    return code == 0


def _score_variant(dry_run: bool, cwd: str | None = None) -> VariantScorecard:
    if dry_run:
        return VariantScorecard(
            variant_id="",
            status="dry_run",
            p1_latency_ms=None,
            p2_tests_passed=False,
            p3_security_passed=False,
            p4_artifacts_complete=True,
            notes="dry run: no checks executed",
        )
    p1_latency = _measure_startup_ms(cwd)
    p3_ok = _run_doctor(cwd)
    code, output = _run_cmd(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=cwd
    )
    return VariantScorecard(
        variant_id="",
        status="passed" if code == 0 else "failed",
        p1_latency_ms=p1_latency,
        p2_tests_passed=(code == 0),
        p3_security_passed=p3_ok,
        p4_artifacts_complete=True,
        notes=output,
    )


def run_diffusion(axis: str, k_variants: int, dry_run: bool) -> dict[str, Any]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path("tools") / "hypervisor" / "runs" / run_id
    os.makedirs(run_dir, exist_ok=True)

    meta = {
        "run_id": run_id,
        "axis": axis,
        "k_variants": k_variants,
        "dry_run": dry_run,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "noise_schedule": [
            {"step": 1, "scope": "architecture/files/ports"},
            {"step": 2, "scope": "module_wiring_and_manifests"},
            {"step": 3, "scope": "function_bodies"},
            {"step": 4, "scope": "repairs_and_hardening"},
        ],
    }
    with open(run_dir / "run.json", "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2, sort_keys=True)

    variants = []
    scorecards = []
    for idx in range(k_variants):
        variant_id = f"v{idx + 1}"
        variants.append(variant_id)
        variant_path = _create_variant(variant_id, axis, dry_run)
        scorecard = _score_variant(dry_run, cwd=str(variant_path) if variant_path else None)
        scorecard.variant_id = variant_id
        score_path = run_dir / f"scorecard_{variant_id}.json"
        with open(score_path, "w", encoding="utf-8") as handle:
            json.dump(scorecard.__dict__, handle, indent=2, sort_keys=True)
        scorecards.append(scorecard.__dict__)

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "variants": variants,
        "scorecards": scorecards,
    }
