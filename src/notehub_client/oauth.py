"""Optional Notehub OAuth client-credentials token provider."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from authlib.integrations.httpx_client import AsyncOAuth2Client

TOKEN_URL = "https://api.notefile.net/oauth2/token"


class NotehubOAuthTokenProvider:
    """Fetch and renew Notehub project OAuth bearer tokens on demand."""

    def __init__(self, client_id: str, client_secret: str, *, leeway: int = 60) -> None:
        self._client = AsyncOAuth2Client(
            client_id, client_secret, token_endpoint_auth_method="client_secret_post"
        )
        self._leeway = leeway
        self._lock = asyncio.Lock()

    async def __call__(self) -> str:
        async with self._lock:
            token: dict[str, Any] | None = self._client.token
            if not token or float(token.get("expires_at", 0)) <= time.time() + self._leeway:
                self._client.token = await self._client.fetch_token(
                    TOKEN_URL, grant_type="client_credentials"
                )
            return self._client.token["access_token"]

    async def aclose(self) -> None:
        await self._client.aclose()
