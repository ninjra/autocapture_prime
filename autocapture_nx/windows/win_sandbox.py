"""Windows process sandbox helpers (best-effort)."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
JOB_OBJECT_LIMIT_JOB_TIME = 0x00000004


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_job_handle = None


def _apply_limits(info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION, limits: dict | None) -> None:
    if not limits:
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        return
    limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    max_processes = int(limits.get("max_processes", 1) or 0)
    if max_processes > 0:
        limit_flags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        info.BasicLimitInformation.ActiveProcessLimit = max_processes
    max_memory_mb = int(limits.get("max_memory_mb", 0) or 0)
    if max_memory_mb > 0:
        bytes_limit = int(max_memory_mb) * 1024 * 1024
        limit_flags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_JOB_MEMORY
        info.ProcessMemoryLimit = bytes_limit
        info.JobMemoryLimit = bytes_limit
    cpu_time_ms = int(limits.get("cpu_time_ms", 0) or 0)
    if cpu_time_ms > 0:
        limit_flags |= JOB_OBJECT_LIMIT_PROCESS_TIME | JOB_OBJECT_LIMIT_JOB_TIME
        units = int(cpu_time_ms) * 10_000  # 100ns units
        try:
            info.BasicLimitInformation.PerProcessUserTimeLimit.QuadPart = units
            info.BasicLimitInformation.PerJobUserTimeLimit.QuadPart = units
        except Exception:
            info.BasicLimitInformation.PerProcessUserTimeLimit = wintypes.LARGE_INTEGER(units)
            info.BasicLimitInformation.PerJobUserTimeLimit = wintypes.LARGE_INTEGER(units)
    info.BasicLimitInformation.LimitFlags = limit_flags


def build_job_limits(limits: dict | None) -> JOBOBJECT_EXTENDED_LIMIT_INFORMATION:
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    _apply_limits(info, limits)
    return info


def assign_job_object(pid: int, *, limits: dict | None = None) -> None:
    if os.name != "nt":
        return
    global _job_handle
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    if _job_handle is None:
        _job_handle = kernel32.CreateJobObjectW(None, None)
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        _apply_limits(info, limits)
        kernel32.SetInformationJobObject(
            _job_handle,
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
    PROCESS_ALL_ACCESS = 0x1F0FFF
    proc_handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not proc_handle:
        return
    try:
        kernel32.AssignProcessToJobObject(_job_handle, proc_handle)
    finally:
        kernel32.CloseHandle(proc_handle)
