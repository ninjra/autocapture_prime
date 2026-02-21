"""Compatibility wrapper for keyring operations referenced by the redesign doc.

The canonical implementation is `autocapture_nx.kernel.keyring.KeyRing`.
"""

from __future__ import annotations

from autocapture_nx.kernel.keyring import (  # noqa: F401
    KeyRing,
    KeyRecord,
    PurposeKeySet,
    export_keyring_bundle,
    import_keyring_bundle,
)

__all__ = [
    "KeyRing",
    "KeyRecord",
    "PurposeKeySet",
    "export_keyring_bundle",
    "import_keyring_bundle",
]

