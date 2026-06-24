"""Custom exception hierarchy for the desktop app."""


class AppError(Exception):
    """Base application error."""


class ConfigError(AppError):
    """Raised when configuration cannot be loaded or validated."""


class BrowserNotReadyError(AppError):
    """Raised when browser operations are attempted before startup."""


class CollectionStoppedError(AppError):
    """Raised when a collection run is stopped by the user."""


class PlatformBlockedError(BrowserNotReadyError):
    """Raised when the target platform blocks the current automation mode."""
