from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.embedder_vllm_localhost.plugin import create_plugin


def _ctx(config: dict[str, object]) -> PluginContext:
    return PluginContext(
        config=config,
        get_capability=lambda _name: None,
        logger=lambda _msg: None,
        rng=None,
        rng_seed=None,
        rng_seed_hex=None,
    )


def test_embedder_requires_remote_model_and_returns_empty_when_unset() -> None:
    plugin = create_plugin(
        "builtin.embedder.vllm_localhost",
        _ctx({"base_url": "http://127.0.0.1:8000", "model": "", "timeout_s": 1.0}),
    )
    assert plugin.embed("hello world") == []
    ident = plugin.identity()
    assert ident.get("strict_remote_only") is True
    assert str(ident.get("last_error") or "").startswith("embed_model_unset")


def test_embedder_does_not_fallback_when_remote_request_fails(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class _FailClient:
        def __init__(self, **_kwargs) -> None:
            return None

        def embeddings(self, _payload):
            raise RuntimeError("down")

    monkeypatch.setattr("plugins.builtin.embedder_vllm_localhost.plugin.OpenAICompatClient", _FailClient)
    plugin = create_plugin(
        "builtin.embedder.vllm_localhost",
        _ctx({"base_url": "http://127.0.0.1:8000", "model": "dummy-embed", "timeout_s": 1.0}),
    )
    assert plugin.embed("hello world") == []
    ident = plugin.identity()
    assert "embed_request_failed" in str(ident.get("last_error") or "")


def test_embedder_uses_remote_vector_when_available(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class _OkClient:
        def __init__(self, **_kwargs) -> None:
            return None

        def embeddings(self, _payload):
            return {"data": [{"embedding": [0.125, 0.25, 0.5]}]}

    monkeypatch.setattr("plugins.builtin.embedder_vllm_localhost.plugin.OpenAICompatClient", _OkClient)
    plugin = create_plugin(
        "builtin.embedder.vllm_localhost",
        _ctx({"base_url": "http://127.0.0.1:8000", "model": "dummy-embed", "timeout_s": 1.0}),
    )
    assert plugin.embed("hello world") == [0.125, 0.25, 0.5]
    ident = plugin.identity()
    assert ident.get("last_error", "") == ""
