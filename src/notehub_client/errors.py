"""Public error types."""

from __future__ import annotations


class NotehubError(Exception):
    """Base error for Notehub client failures."""


class NotehubTransportError(NotehubError):
    """Network or timeout failure."""


class NotehubAPIError(NotehubError):
    """Non-success response from Notehub."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        retry_after: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class NotehubAuthenticationError(NotehubAPIError):
    """Authentication rejected (HTTP 401)."""


class NotehubPermissionError(NotehubAPIError):
    """Permission rejected (HTTP 403)."""


class NotehubRateLimitError(NotehubAPIError):
    """Rate limit reached (HTTP 429)."""


class NotehubResponseError(NotehubError):
    """The server returned a malformed or incompatible response."""


class NotehubOAuthError(NotehubError):
    """OAuth token exchange failed; messages never include raw server responses."""


class NotehubDependencyError(ImportError):
    """An optional Notehub feature cannot load a declared dependency."""

    def __init__(self, feature: str, extra: str, missing_module: str) -> None:
        self.feature = feature
        self.extra = extra
        self.missing_module = missing_module
        super().__init__(
            f"The {feature!r} feature needs {missing_module!r}. "
            f"Install it with `pip install 'notehub-client[{extra}]'`."
        )
