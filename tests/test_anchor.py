import os
import json
import tempfile
import unittest
import builtins
from pathlib import Path
from unittest.mock import patch

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

    def test_anchor_does_not_crash_when_keyring_unprotect_fails(self):
        class _BrokenKeyring:
            def active_key(self, _purpose: str):
                raise RuntimeError("DPAPI unprotect requires Windows")

        with tempfile.TemporaryDirectory() as tmp:
            anchor_path = os.path.join(tmp, "anchor", "anchors.ndjson")
            config = {
                "storage": {
                    "data_dir": tmp,
                    "anchor": {"path": anchor_path, "use_dpapi": False, "sign": True},
                }
            }
            writer = AnchorWriter(
                "anchor",
                PluginContext(
                    config=config,
                    get_capability=lambda k: _BrokenKeyring() if k == "storage.keyring" else None,
                    logger=lambda _m: None,
                ),
            )
            record = writer.anchor("deadbeef")
            self.assertEqual(record["ledger_head_hash"], "deadbeef")
            self.assertNotIn("anchor_hmac", record)
            self.assertTrue(os.path.exists(anchor_path))

    def test_anchor_falls_back_when_primary_append_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            anchor_path = os.path.join(tmp, "anchor", "anchors.ndjson")
            keyring_path = os.path.join(tmp, "vault", "keyring.json")
            root_key_path = os.path.join(tmp, "vault", "root.key")
            keyring = KeyRing.load(keyring_path, legacy_root_path=root_key_path, require_protection=False)
            writer = AnchorWriter(
                "anchor",
                PluginContext(
                    config={"storage": {"data_dir": tmp, "anchor": {"path": anchor_path, "use_dpapi": False}}},
                    get_capability=lambda k: keyring if k == "storage.keyring" else None,
                    logger=lambda _m: None,
                ),
            )
            real_open = builtins.open

            def fake_open(path, *args, **kwargs):
                mode = args[0] if args else kwargs.get("mode", "r")
                if path == anchor_path and "a" in str(mode):
                    raise PermissionError("denied")
                return real_open(path, *args, **kwargs)

            with patch("plugins.builtin.anchor_basic.plugin.open", side_effect=fake_open):
                record = writer.anchor("deadbeef")
            self.assertEqual(record["ledger_head_hash"], "deadbeef")
            self.assertNotEqual(writer._path, anchor_path)  # pylint: disable=protected-access


if __name__ == "__main__":
    unittest.main()
