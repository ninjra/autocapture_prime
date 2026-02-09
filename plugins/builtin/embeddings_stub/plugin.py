"""Compatibility embeddings plugin (alias of the embedder stub).

The adversarial redesign spec references `plugins/builtin/embeddings_*`.
This plugin keeps the older naming available without changing runtime behavior.
"""

from __future__ import annotations

from plugins.builtin.embedder_stub.plugin import EmbedderBasic as _EmbedderBasic


def create_plugin(plugin_id: str, context):  # noqa: ANN001
    return _EmbedderBasic(plugin_id, context)

