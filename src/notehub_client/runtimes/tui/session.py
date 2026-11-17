"""Credential resolution and ownership for terminal client sessions."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from ...client import NotehubClient
from ...helpers import RequestPacer, validate_bearer_token

if TYPE_CHECKING:
    from ...typing.observe import Observer
    from .state import TUIOptions


class SessionController:
    """Own production clients and borrow injected clients without closing them."""

    def __init__(
        self,
        options: TUIOptions | None = None,
        *,
        client: NotehubClient | None = None,
        observer: Observer | None = None,
    ) -> None:
        self.options = options
        self.client = client
        self.owns_client = False
        self.observer = observer

    def token(self) -> str | None:
        """Resolve credentials without disclosing contents in errors."""
        if self.options is not None and self.options.demo:
            return None
        source = self.options.token_file if self.options is not None else None
        if source is not None:
            try:
                value = source.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                raise ValueError("Could not read token file") from None
            if not value:
                raise ValueError("Token file is empty")
        else:
            value = (os.getenv("NOTEHUB_TOKEN") or "").strip()
        if not value:
            return None
        try:
            return validate_bearer_token(value)
        except ValueError:
            raise ValueError("Invalid bearer token") from None

    def connect(self, token: str | None = None) -> NotehubClient:
        """Return an existing client or create a paced production client."""
        if self.client is not None:
            return self.client
        if self.options is not None and self.options.demo:
            raise ValueError("Demo sessions use the local demo service")
        credential = token if token is not None else self.token()
        if not credential:
            raise ValueError("Provide a bearer token to connect")
        try:
            credential = validate_bearer_token(credential.strip())
        except ValueError:
            raise ValueError("Invalid bearer token") from None
        self.client = NotehubClient(credential, pacer=RequestPacer(), observer=self.observer)
        self.owns_client = True
        return self.client

    async def disconnect(self) -> None:
        """Close an owned client once and detach any borrowed client."""
        client, owned = self.client, self.owns_client
        self.client = None
        self.owns_client = False
        if client is not None and owned:
            await client.aclose()


__all__ = ["SessionController"]
