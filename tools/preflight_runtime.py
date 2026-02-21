#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "config" / "autocapture_prime.yaml"


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def _run(cmd: list[str], timeout: float = 4.0) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
    )
    return proc.returncode, (proc.stdout or "").strip()


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _get_nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _check_gpu() -> CheckResult:
    if not shutil.which("nvidia-smi"):
        return CheckResult("gpu.nvidia_smi", False, "nvidia-smi not found in PATH")
    rc, out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], timeout=6.0)
    if rc != 0:
        return CheckResult("gpu.nvidia_smi", False, out or "nvidia-smi query failed")
    line = out.splitlines()[0] if out else ""
    return CheckResult("gpu.nvidia_smi", bool(line), line or "no GPUs reported")


def _check_vllm(base_url: str) -> CheckResult:
    curl = shutil.which("curl")
    if not curl:
        return CheckResult("vllm.health", False, "curl not found")
    models_url = base_url.rstrip("/") + "/v1/models"
    rc, out = _run([curl, "-sS", "--max-time", "3", models_url], timeout=5.0)
    if rc != 0:
        return CheckResult("vllm.health", False, out[:200] or f"cannot reach {models_url}")
    return CheckResult("vllm.health", True, "v1/models reachable")


def _check_dir(path: str, name: str, must_exist: bool = True) -> CheckResult:
    target = Path(path).expanduser()
    if must_exist and not target.exists():
        return CheckResult(name, False, f"missing: {target}")
    if target.exists() and not target.is_dir():
        return CheckResult(name, False, f"not a directory: {target}")
    if target.exists() and not os.access(target, os.R_OK):
        return CheckResult(name, False, f"not readable: {target}")
    if target.exists() and not os.access(target, os.W_OK):
        return CheckResult(name, False, f"not writable: {target}")
    return CheckResult(name, True, str(target))


def main() -> int:
    parser = argparse.ArgumentParser(description="Autocapture Prime runtime preflight checks.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to autocapture_prime.yaml")
    parser.add_argument("--skip-gpu", action="store_true", help="Skip GPU visibility check")
    parser.add_argument("--skip-vllm", action="store_true", help="Skip vLLM endpoint check")
    args = parser.parse_args()

    cfg_path = Path(args.config).expanduser()
    cfg = _load_config(cfg_path)
    spool_root = str(_get_nested(cfg, "spool", "root_dir_linux", default="/mnt/d/autocapture"))
    storage_root = str(_get_nested(cfg, "storage", "root_dir", default=str(REPO_ROOT / "artifacts" / "chronicle")))
    vllm_base = str(_get_nested(cfg, "vllm", "base_url", default="http://127.0.0.1:8000"))

    checks = [CheckResult("config.path", cfg_path.exists(), str(cfg_path))]
    if args.skip_gpu:
        checks.append(CheckResult("gpu.nvidia_smi", True, "skipped"))
    else:
        checks.append(_check_gpu())
    if args.skip_vllm:
        checks.append(CheckResult("vllm.health", True, "skipped"))
    else:
        checks.append(_check_vllm(vllm_base))
    checks.extend(
        [
            _check_dir(spool_root, "spool.root_dir_linux", must_exist=True),
            _check_dir(storage_root, "storage.root_dir", must_exist=False),
        ]
    )
    payload = {
        "ok": all(item.ok for item in checks),
        "checks": [asdict(item) for item in checks],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
