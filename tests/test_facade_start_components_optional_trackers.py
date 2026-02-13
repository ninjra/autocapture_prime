from __future__ import annotations

from contextlib import contextmanager


class _FakeKernelMgr:
    def __init__(self, system):
        self._system = system

    @contextmanager
    def session(self):
        yield self._system

    def last_error(self):
        return None


class _FakeSystem:
    def __init__(self, caps: dict[str, object]):
        self._caps = dict(caps)

    def has(self, capability: str) -> bool:
        return capability in self._caps

    def get(self, capability: str):
        return self._caps[capability]


class _StartOK:
    def start(self):
        return None


def test_start_components_allows_missing_optional_trackers():
    from autocapture_nx.ux.facade import UXFacade

    facade = UXFacade(persistent=True, auto_start_capture=False)
    facade._config = {
        "privacy": {"capture": {"require_consent": False}},
        "capture": {
            "video": {"enabled": False},
            "audio": {"enabled": False},
            "screenshot": {"enabled": True},
            # Even if these are "enabled", trackers must remain optional for soak.
            "window_metadata": {"enabled": True},
            "input_tracking": {"mode": "win32_idle"},
        },
    }
    system = _FakeSystem({"capture.screenshot": _StartOK()})
    facade._kernel_mgr = _FakeKernelMgr(system)

    result = facade._start_components()
    assert result.get("ok") is True
    started = result.get("started") or []
    assert "capture.screenshot" in started

