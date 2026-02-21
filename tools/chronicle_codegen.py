#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTO = REPO_ROOT / "contracts" / "chronicle" / "v0" / "chronicle.proto"
STAMP = REPO_ROOT / "contracts" / "chronicle" / "v0" / "generated" / "chronicle_codegen_stamp.json"
OUT_DIR = REPO_ROOT / "autocapture_prime" / "chronicle" / "v0"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_stamp(payload: dict[str, object]) -> None:
    STAMP.parent.mkdir(parents=True, exist_ok=True)
    STAMP.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _find_codegen_cmd() -> list[str] | None:
    protoc = shutil.which("protoc")
    if protoc:
        return [protoc]
    py = sys.executable
    try:
        import grpc_tools  # noqa: F401
    except Exception:
        return None
    return [py, "-m", "grpc_tools.protoc"]


def _ensure_pkg(path: Path) -> None:
    cur = path
    while cur != REPO_ROOT:
        init_py = cur / "__init__.py"
        if not init_py.exists():
            init_py.write_text("", encoding="utf-8")
        cur = cur.parent


def _generate() -> tuple[bool, str]:
    cmd_prefix = _find_codegen_cmd()
    if not cmd_prefix:
        return False, "protoc/grpc_tools.protoc not found"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_pkg(OUT_DIR)
    if len(cmd_prefix) == 1:
        cmd = cmd_prefix + [
            f"-I{PROTO.parent}",
            f"--python_out={OUT_DIR}",
            str(PROTO),
        ]
    else:
        cmd = cmd_prefix + [
            f"-I{PROTO.parent}",
            f"--python_out={OUT_DIR}",
            str(PROTO),
        ]
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "codegen failed").strip()
        return False, msg
    return True, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate chronicle protobuf bindings and stamp.")
    parser.add_argument("--check", action="store_true", help="Fail when stamp is missing/outdated.")
    args = parser.parse_args()

    if not PROTO.exists():
        print("FAIL: chronicle proto missing")
        return 2
    proto_hash = _sha256(PROTO)
    current = {}
    if STAMP.exists():
        try:
            current = json.loads(STAMP.read_text(encoding="utf-8"))
        except Exception:
            current = {}

    if args.check:
        if not current:
            print("FAIL: codegen stamp missing")
            return 1
        if str(current.get("proto_sha256")) != proto_hash:
            print("FAIL: codegen stamp stale")
            return 1
        print("OK: chronicle codegen stamp fresh")
        return 0

    ok, detail = _generate()
    payload = {
        "proto_path": str(PROTO.relative_to(REPO_ROOT)),
        "proto_sha256": proto_hash,
        "generated_out_dir": str(OUT_DIR.relative_to(REPO_ROOT)),
        "generator": "protoc/grpc_tools.protoc",
        "generated": bool(ok),
        "detail": detail,
        "pid": os.getpid(),
    }
    _write_stamp(payload)
    if ok:
        print("OK: chronicle codegen generated")
        return 0
    print(f"WARN: chronicle codegen skipped: {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
