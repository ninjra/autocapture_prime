"""MX plugin system."""

from .kinds import REQUIRED_KINDS, all_kinds, is_required
from .manifest import ExtensionManifest, PluginManifest
from .manager import PluginManager

__all__ = [
    "REQUIRED_KINDS",
    "all_kinds",
    "is_required",
    "ExtensionManifest",
    "PluginManifest",
    "PluginManager",
]
