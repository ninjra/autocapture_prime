"""Core error types for MX."""

from __future__ import annotations


class AutocaptureError(RuntimeError):
    """Base error for MX modules."""


class ConfigError(AutocaptureError):
    """Raised when configuration is invalid or missing."""


class SchemaValidationError(AutocaptureError):
    """Raised when schema validation fails."""
