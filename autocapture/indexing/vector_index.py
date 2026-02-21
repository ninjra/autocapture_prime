"""Compatibility wrapper for the redesign doc enforcement locations.

The canonical implementation lives in `autocapture/indexing/vector.py`, but the
adversarial redesign traceability expects a stable module path here.
"""

from __future__ import annotations

from autocapture.indexing.vector import LocalEmbedder, QdrantVectorIndex, VectorIndex

__all__ = ["LocalEmbedder", "QdrantVectorIndex", "VectorIndex"]

