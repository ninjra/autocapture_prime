from __future__ import annotations

from contextlib import contextmanager
import time


class _BootFailKernelMgr:
    @contextmanager
    def session(self):
        yield None

    def last_error(self):
        return "ConfigError:instance_lock_held"


class _BootFailMissingCapabilityKernelMgr(_BootFailKernelMgr):
    def last_error(self):
        return "Missing capability: storage.metadata, retrieval.strategy."


def test_query_returns_deterministic_payload_when_kernel_boot_fails():
    from autocapture_nx.ux.facade import UXFacade

    facade = UXFacade(persistent=True, auto_start_capture=False)
    facade._kernel_mgr = _BootFailKernelMgr()  # noqa: SLF001
    out = facade.query("status")
    assert bool(out.get("ok")) is False
    assert str(out.get("error") or "") == "kernel_boot_failed"
    answer = out.get("answer", {}) if isinstance(out.get("answer", {}), dict) else {}
    assert str(answer.get("state") or "") == "degraded"
    processing = out.get("processing", {}) if isinstance(out.get("processing", {}), dict) else {}
    extraction = processing.get("extraction", {}) if isinstance(processing.get("extraction", {}), dict) else {}
    assert str(extraction.get("blocked_reason") or "") == "kernel_boot_failed"
    trace = processing.get("query_trace", {}) if isinstance(processing.get("query_trace", {}), dict) else {}
    assert str(trace.get("error") or "") == "kernel_boot_failed"


def test_query_returns_capability_missing_payload_quickly_on_boot_error():
    from autocapture_nx.ux.facade import UXFacade

    facade = UXFacade(persistent=True, auto_start_capture=False)
    facade._kernel_mgr = _BootFailMissingCapabilityKernelMgr()  # noqa: SLF001
    started = time.perf_counter()
    out = facade.query("status")
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert float(elapsed_ms) < 500.0
    assert bool(out.get("ok")) is False
    assert str(out.get("error") or "") == "query_capability_missing"
    processing = out.get("processing", {}) if isinstance(out.get("processing", {}), dict) else {}
    extraction = processing.get("extraction", {}) if isinstance(processing.get("extraction", {}), dict) else {}
    assert str(extraction.get("blocked_reason") or "") == "query_capability_missing"
    trace = processing.get("query_trace", {}) if isinstance(processing.get("query_trace", {}), dict) else {}
    missing = trace.get("missing_capabilities", [])
    assert isinstance(missing, list)
    assert "storage.metadata" in missing


def test_kernel_manager_releases_kernel_on_boot_failure(monkeypatch):
    from autocapture_nx.kernel.loader import default_config_paths
    from autocapture_nx.ux.facade import KernelManager

    events: list[str] = []

    class _FailKernel:
        def __init__(self, *_args, **_kwargs):
            events.append("init")

        def boot(self, *_, **__):
            events.append("boot")
            raise RuntimeError("boom")

        def shutdown(self):
            events.append("shutdown")

    monkeypatch.setattr("autocapture_nx.ux.facade.Kernel", _FailKernel)
    km = KernelManager(default_config_paths(), persistent=True, start_conductor=False)
    with km.session() as system:
        assert system is None
    assert "shutdown" in events
