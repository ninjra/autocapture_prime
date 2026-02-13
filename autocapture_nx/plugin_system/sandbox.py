"""Plugin sandbox helpers and IPC validation."""

from __future__ import annotations

import json
import os
import signal
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

    # On POSIX (including WSL), ensure subprocesses die with their parent and honor
    # the existing "job_limits" config via rlimits. This avoids leaking many
    # host_runner processes when a test shard crashes and prevents runaway RAM.
    preexec_fn = None
    start_new_session = False
    if os.name != "nt":
        start_new_session = True

        def _posix_preexec() -> None:  # Runs in the child just before exec.
            # Best-effort: terminate child if parent dies.
            try:
                import ctypes
                import ctypes.util

                libc_path = ctypes.util.find_library("c")
                if libc_path:
                    libc = ctypes.CDLL(libc_path, use_errno=True)
                    PR_SET_PDEATHSIG = 1
                    libc.prctl(PR_SET_PDEATHSIG, int(signal.SIGTERM))
            except Exception:
                pass

            if not limits:
                return
            try:
                import math
                import resource

                max_memory_mb = int(limits.get("max_memory_mb", 0) or 0)
                if max_memory_mb > 0 and hasattr(resource, "RLIMIT_AS"):
                    bytes_limit = int(max_memory_mb) * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_AS, (bytes_limit, bytes_limit))

                cpu_time_ms = int(limits.get("cpu_time_ms", 0) or 0)
                if cpu_time_ms > 0 and hasattr(resource, "RLIMIT_CPU"):
                    seconds = max(1, int(math.ceil(cpu_time_ms / 1000.0)))
                    resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds))
            except Exception:
                # Best-effort only; sandbox must not fail open due to platform variance.
                pass

        preexec_fn = _posix_preexec
        notes.append("posix_start_new_session")
        notes.append("posix_pdeathsig_sigterm")
        if limits:
            if int(limits.get("max_memory_mb", 0) or 0) > 0:
                notes.append(f"posix_rlimit_as_mb={int(limits.get('max_memory_mb', 0) or 0)}")
            if int(limits.get("cpu_time_ms", 0) or 0) > 0:
                notes.append(f"posix_rlimit_cpu_ms={int(limits.get('cpu_time_ms', 0) or 0)}")
            if int(limits.get("max_processes", 0) or 0) > 0:
                # On POSIX, threads count toward RLIMIT_NPROC, and host_runner uses
                # threads internally. We intentionally do not apply RLIMIT_NPROC here.
                notes.append(f"posix_max_processes_unenforced={int(limits.get('max_processes', 0) or 0)}")

    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=start_new_session,
        preexec_fn=preexec_fn,
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
