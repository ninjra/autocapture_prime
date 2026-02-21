import os
import shutil
import tempfile
import unittest
from pathlib import Path

from autocapture.indexing.vector import LocalEmbedder
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.vlm_stub.plugin import VLMStub

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    Image = None
    _PIL_AVAILABLE = False


class LocalModelFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_bundle_dir = os.environ.get("AUTOCAPTURE_BUNDLE_DIR")
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        shutil.copytree(Path("tests/fixtures/bundles/embedder_toy"), root / "embedder_toy")
        shutil.copytree(Path("tests/fixtures/bundles/vlm_toy"), root / "vlm_toy")
        os.environ["AUTOCAPTURE_BUNDLE_DIR"] = self._tmp.name

    def tearDown(self) -> None:
        if self._orig_bundle_dir is None:
            os.environ.pop("AUTOCAPTURE_BUNDLE_DIR", None)
        else:
            os.environ["AUTOCAPTURE_BUNDLE_DIR"] = self._orig_bundle_dir
        self._tmp.cleanup()

    def test_toy_embedder_bundle(self) -> None:
        embedder = LocalEmbedder()
        vec = embedder.embed("hello world")
        self.assertEqual(len(vec), 8)
        self.assertGreater(vec[0], 0.0)
        self.assertGreater(vec[1], 0.0)
        identity = embedder.identity()
        self.assertEqual(identity.get("backend"), "toy")
        self.assertEqual(identity.get("bundle_id"), "embedder.toy")
        self.assertEqual(identity.get("bundle_version"), "1.0.0")
        self.assertIn("model_name", identity)

    @unittest.skipIf(not _PIL_AVAILABLE, "Pillow not available")
    def test_toy_vlm_bundle(self) -> None:
        context = PluginContext(config={}, get_capability=lambda _name: None, logger=lambda _msg: None)
        plugin = VLMStub("builtin.vlm.stub", context)
        image = Image.new("RGB", (32, 32), (250, 250, 250))
        buffer = tempfile.TemporaryFile()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        payload = plugin.extract(buffer.read())
        self.assertEqual(payload.get("backend"), "toy.vlm")
        self.assertEqual(payload.get("caption"), "Toy caption: overview of the screen contents.")
        self.assertEqual(payload.get("text_plain"), "Toy caption: overview of the screen contents.")
        self.assertEqual(payload.get("bundle_id"), "vlm.toy")
        self.assertIsInstance(payload.get("layout"), dict)
        self.assertIn("tags", payload)
        buffer.close()


if __name__ == "__main__":
    unittest.main()
