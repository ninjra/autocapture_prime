from __future__ import annotations

import importlib

from autocapture_nx.runtime import service_ports


def test_service_ports_defaults_are_canonical_localhost(monkeypatch) -> None:
    for name in (
        "AUTOCAPTURE_VLM_ROOT_URL",
        "AUTOCAPTURE_VLM_MODEL",
        "AUTOCAPTURE_EMBEDDER_BASE_URL",
        "AUTOCAPTURE_EMBEDDER_MODEL",
        "AUTOCAPTURE_GROUNDING_BASE_URL",
        "AUTOCAPTURE_HYPERVISOR_GATEWAY_BASE_URL",
        "AUTOCAPTURE_POPUP_QUERY_BASE_URL",
        "AUTOCAPTURE_DEVTOOLS_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    mod = importlib.reload(service_ports)
    assert mod.VLM_ROOT_URL == "http://127.0.0.1:8000"
    assert mod.VLM_BASE_URL == "http://127.0.0.1:8000/v1"
    assert mod.VLM_MODEL_ID == "internvl3_5_8b"
    assert mod.EMBEDDER_BASE_URL == "http://127.0.0.1:8001"
    assert mod.EMBEDDER_MODEL_ID == "BAAI/bge-small-en-v1.5"
    assert mod.GROUNDING_BASE_URL == "http://127.0.0.1:8011"
    assert mod.HYPERVISOR_GATEWAY_BASE_URL == "http://127.0.0.1:34221"
    assert mod.POPUP_QUERY_BASE_URL == "http://127.0.0.1:8787"
    assert mod.DEVTOOLS_BASE_URL == "http://127.0.0.1:7411"
