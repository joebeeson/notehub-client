"""Public error types."""

from typing import Any


class NotehubError(Exception):
    """Base error for Notehub client failures."""


class NotehubTransportError(NotehubError):
    """Network or timeout failure."""


class NotehubAPIError(NotehubError):
    """Non-success response from Notehub."""

    def __init__(
        self, status_code: int, message: str, *, payload: Any = None, retry_after: str | None = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload
        self.retry_after = retry_after


class NotehubAuthenticationError(NotehubAPIError):
    """Authentication rejected (HTTP 401)."""


class NotehubPermissionError(NotehubAPIError):
    """Permission rejected (HTTP 403)."""


class NotehubRateLimitError(NotehubAPIError):
    """Rate limit reached (HTTP 429)."""
