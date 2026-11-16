"""Optional Notehub OAuth client-credentials token provider."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Mapping

from .constants import NOTEHUB_API_ORIGIN
from .errors import NotehubDependencyError, NotehubOAuthError
from .helpers import validate_bearer_token

TOKEN_URL = f"{NOTEHUB_API_ORIGIN}/oauth2/token"


class NotehubOAuthTokenProvider:
    """Fetch and renew Notehub project OAuth bearer tokens on demand.

    Concurrent requests share a token refresh. ``leeway`` causes renewal to
    begin before the token's reported expiration time.
    """

    def __init__(self, client_id: str, client_secret: str, *, leeway: int = 60) -> None:
        if not client_id or not client_secret:
            raise ValueError("client_id and client_secret must be nonempty")
        if type(leeway) is not int or leeway < 0:
            raise ValueError("leeway must be a nonnegative integer")
        try:
            from authlib.integrations.httpx_client import AsyncOAuth2Client
        except ModuleNotFoundError as error:
            if (error.name or "").partition(".")[0] != "authlib":
                raise
            raise NotehubDependencyError("OAuth client credentials", "oauth", "authlib") from error
        self._client = AsyncOAuth2Client(
            client_id, client_secret, token_endpoint_auth_method="client_secret_post"
        )
        self._leeway = leeway
        self._lock = asyncio.Lock()
        self._closed = False

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
            if token is None or expires_at <= time.time() + self._leeway:
                try:
                    fetched = await self._client.fetch_token(
                        TOKEN_URL, grant_type="client_credentials"
                    )
                except Exception:
                    raise NotehubOAuthError("Notehub OAuth token request failed") from None
                token = fetched if isinstance(fetched, Mapping) else None
            access_token = token.get("access_token") if token is not None else None
            if not isinstance(access_token, str) or not access_token:
                raise NotehubOAuthError("Notehub OAuth response did not contain an access token")
            try:
                return validate_bearer_token(access_token)
            except ValueError:
                raise NotehubOAuthError(
                    "Notehub OAuth response contained an invalid access token"
                ) from None

    async def aclose(self) -> None:
        """Close the OAuth HTTP client and prevent further token requests."""
        async with self._lock:
            if not self._closed:
                self._closed = True
                await self._client.aclose()
