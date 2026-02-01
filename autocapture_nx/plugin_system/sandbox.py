"""Plugin sandbox helpers and IPC validation."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.audit import append_audit_event
from autocapture_nx.windows.win_sandbox import assign_job_object


@dataclass(frozen=True)
class SandboxReport:
    pid: int | None
    restricted_token: bool
    job_object: bool
    ipc_schema_enforced: bool
    ipc_max_bytes: int
    notes: tuple[str, ...]


def _default_report(
    *,
    pid: int | None,
    restricted_token: bool,
    job_object: bool,
    ipc_schema_enforced: bool,
    ipc_max_bytes: int,
    notes: list[str],
) -> SandboxReport:
    return SandboxReport(
        pid=pid,
        restricted_token=restricted_token,
        job_object=job_object,
        ipc_schema_enforced=ipc_schema_enforced,
        ipc_max_bytes=ipc_max_bytes,
        notes=tuple(notes),
    )


def spawn_plugin_process(
    args: list[str],
    *,
    env: dict[str, str] | None,
    limits: dict[str, Any] | None,
    ipc_max_bytes: int,
    use_restricted_token: bool = True,
) -> tuple[subprocess.Popen[str], SandboxReport]:
    """Spawn plugin host with best-effort sandboxing."""
    notes: list[str] = []
    restricted = False
    if use_restricted_token and os.name == "nt":
        # Best-effort: restricted token support requires pywin32 or explicit API use.
        # Fall back when unavailable.
        try:
            import win32security  # type: ignore  # noqa: F401

            notes.append("restricted_token_available")
        except Exception:
            notes.append("restricted_token_unavailable")
    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    job_object = False
    try:
        assign_job_object(proc.pid, limits=limits)
        job_object = True
    except Exception:
        notes.append("job_object_failed")
    report = _default_report(
        pid=proc.pid,
        restricted_token=restricted,
        job_object=job_object,
        ipc_schema_enforced=True,
        ipc_max_bytes=ipc_max_bytes,
        notes=notes,
    )
    append_audit_event(
        action="plugin.sandbox.spawn",
        actor="plugin_system",
        outcome="ok",
        details={
            "pid": proc.pid,
            "restricted_token": restricted,
            "job_object": job_object,
            "ipc_max_bytes": ipc_max_bytes,
            "notes": list(report.notes),
        },
    )
    return proc, report


def validate_ipc_message(message: dict[str, Any], *, role: str) -> tuple[bool, str]:
    """Validate IPC message shape based on role."""
    if not isinstance(message, dict):
        return False, "message_not_dict"
    if message.get("response_to") == "cap_call":
        return True, "ok"
    method = message.get("method")
    if role == "plugin":
        if method not in {"capabilities", "call"}:
            return False, "unknown_method"
        if method == "call":
            if "capability" not in message or "function" not in message:
                return False, "missing_fields"
    if role == "host":
        if method == "cap_call":
            if "capability" not in message or "function" not in message:
                return False, "missing_fields"
    return True, "ok"


def write_sandbox_report(report: SandboxReport, *, path: str | Path = "artifacts/security/plugin_sandbox_report.json") -> None:
    payload = {
        "pid": report.pid,
        "restricted_token": report.restricted_token,
        "job_object": report.job_object,
        "ipc_schema_enforced": report.ipc_schema_enforced,
        "ipc_max_bytes": report.ipc_max_bytes,
        "notes": list(report.notes),
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
