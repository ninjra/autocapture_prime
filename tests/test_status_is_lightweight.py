from __future__ import annotations

from autocapture_nx.kernel.loader import default_config_paths
from autocapture_nx.ux.facade import UXFacade


def test_status_does_not_force_kernel_boot(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOCAPTURE_DATA_DIR", str(tmp_path))
    facade = UXFacade(paths=default_config_paths(), persistent=False, safe_mode=False)
    assert facade._kernel_mgr.kernel() is None  # type: ignore[attr-defined]
    payload = facade.status()
    assert payload["kernel_ready"] is False
    assert "capture_status" in payload
    assert "processing_state" in payload
    assert "slo" in payload
    assert facade._kernel_mgr.kernel() is None  # type: ignore[attr-defined]
    facade.shutdown()
