import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from autocapture_nx.kernel.config import ConfigPaths
from autocapture_nx.kernel.event_builder import EventBuilder
from autocapture_nx.kernel.ids import ensure_run_id, prefixed_id
from autocapture_nx.kernel.loader import Kernel


class _DummyJournal:
    def append_event(self, *args, **kwargs):
        _ = args
        _ = kwargs
        return "event"


class _DummyLedger:
    def append(self, entry):
        _ = entry
        return "hash"


class _DummyAnchor:
    def anchor(self, _ledger_hash: str) -> None:
        return None


class _DictStore:
    def __init__(self) -> None:
        self.data = {}

    def put_new(self, key: str, value):
        if key in self.data:
            raise FileExistsError(f"Record already exists: {key}")
        self.data[key] = value

    def put(self, key: str, value):
        self.data[key] = value

    def get(self, key: str, default=None):
        return self.data.get(key, default)


class _Caps:
    def __init__(self, store, media):
        self._store = store
        self._media = media

    def get(self, name: str):
        if name == "storage.metadata":
            return self._store
        if name == "storage.media":
            return self._media
        raise KeyError(name)


class RunManifestTests(unittest.TestCase):
    def test_run_manifest_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default_path = root / "default.json"
            user_path = root / "user.json"
            schema_path = root / "schema.json"
            backup_dir = root / "backup"

            default = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
            schema = json.loads(Path("contracts/config_schema.json").read_text(encoding="utf-8"))
            default_path.write_text(json.dumps(default, indent=2, sort_keys=True), encoding="utf-8")
            user_path.write_text("{}", encoding="utf-8")
            schema_path.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")

            paths = ConfigPaths(default_path, user_path, schema_path, backup_dir)
            kernel = Kernel(paths, safe_mode=False)
            effective = kernel.load_effective_config()
            kernel.config = effective.data
            kernel.effective_config = effective
            ensure_run_id(kernel.config)

            store = _DictStore()
            caps = _Caps(store, object())
            builder = EventBuilder(kernel.config, _DummyJournal(), _DummyLedger(), _DummyAnchor())
            plugins = [SimpleNamespace(plugin_id="builtin.storage.encrypted")]

            kernel._record_storage_manifest(builder, caps, plugins)

            record_id = prefixed_id(builder.run_id, "system.run_manifest", 0)
            self.assertIn(record_id, store.data)
            payload = store.data[record_id]
            self.assertEqual(payload.get("record_type"), "system.run_manifest")
            self.assertEqual(payload.get("run_id"), builder.run_id)
            self.assertIn("locks", payload)
            self.assertIn("plugins", payload)
            self.assertIn("packages", payload)
            self.assertIsInstance(payload.get("packages"), dict)
            self.assertIn("package_fingerprint", payload)

    def test_run_manifest_final_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default_path = root / "default.json"
            user_path = root / "user.json"
            schema_path = root / "schema.json"
            backup_dir = root / "backup"

            default = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
            schema = json.loads(Path("contracts/config_schema.json").read_text(encoding="utf-8"))
            default_path.write_text(json.dumps(default, indent=2, sort_keys=True), encoding="utf-8")
            user_path.write_text("{}", encoding="utf-8")
            schema_path.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")

            paths = ConfigPaths(default_path, user_path, schema_path, backup_dir)
            kernel = Kernel(paths, safe_mode=False)
            effective = kernel.load_effective_config()
            kernel.config = effective.data
            kernel.effective_config = effective
            ensure_run_id(kernel.config)

            store = _DictStore()
            system = SimpleNamespace(
                config=kernel.config,
                plugins=[SimpleNamespace(plugin_id="builtin.storage.encrypted")],
                get=lambda name: store if name == "storage.metadata" else None,
            )
            kernel.system = system
            builder = EventBuilder(kernel.config, _DummyJournal(), _DummyLedger(), _DummyAnchor())

            kernel._record_storage_manifest_final(builder, {"events": 0, "drops": 0, "errors": 0}, 0, "2024-01-01T00:00:00+00:00")

            record_id = prefixed_id(builder.run_id, "system.run_manifest.final", 0)
            self.assertIn(record_id, store.data)
            payload = store.data[record_id]
            self.assertEqual(payload.get("record_type"), "system.run_manifest.final")
            self.assertEqual(payload.get("run_id"), builder.run_id)
            self.assertIn("packages", payload)
            self.assertIsInstance(payload.get("packages"), dict)
            self.assertIn("package_fingerprint", payload)


if __name__ == "__main__":
    unittest.main()
