"""Tooling package marker.

This repo primarily executes tools via `python tools/<script>.py`, but a small
subset of tools also import shared helpers. Making `tools` a package keeps those
imports stable and deterministic.
"""

