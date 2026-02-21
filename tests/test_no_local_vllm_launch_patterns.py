from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_query_tools_do_not_launch_vllm() -> None:
    q1 = _read("tools/query_latest_single.py")
    q2 = _read("tools/run_advanced10_queries.py")
    assert "vllm_service.sh" not in q1
    assert "vllm_service.sh" not in q2
    assert ".entrypoints.openai.api_server" not in q1
    assert ".entrypoints.openai.api_server" not in q2
    assert "check_external_vllm_ready" in q1
    assert "check_external_vllm_ready" in q2


def test_vllm_service_script_is_probe_only() -> None:
    content = _read("tools/vllm_service.sh")
    assert "deprecated: local vLLM lifecycle is owned by the sidecar repo." in content
    assert "vllm.entrypoints.openai.api_server" not in content
    assert "nohup" not in content
    assert "start|stop|restart|logs" in content


def test_deprecated_powershell_launchers_are_stubbed() -> None:
    for path in (
        "tools/start_vllm.ps1",
        "tools/install_vllm.ps1",
        "tools/vllm_foreground_probe.ps1",
        "tools/wsl_vllm_log.ps1",
    ):
        text = _read(path)
        assert "DEPRECATED" in text
        assert "127.0.0.1:8000" in text
