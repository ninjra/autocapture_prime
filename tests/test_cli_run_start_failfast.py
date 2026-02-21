from __future__ import annotations

import types

import autocapture_nx.cli as cli


def test_cmd_run_exits_nonzero_when_run_start_fails(monkeypatch, capsys) -> None:
    class FakeFacade:
        def run_start(self):
            return {"ok": False, "error": "kernel_boot_failed"}

        def shutdown(self):
            return None

    monkeypatch.setattr(cli, "create_facade", lambda **_kwargs: FakeFacade())
    args = types.SimpleNamespace(duration_s=1, status_interval_s=0, safe_mode=False)
    code = cli.cmd_run(args)
    out = capsys.readouterr().out
    assert code == 2
    assert "kernel_boot_failed" in out

