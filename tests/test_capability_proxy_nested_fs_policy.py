from __future__ import annotations

import os
from pathlib import Path

from autocapture_nx.plugin_system.registry import CapabilityProxy
from autocapture_nx.plugin_system.runtime import FilesystemPolicy


class _LazyStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)

    def __getattr__(self, name: str):
        if name != "latest":
            raise AttributeError(name)
        # Simulate lazy store init that requires write access.
        os.makedirs(self._data_dir, exist_ok=True)

        def _latest(*_args, **_kwargs):
            return {}

        return _latest


class _RetrievalLike:
    def __init__(self, store: CapabilityProxy) -> None:
        self._store = store

    def search(self) -> dict:
        latest = self._store.latest
        return latest()


def test_nested_capability_attribute_resolution_uses_callee_filesystem_policy(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store_policy = FilesystemPolicy.from_paths(read=[data_dir], readwrite=[data_dir])
    retrieval_policy = FilesystemPolicy.from_paths(read=[tmp_path], readwrite=[])

    store = CapabilityProxy(_LazyStore(data_dir), network_allowed=False, filesystem_policy=store_policy)
    retrieval = CapabilityProxy(_RetrievalLike(store), network_allowed=False, filesystem_policy=retrieval_policy)

    out = retrieval.search()
    assert isinstance(out, dict)
    assert data_dir.exists()
