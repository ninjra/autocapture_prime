"""Media store backed by BlobStore."""

from __future__ import annotations

from pathlib import Path

from autocapture.storage.blob_store import BlobStore
from autocapture.storage.keys import load_keyring


def create_media_store(plugin_id: str):
    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config

    config = load_config(default_config_paths(), safe_mode=False)
    root = Path(config.get("storage", {}).get("media_dir", "data/media"))
    return BlobStore(root, load_keyring(config))
