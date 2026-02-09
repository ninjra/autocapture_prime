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
    def __init__(
        self,
        queue_dir: str | Path,
        *,
        protocol_version: int = 1,
        max_pending: int = 256,
    ) -> None:
        self.queue_dir = str(queue_dir)
        self._dir = Path(queue_dir)
        self._protocol_version = int(protocol_version or 1)
        self._max_pending = int(max(1, max_pending))
        self._lock = threading.Lock()
        self._seq = 0

    @property
    def requests_dir(self) -> Path:
        return self._dir / "requests"

    @property
    def responses_dir(self) -> Path:
        return self._dir / "responses"

    @property
    def done_dir(self) -> Path:
        return self._dir / "done"

    def available(self, distro: str | None = None) -> bool:
        # Tests run in non-Windows environments (CI/WSL) but still need to
        # validate round-trip mechanics deterministically.
        force = os.getenv("AUTOCAPTURE_WSL2_QUEUE_FORCE", "").strip().lower() in {"1", "true", "yes"}
        if force:
            return True
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
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        self.responses_dir.mkdir(parents=True, exist_ok=True)
        self.done_dir.mkdir(parents=True, exist_ok=True)

        # Backpressure: bound the number of pending request files so the native
        # side doesn't queue unbounded work.
        try:
            pending = len(list(self.requests_dir.glob("*.json")))
        except Exception:
            pending = 0
        if pending >= self._max_pending:
            return Wsl2DispatchResult(
                ok=False,
                allow_fallback=bool(allow_fallback),
                path=None,
                error="wsl2_backpressure",
                reason="backpressure",
            )

        job_id = prefixed_id(run_id or "run", "wsl2", seq)
        safe_id = job_id.replace("/", "_")
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
        path = self.requests_dir / f"{safe_id}.json"
        tmp = self.requests_dir / f".{safe_id}.json.tmp"
        tmp.write_bytes(encoded)
        os.replace(tmp, path)
        return Wsl2DispatchResult(
            ok=True,
            allow_fallback=bool(allow_fallback),
            path=str(path),
            error=None,
            reason="queued",
        )

    def poll_responses(self, *, max_items: int = 50) -> list[dict[str, Any]]:
        """Ingest worker responses (best-effort, deterministic ordering)."""

        self.responses_dir.mkdir(parents=True, exist_ok=True)
        self.done_dir.mkdir(parents=True, exist_ok=True)
        paths = sorted(self.responses_dir.glob("*.json"))
        out: list[dict[str, Any]] = []
        for path in paths[: max(0, int(max_items))]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                payload = {"error": "invalid_json", "path": str(path)}
            out.append(payload if isinstance(payload, dict) else {"payload": payload})
            # Archive response instead of deleting (no local deletion).
            try:
                dest = self.done_dir / path.name
                os.replace(path, dest)
            except Exception:
                pass
        return out

    def await_response(self, job_id: str, *, timeout_s: float = 10.0, poll_s: float = 0.05) -> dict[str, Any] | None:
        """Wait for a response for the given job_id."""

        deadline = time.time() + max(0.0, float(timeout_s))
        target = str(job_id or "").replace("/", "_")
        while time.time() <= deadline:
            for payload in self.poll_responses(max_items=100):
                if str(payload.get("job_id") or "").replace("/", "_") == target:
                    return payload
            time.sleep(max(0.01, float(poll_s)))
        return None
