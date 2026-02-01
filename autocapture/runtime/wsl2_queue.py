"""WSL2 routing queue for GPU-heavy tasks."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.ids import prefixed_id


@dataclass(frozen=True)
class Wsl2DispatchResult:
    ok: bool
    allow_fallback: bool
    path: str | None
    error: str | None
    reason: str


class Wsl2Queue:
    def __init__(self, queue_dir: str | Path, *, protocol_version: int = 1) -> None:
        self.queue_dir = str(queue_dir)
        self._dir = Path(queue_dir)
        self._protocol_version = int(protocol_version or 1)
        self._lock = threading.Lock()
        self._seq = 0

    def available(self, distro: str | None = None) -> bool:
        if os.name != "nt":
            return False
        return bool(shutil.which("wsl") or shutil.which("wsl.exe"))

    def _protocol_ok(self) -> bool:
        proto_path = self._dir / "protocol.json"
        if not proto_path.exists():
            return True
        try:
            payload = json.loads(proto_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        version = payload.get("protocol_version")
        try:
            return int(version) == self._protocol_version
        except Exception:
            return False

    def dispatch(
        self,
        *,
        job_name: str,
        payload: dict[str, Any],
        run_id: str,
        distro: str | None = None,
        allow_fallback: bool = False,
    ) -> Wsl2DispatchResult:
        if not self.available(distro):
            return Wsl2DispatchResult(
                ok=False,
                allow_fallback=bool(allow_fallback),
                path=None,
                error="wsl2_unavailable",
                reason="missing_wsl",
            )
        if not self._protocol_ok():
            return Wsl2DispatchResult(
                ok=False,
                allow_fallback=bool(allow_fallback),
                path=None,
                error="protocol_mismatch",
                reason="protocol_mismatch",
            )
        with self._lock:
            self._seq += 1
            seq = self._seq
        self._dir.mkdir(parents=True, exist_ok=True)
        job_id = prefixed_id(run_id or "run", "wsl2", seq)
        record = {
            "schema_version": int(self._protocol_version),
            "job_id": job_id,
            "job_name": str(job_name),
            "run_id": str(run_id or ""),
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "distro": str(distro or ""),
            "payload": payload,
        }
        encoded = json.dumps(record, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        path = self._dir / f"{job_id}.json"
        tmp = self._dir / f".{job_id}.json.tmp"
        tmp.write_bytes(encoded)
        os.replace(tmp, path)
        return Wsl2DispatchResult(
            ok=True,
            allow_fallback=bool(allow_fallback),
            path=str(path),
            error=None,
            reason="queued",
        )
