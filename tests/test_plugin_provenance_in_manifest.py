from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from autocapture_nx.kernel.event_builder import EventBuilder
from autocapture_nx.kernel.config import ConfigPaths
from autocapture_nx.kernel.ids import ensure_run_id, prefixed_id
from autocapture_nx.kernel.loader import Kernel


class _DictStore:
    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def put_new(self, key: str, value: dict) -> None:
        if key in self._store:
            raise FileExistsError(key)
        self._store[key] = value

    def get(self, key: str, default=None):
        return self._store.get(key, default)


class _Caps:
    def __init__(self, metadata: _DictStore, media: object) -> None:
        self._metadata = metadata
        self._media = media

    def get(self, name: str):
        if name == "storage.metadata":
            return self._metadata
        if name == "storage.media":
            return self._media
        raise KeyError(name)


class _Journal:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def append_event(
        self,
        event_type: str,
        payload: dict,
        *,
        event_id: str | None = None,
        ts_utc: str | None = None,
        tzid: str | None = None,
        offset_minutes: int | None = None,
    ) -> str:
        self.events.append(
            {
                "event_type": str(event_type),
                "payload": dict(payload),
                "event_id": event_id,
                "ts_utc": ts_utc,
                "tzid": tzid,
                "offset_minutes": offset_minutes,
            }
        )
        return "journal_hash"


class _Ledger:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def append(self, entry: dict) -> str:
        self.entries.append(dict(entry))
        return "ledger_hash"


class _Anchor:
    def anchor(self, _ledger_hash: str) -> str:
        return "anchor_id"


class PluginProvenanceManifestTests(unittest.TestCase):
    def test_manifest_includes_plugin_provenance_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            default_path = root / "default.json"
            user_path = root / "user.json"
            schema_path = root / "schema.json"
            default_path.write_text("{}", encoding="utf-8")
            user_path.write_text("{}", encoding="utf-8")
            schema_path.write_text("{}", encoding="utf-8")
            lockfile = root / "plugin_locks.json"
            lockfile.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "plugins": {
                            "builtin.storage.encrypted": {
                                "manifest_sha256": "m" * 64,
                                "artifact_sha256": "a" * 64,
                            }
                        },
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            cfg: dict = {
                "storage": {"data_dir": str(data_dir)},
                "plugins": {"locks": {"enforce": True, "lockfile": str(lockfile)}},
            }
            ensure_run_id(cfg)
            kernel = Kernel(
                ConfigPaths(
                    default_path=default_path,
                    user_path=user_path,
                    schema_path=schema_path,
                    backup_dir=(root / "backup").resolve(),
                )
            )
            kernel.config = cfg

            store = _DictStore()
            caps = _Caps(store, object())
            builder = EventBuilder(cfg, _Journal(), _Ledger(), _Anchor())
            plugins = [
                SimpleNamespace(
                    plugin_id="builtin.storage.encrypted",
                    manifest={
                        "plugin_id": "builtin.storage.encrypted",
                        "version": "0.1.0",
                        "permissions": {"network": False, "filesystem": "readwrite"},
                    },
                )
            ]

            kernel._record_storage_manifest(builder, caps, plugins, include_packages=False, include_counts=False)

            record_id = prefixed_id(builder.run_id, "system.run_manifest", 0)
            payload = store.get(record_id)
            self.assertIsInstance(payload, dict)
            prov = payload.get("plugin_provenance")
            self.assertIsInstance(prov, dict)
            item = prov.get("builtin.storage.encrypted")
            self.assertIsInstance(item, dict)
            self.assertEqual(item.get("manifest_sha256"), "m" * 64)
            self.assertEqual(item.get("artifact_sha256"), "a" * 64)
            self.assertIsInstance(item.get("permissions"), dict)


if __name__ == "__main__":
    unittest.main()
