import os
import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.kernel.keyring import KeyRing
from autocapture.pillars.citable import verify_anchors
from plugins.builtin.anchor_basic.plugin import AnchorWriter


class AnchorTests(unittest.TestCase):
    def test_anchor_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            anchor_path = os.path.join(tmp, "anchor", "anchors.ndjson")
            keyring_path = os.path.join(tmp, "vault", "keyring.json")
            root_key_path = os.path.join(tmp, "vault", "root.key")
            keyring = KeyRing.load(keyring_path, legacy_root_path=root_key_path, require_protection=False)
            config = {"storage": {"data_dir": tmp, "anchor": {"path": anchor_path, "use_dpapi": False}}}
            writer = AnchorWriter(
                "anchor",
                PluginContext(
                    config=config,
                    get_capability=lambda k: keyring if k == "storage.keyring" else None,
                    logger=lambda _m: None,
                ),
            )
            record = writer.anchor("deadbeef")
            self.assertEqual(record["ledger_head_hash"], "deadbeef")
            self.assertTrue(os.path.exists(anchor_path))
            ok, errors = verify_anchors(Path(anchor_path), keyring)
            self.assertTrue(ok, errors)

            # Tamper with anchor to ensure HMAC verification fails
            lines = Path(anchor_path).read_text(encoding="utf-8").splitlines()
            tampered = json.loads(lines[-1])
            tampered["ledger_head_hash"] = "badbeef"
            lines[-1] = json.dumps(tampered)
            Path(anchor_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
            ok, errors = verify_anchors(Path(anchor_path), keyring)
            self.assertFalse(ok)
            self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
