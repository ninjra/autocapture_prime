import os
import tempfile
import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.anchor_basic.plugin import AnchorWriter


class AnchorTests(unittest.TestCase):
    def test_anchor_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            anchor_path = os.path.join(tmp, "anchor", "anchors.ndjson")
            config = {"storage": {"data_dir": tmp, "anchor": {"path": anchor_path, "use_dpapi": False}}}
            ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
            writer = AnchorWriter("anchor", ctx)
            record = writer.anchor("deadbeef")
            self.assertEqual(record["ledger_head_hash"], "deadbeef")
            self.assertTrue(os.path.exists(anchor_path))


if __name__ == "__main__":
    unittest.main()
