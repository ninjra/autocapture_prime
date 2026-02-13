from __future__ import annotations

from pathlib import Path

import pytest

from autocapture_nx.inference.vllm_endpoint import EXTERNAL_VLLM_BASE_URL, enforce_external_vllm_base_url


def test_enforce_external_vllm_base_url_accepts_default_and_canonical() -> None:
    assert enforce_external_vllm_base_url(None) == EXTERNAL_VLLM_BASE_URL
    assert enforce_external_vllm_base_url("") == EXTERNAL_VLLM_BASE_URL
    assert enforce_external_vllm_base_url("http://127.0.0.1:8000") == EXTERNAL_VLLM_BASE_URL
    assert enforce_external_vllm_base_url("http://127.0.0.1:8000/") == EXTERNAL_VLLM_BASE_URL


@pytest.mark.parametrize(
    "candidate",
    [
        "http://localhost:8000",
        "http://127.0.0.1:9000",
        "https://127.0.0.1:8000",
        "http://0.0.0.0:8000",
        "http://192.168.1.10:8000",
    ],
)
def test_enforce_external_vllm_base_url_rejects_noncanonical(candidate: str) -> None:
    with pytest.raises(ValueError):
        enforce_external_vllm_base_url(candidate)


def test_vllm_plugins_apply_external_endpoint_policy() -> None:
    files = (
        "plugins/builtin/vlm_vllm_localhost/plugin.py",
        "plugins/builtin/answer_synth_vllm_localhost/plugin.py",
        "plugins/builtin/embedder_vllm_localhost/plugin.py",
        "plugins/builtin/ocr_nemotron_torch/plugin.py",
    )
    for rel in files:
        text = Path(rel).read_text(encoding="utf-8")
        assert "enforce_external_vllm_base_url" in text

