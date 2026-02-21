"""Compatibility wrapper for the redesign doc enforcement locations.

The canonical implementation lives in `autocapture/indexing/lexical.py`, but the
adversarial redesign traceability expects a stable module path here.
"""

from __future__ import annotations

from autocapture.indexing.lexical import LexicalIndex

__all__ = ["LexicalIndex"]

