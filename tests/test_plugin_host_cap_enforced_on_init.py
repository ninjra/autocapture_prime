from __future__ import annotations

import itertools
from pathlib import Path

import pytest


def test_subprocess_plugin_host_cap_enforced_during_init(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    Regression test for WSL crashes: SubprocessPlugin instances must be visible to
    the reaper/cap logic even during init-time host starts, so bursts of plugin
    loads can't spawn an unbounded number of host_runner processes.
    """

    import autocapture_nx.plugin_system.host as host

    monkeypatch.setenv("AUTOCAPTURE_PLUGINS_LAZY_START", "0")
    monkeypatch.setenv("AUTOCAPTURE_PLUGINS_SUBPROCESS_SPAWN_WAIT_S", "2")

    close_count = {"n": 0}
    pid_counter = itertools.count(1000)

    class _FakeProc:
        def __init__(self) -> None:
            self.pid = next(pid_counter)

    class FakePluginProcess:
        def __init__(self, *args, **kwargs) -> None:
            self._proc = _FakeProc()
            self._closed = False

        def capabilities(self) -> dict[str, list[str]]:
            return {"cap.test": ["noop"]}

        def close(self) -> None:
            if self._closed:
                return
            self._closed = True
            close_count["n"] += 1

    monkeypatch.setattr(host, "PluginProcess", FakePluginProcess)

    config = {
        "storage": {"data_dir": str(tmp_path / "data")},
        "plugins": {"hosting": {"subprocess_max_hosts": 2, "subprocess_idle_ttl_s": 0.0}},
    }
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    plugin_file = tmp_path / "plugin.py"
    plugin_file.write_text("# test stub\n", encoding="utf-8")

    try:
        for i in range(6):
            host.SubprocessPlugin(
                plugin_path=plugin_file,
                callable_name="create_plugin",
                plugin_id=f"test.plugin.{i}",
                network_allowed=False,
                config=config,
                plugin_config={},
                capabilities={},
                allowed_capabilities=set(),
                filesystem_policy=None,
                entrypoint_kind="not-a-capability",  # forces init-time host start when lazy start is disabled
                provided_capabilities=[],
            )
            report = host.reap_subprocess_hosts(force=False, bypass_interval_gate=True)
            assert int(report.get("remaining", 0)) <= 2
    finally:
        host.close_all_subprocess_hosts(reason="test_cleanup")

    # Creating 6 plugins with max_hosts=2 must have caused closures at some point.
    assert close_count["n"] > 0

