from __future__ import annotations

import pytest


def test_tray_requires_loopback_bind_host() -> None:
    from autocapture_nx.tray import _ensure_loopback_host

    assert _ensure_loopback_host("127.0.0.1") == "127.0.0.1"
    with pytest.raises(RuntimeError):
        _ensure_loopback_host("0.0.0.0")
    with pytest.raises(RuntimeError):
        _ensure_loopback_host("::1")

