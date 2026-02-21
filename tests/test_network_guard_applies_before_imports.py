from __future__ import annotations

import json
import os
import subprocess
import sys


def test_network_guard_blocks_import_time_outbound(tmp_path) -> None:
    # Create a plugin module that attempts outbound network at import time.
    plugin_path = tmp_path / "plugin.py"
    plugin_path.write_text(
        "\n".join(
            [
                "import socket",
                "import requests  # noqa: F401",
                "s = socket.socket()",
                "s.settimeout(0.1)",
                "s.connect(('1.1.1.1', 80))",
                "",
                "def create_plugin(plugin_id, ctx):",
                "    return type('P', (), {'capabilities': lambda self: {}})()",
                "",
            ]
        ),
        encoding="utf-8",
    )

    init = {
        "config": {
            "storage": {"data_dir": str(tmp_path)},
            "runtime": {"run_id": "test"},
            "plugins": {"hosting": {"rpc_timeout_s": 1, "rpc_max_message_bytes": 1000000}},
        },
        "host_config": {
            "plugins": {"hosting": {"rpc_timeout_s": 1, "rpc_max_message_bytes": 1000000}},
        },
        "allowed_capabilities": [],
        "filesystem_policy": {"read": [], "readwrite": []},
        "rng": {"enabled": False},
    }

    env = dict(os.environ)
    env["PYTHONPATH"] = str(os.getcwd())
    # Force deny by passing network_allowed=false.
    cmd = [
        sys.executable,
        "-m",
        "autocapture_nx.plugin_system.host_runner",
        str(plugin_path),
        "create_plugin",
        "test.plugin",
        "false",
    ]
    proc = subprocess.run(
        cmd,
        input=(json.dumps(init) + "\n").encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=8,
        check=False,
    )
    assert proc.returncode != 0
    err = proc.stderr.decode("utf-8", errors="replace")
    # PermissionError should be raised before plugin factory runs.
    assert "PermissionError" in err or "Network access is denied" in err

