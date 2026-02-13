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


class _StartAttrRaises:
    def __getattr__(self, name: str):
        if name == "start":
            raise RuntimeError("no providers")
        raise AttributeError(name)


class _StartOK:
    def start(self):
        return None


def test_start_components_marks_required_not_startable_as_error():
    # Avoid booting the real kernel. We only want to validate UXFacade's
    # required-component startability checks.
    from autocapture_nx.ux.facade import UXFacade

    facade = UXFacade(persistent=True, auto_start_capture=False)
    # Minimal config: screenshot required, video/audio disabled.
    facade._config = {
        "privacy": {"capture": {"require_consent": False}},
        "capture": {
            "video": {"enabled": False},
            "audio": {"enabled": False},
            "screenshot": {"enabled": True},
        },
    }
    system = _FakeSystem(
        {
            "capture.source": _StartOK(),
            "capture.screenshot": _StartAttrRaises(),
            "tracking.input": _StartOK(),
        }
    )
    facade._kernel_mgr = _FakeKernelMgr(system)

    result = facade._start_components()
    assert result.get("ok") is False
    assert result.get("error") == "component_start_failed"
    errors = result.get("errors") or []
    assert any(isinstance(e, dict) and e.get("component") == "capture.screenshot" for e in errors)

