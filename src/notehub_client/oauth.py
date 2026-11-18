"""Optional Notehub OAuth client-credentials token provider."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Mapping
from datetime import timedelta
from logging import getLogger
from typing import TYPE_CHECKING

from .constants import NOTEHUB_API_ORIGIN
from .errors import NotehubDependencyError, NotehubOAuthError
from .helpers import validate_bearer_token

if TYPE_CHECKING:
    from collections.abc import Iterator

TOKEN_URL = f"{NOTEHUB_API_ORIGIN}/oauth2/token"
LOGGER = getLogger(__name__)


class NotehubOAuthTokenProvider:
    """Fetch and renew Notehub project OAuth bearer tokens on demand.

    Concurrent requests share a token refresh. ``leeway`` causes renewal to
    begin before the token's reported expiration time. Supply it as seconds or
    a :class:`datetime.timedelta`.

    Invalid token responses raise ``NotehubOAuthError`` and are discarded, so
    a later call can attempt a new exchange. Failed calls are not retried
    automatically, and there is no background refresh task.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        leeway: int | timedelta = 60,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("client_id and client_secret must be nonempty")
        if isinstance(leeway, timedelta):
            leeway_seconds = leeway.total_seconds()
        elif type(leeway) is int:
            leeway_seconds = leeway
        else:
            raise ValueError("leeway must be nonnegative seconds or a timedelta")
        if leeway_seconds < 0:
            raise ValueError("leeway must be nonnegative seconds or a timedelta")
        try:
            from authlib.integrations.httpx_client import AsyncOAuth2Client
        except ModuleNotFoundError as error:
            if (error.name or "").partition(".")[0] != "authlib":
                raise
            raise NotehubDependencyError("OAuth client credentials", "oauth", "authlib") from error
        self._client = AsyncOAuth2Client(
            client_id,
            client_secret,
            # This selects OAuth client-secret transport; it is a protocol constant, not a credential.
            token_endpoint_auth_method="client_secret_post",  # noqa: S106  # nosec B106
        )
        self._leeway = leeway_seconds
        self._lock = asyncio.Lock()
        self._closed = False

    def __rich_repr__(self) -> Iterator[object]:
        yield "leeway_seconds", self._leeway, 60
        yield "closed", self._closed, False

    async def __aenter__(self) -> NotehubOAuthTokenProvider:
        if self._closed:
            raise RuntimeError("NotehubOAuthTokenProvider is closed")
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def __call__(self) -> str:
        """Return a valid bearer token, refreshing it when it nears expiration."""
        async with self._lock:
            if self._closed:
                raise RuntimeError("NotehubOAuthTokenProvider is closed")
            token: Mapping[str, object] | None = (
                self._client.token if isinstance(self._client.token, Mapping) else None
            )
            expiry = token.get("expires_at") if token is not None else None
            expires_at = (
                float(expiry) if isinstance(expiry, (int, float)) and math.isfinite(expiry) else 0.0
            )
            refreshed = False
            if token is None or expires_at <= time.time() + self._leeway:
                try:
                    fetched = await self._client.fetch_token(
                        TOKEN_URL, grant_type="client_credentials"
                    )
                except Exception as error:
                    # TODO(oauth-backoff): Design an opt-in failed-exchange
                    # cooldown for queued callers. Cover transient versus invalid
                    # credentials, cancellation, and recovery with a fake clock;
                    # never reuse a rejected token or expose server response data.
                    LOGGER.warning(
                        "Notehub OAuth token exchange failed: error_type=%r",
                        type(error).__name__,
                    )
                    raise NotehubOAuthError("Notehub OAuth token request failed") from None
                token = fetched if isinstance(fetched, Mapping) else None
                refreshed = True
            access_token = token.get("access_token") if token is not None else None
            if not isinstance(access_token, str) or not access_token:
                # Authlib caches fetched tokens before our bearer validation.
                # Rejecting one must permit the next caller to exchange again.
                self._client.token = None
                LOGGER.warning(
                    "Notehub OAuth token response invalid: reason=%r", "missing_access_token"
                )
                raise NotehubOAuthError("Notehub OAuth response did not contain an access token")
            try:
                validated_token = validate_bearer_token(access_token)
            except ValueError:
                self._client.token = None
                LOGGER.warning(
                    "Notehub OAuth token response invalid: reason=%r", "invalid_access_token"
                )
                raise NotehubOAuthError(
                    "Notehub OAuth response contained an invalid access token"
                ) from None
            if refreshed:
                LOGGER.info("Notehub OAuth token refreshed: leeway_seconds=%r", self._leeway)
            return validated_token

    async def aclose(self) -> None:
        """Close the OAuth HTTP client and prevent further token requests."""
        async with self._lock:
            if not self._closed:
                self._closed = True
                await self._client.aclose()
