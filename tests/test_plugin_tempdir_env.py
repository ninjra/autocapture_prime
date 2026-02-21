import os
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.registry import CapabilityProxy
from autocapture_nx.plugin_system.runtime import FilesystemPolicy


class PluginTempdirEnvTests(unittest.TestCase):
    def test_capability_proxy_tempdir_allows_tempfile_write(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="acp_tmpdir_test_"))
        allowed_tmp = base / "allowed_tmp"
        policy = FilesystemPolicy.from_paths(read=[], readwrite=[str(allowed_tmp)])

        def write_temp() -> str:
            with tempfile.NamedTemporaryFile(mode="w", delete=True) as handle:
                handle.write("ok")
                return str(Path(handle.name).parent)

        # Baseline: without temp_dir override, tempfile should attempt /tmp and fail under the guard.
        proxy_no_tmp = CapabilityProxy(write_temp, network_allowed=False, filesystem_policy=policy, plugin_id="test.plugin")
        with self.assertRaises(Exception):
            proxy_no_tmp()

        # With temp_dir override, the call should succeed and write under allowed_tmp.
        prev = {k: os.environ.get(k) for k in ("TMPDIR", "TMP", "TEMP")}
        proxy = CapabilityProxy(
            write_temp,
            network_allowed=False,
            filesystem_policy=policy,
            plugin_id="test.plugin",
            temp_dir=str(allowed_tmp),
        )
        used_dir = proxy()
        self.assertEqual(Path(used_dir).resolve(), allowed_tmp.resolve())
        self.assertEqual({k: os.environ.get(k) for k in ("TMPDIR", "TMP", "TEMP")}, prev)

    def test_capability_proxy_tempdir_file_collision_falls_back_to_dir(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="acp_tmpdir_collision_"))
        file_path = base / "tmp"
        file_path.write_text("occupied", encoding="utf-8")
        policy = FilesystemPolicy.from_paths(read=[], readwrite=[str(base)])

        def write_temp() -> str:
            with tempfile.NamedTemporaryFile(mode="w", delete=True) as handle:
                handle.write("ok")
                return str(Path(handle.name).parent)

        proxy = CapabilityProxy(
            write_temp,
            network_allowed=False,
            filesystem_policy=policy,
            plugin_id="test.plugin",
            temp_dir=str(file_path),
        )
        used_dir = Path(proxy())
        self.assertTrue(used_dir.name.endswith(".dir"))
        self.assertTrue(used_dir.exists())
        self.assertTrue(used_dir.is_dir())


if __name__ == "__main__":
    unittest.main()
