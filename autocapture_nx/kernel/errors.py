"""Kernel error types."""


class AutocaptureError(Exception):
    """Base error for Autocapture NX."""


class ConfigError(AutocaptureError):
    """Raised when configuration validation or loading fails."""


class PluginError(AutocaptureError):
    """Raised when plugin loading or validation fails."""


class PermissionError(AutocaptureError):
    """Raised when a permission check fails."""


class SafeModeError(AutocaptureError):
    """Raised when a safe-mode invariant is violated."""


class NetworkDisabledError(AutocaptureError):
    """Raised when network access is attempted while disabled."""
