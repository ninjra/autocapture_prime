import os
import socket
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.errors import PermissionError
from autocapture_nx.plugin_system.runtime import FilesystemPolicy, filesystem_guard, network_guard


class SecurityGuardsTests(unittest.TestCase):
    def test_network_guard_blocks_outbound_connections(self) -> None:
        with network_guard(False):
            with self.assertRaises(PermissionError):
                socket.create_connection(("example.com", 80), timeout=0.5)

    def test_filesystem_guard_blocks_dotdot_escape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            allowed = root / "allowed"
            allowed.mkdir()
            outside = root / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            policy = FilesystemPolicy.from_paths(read=[allowed], readwrite=[])
            escaped = allowed / ".." / "outside.txt"
            with filesystem_guard(policy):
                with self.assertRaises(PermissionError):
                    escaped.read_text(encoding="utf-8")

    def test_filesystem_guard_blocks_symlink_escape(self) -> None:
        if os.name == "nt":
            self.skipTest("symlink behavior varies on Windows runners")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            allowed = root / "allowed"
            allowed.mkdir()
            outside = root / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            link = allowed / "link.txt"
            try:
                link.symlink_to(outside)
            except Exception:
                self.skipTest("symlink not supported")
            policy = FilesystemPolicy.from_paths(read=[allowed], readwrite=[])
            with filesystem_guard(policy):
                with self.assertRaises(PermissionError):
                    link.read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

