"""DPAPI helpers used by proof-bundle signing/verification pathways.

This is a small compatibility shim so security-critical export/import code can
depend on a stable module path across NX/MX boundaries.
"""

from __future__ import annotations

import os


def protect(data: bytes) -> bytes:
    """Protect bytes with Windows DPAPI when available."""

    if os.name != "nt":
        raise RuntimeError("DPAPI protect requires Windows")
    from autocapture_nx.windows.dpapi import protect as _protect

    return _protect(data)


def unprotect(data: bytes) -> bytes:
    """Unprotect bytes with Windows DPAPI when available."""

    if os.name != "nt":
        raise RuntimeError("DPAPI unprotect requires Windows")
    from autocapture_nx.windows.dpapi import unprotect as _unprotect

    return _unprotect(data)

