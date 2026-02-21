"""WSL2 routing queue for GPU-heavy tasks."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import hashlib
from datetime import datetime, timezone
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
        max_inflight: int = 1,
        token_ttl_s: float = 300.0,
    ) -> None:
        self.queue_dir = str(queue_dir)
        self._dir = Path(queue_dir)
        self._protocol_version = int(protocol_version or 1)
        self._max_pending = int(max(1, max_pending))
        self._max_inflight = int(max(1, max_inflight))
        self._token_ttl_s = float(max(1.0, token_ttl_s))
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

    @property
    def tokens_dir(self) -> Path:
        return self._dir / "tokens"

    @property
    def request_index_dir(self) -> Path:
        return self._dir / "request_index"

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
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        self.responses_dir.mkdir(parents=True, exist_ok=True)
        self.done_dir.mkdir(parents=True, exist_ok=True)
        self.tokens_dir.mkdir(parents=True, exist_ok=True)
        self.request_index_dir.mkdir(parents=True, exist_ok=True)

        payload_hash = hashlib.sha256(
            json.dumps(payload or {}, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        job_key = hashlib.sha256(
            f"{str(job_name)}|{str(run_id)}|{payload_hash}|{int(self._protocol_version)}".encode("utf-8")
        ).hexdigest()
        index_path = self.request_index_dir / f"{job_key}.json"

        with self._lock:
            self._reconcile_tokens_locked()
            if index_path.exists():
                try:
                    idx_payload = json.loads(index_path.read_text(encoding="utf-8"))
                except Exception:
                    idx_payload = {}
                existing_path = Path(str(idx_payload.get("request_path") or ""))
                if existing_path and existing_path.exists():
                    return Wsl2DispatchResult(
                        ok=True,
                        allow_fallback=bool(allow_fallback),
                        path=str(existing_path),
                        error=None,
                        reason="dedupe_pending",
                    )
                try:
                    index_path.unlink(missing_ok=True)
                except Exception:
                    pass

            inflight = len(list(self.tokens_dir.glob("*.token")))
            if inflight >= self._max_inflight:
                return Wsl2DispatchResult(
                    ok=False,
                    allow_fallback=bool(allow_fallback),
                    path=None,
                    error="wsl2_token_backpressure",
                    reason="token_backpressure",
                )
            self._seq += 1
            seq = self._seq

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
        token_id = f"{safe_id}.token"
        token_path = self.tokens_dir / token_id
        record = {
            "schema_version": int(self._protocol_version),
            "job_id": job_id,
            "job_key": job_key,
            "payload_hash": payload_hash,
            "token_id": token_id,
            "job_name": str(job_name),
            "run_id": str(run_id or ""),
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "distro": str(distro or ""),
            "payload": payload,
        }
        encoded = json.dumps(record, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        path = self.requests_dir / f"{safe_id}.json"
        tmp = self.requests_dir / f".{safe_id}.json.tmp"
        token_payload = {
            "schema_version": int(self._protocol_version),
            "job_id": job_id,
            "job_key": job_key,
            "token_id": token_id,
            "ts_utc": record["ts_utc"],
        }
        index_payload = {
            "schema_version": int(self._protocol_version),
            "job_id": job_id,
            "job_key": job_key,
            "token_id": token_id,
            "request_path": str(path),
            "ts_utc": record["ts_utc"],
        }
        token_tmp = self.tokens_dir / f".{token_id}.tmp"
        index_tmp = self.request_index_dir / f".{job_key}.tmp"
        try:
            token_tmp.write_text(
                json.dumps(token_payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(token_tmp, token_path)
            tmp.write_bytes(encoded)
            os.replace(tmp, path)
            index_tmp.write_text(
                json.dumps(index_payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(index_tmp, index_path)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                token_tmp.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                index_tmp.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                token_path.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                index_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise
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
            self._release_for_response(payload if isinstance(payload, dict) else {})
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

    def _reconcile_tokens_locked(self) -> None:
        now = time.time()
        for token in self.tokens_dir.glob("*.token"):
            try:
                payload = json.loads(token.read_text(encoding="utf-8"))
            except Exception:
                try:
                    token.unlink(missing_ok=True)
                except Exception:
                    pass
                continue
            ts_utc = str(payload.get("ts_utc") or "").strip()
            ts_epoch = 0.0
            if ts_utc:
                try:
                    norm = ts_utc[:-1] + "+00:00" if ts_utc.endswith("Z") else ts_utc
                    ts_epoch = datetime.fromisoformat(norm).astimezone(timezone.utc).timestamp()
                except Exception:
                    ts_epoch = 0.0
            if ts_epoch > 0.0 and (now - ts_epoch) > self._token_ttl_s:
                try:
                    token.unlink(missing_ok=True)
                except Exception:
                    pass
                job_key = str(payload.get("job_key") or "").strip()
                if job_key:
                    try:
                        (self.request_index_dir / f"{job_key}.json").unlink(missing_ok=True)
                    except Exception:
                        pass

    def _release_for_response(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        with self._lock:
            token_id = str(payload.get("token_id") or "").strip()
            job_key = str(payload.get("job_key") or "").strip()
            job_id = str(payload.get("job_id") or "").strip()
            if not token_id and job_id:
                token_id = f"{job_id.replace('/', '_')}.token"
            token_path = (self.tokens_dir / token_id) if token_id else None
            if (not job_key) and token_path is not None and token_path.exists():
                try:
                    token_payload = json.loads(token_path.read_text(encoding="utf-8"))
                    job_key = str(token_payload.get("job_key") or "").strip()
                except Exception:
                    pass
            if token_id:
                try:
                    (self.tokens_dir / token_id).unlink(missing_ok=True)
                except Exception:
                    pass
            if job_key:
                try:
                    (self.request_index_dir / f"{job_key}.json").unlink(missing_ok=True)
                except Exception:
                    pass
