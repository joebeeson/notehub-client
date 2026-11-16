"""Async Notehub transport and client lifecycle."""

from __future__ import annotations

# TODO: Is this module and class getting a bit big for its britches?

import math
from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import unquote

import httpx

from .constants import DEFAULT_TIMEOUT, NOTEHUB_API_ORIGIN
from .errors import (
    NotehubAPIError,
    NotehubAuthenticationError,
    NotehubPermissionError,
    NotehubRateLimitError,
    NotehubResponseError,
    NotehubTransportError,
)
from .helpers import validate_bearer_token, validate_json_value
from .resources import (
    BillingAccountsFacade,
    DevicesFacade,
    EventsFacade,
    FleetsFacade,
    JobsFacade,
    MonitorsFacade,
    NotesFacade,
    OrganizationsFacade,
    ProjectsFacade,
    RoutesFacade,
    UsageFacade,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from .typing import JSONValue, QueryValue

    TokenProvider = Callable[[], Awaitable[str]]

BASE_URL = NOTEHUB_API_ORIGIN


class NotehubClient:
    """Own the HTTP transport and expose Notehub domain operation facades.

    Pass either a static bearer token or an async token provider. The client
    closes HTTP clients it creates itself; an injected ``http_client`` remains
    owned by the caller.
    """

    projects: ProjectsFacade
    devices: DevicesFacade
    events: EventsFacade
    fleets: FleetsFacade
    organizations: OrganizationsFacade
    billing_accounts: BillingAccountsFacade
    notes: NotesFacade
    routes: RoutesFacade
    jobs: JobsFacade
    monitors: MonitorsFacade
    usage: UsageFacade

    # TODO: Should we check/fallback to like `environ["NOTEHUB_TOKEN"]` if it exists?
    # TODO: I wonder if configuration is getting large enough to warrant its own handling.
    def __init__(
        self,
        token: str | None = None,
        *,
        token_provider: TokenProvider | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        base_url: str = BASE_URL,
    ) -> None:
        if (token is None) == (token_provider is None):
            raise ValueError("Provide exactly one token or token_provider")
        if token_provider is not None and not callable(token_provider):
            raise ValueError("token_provider must be an async callable")
        if token is not None:
            token = validate_bearer_token(token)
        if type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be a nonnegative number")
        base = httpx.URL(base_url)
        if (
            base.scheme not in {"http", "https"}
            or not base.host
            or base.userinfo
            or base.path not in {"", "/"}
            or base.query
            or base.fragment
        ):
            raise ValueError("base_url must be an HTTP(S) origin without credentials or query")
        self._token = token
        self._provider = token_provider
        self._owns_http = http_client is None
        self._http = http_client if http_client is not None else httpx.AsyncClient(timeout=timeout)
        self._base_url = str(base).rstrip("/")
        self._closed = False
        self.projects = ProjectsFacade(self)
        self.devices = DevicesFacade(self)
        self.events = EventsFacade(self)
        self.fleets = FleetsFacade(self)
        self.organizations = OrganizationsFacade(self)
        self.billing_accounts = BillingAccountsFacade(self)
        self.notes = NotesFacade(self)
        self.routes = RoutesFacade(self)
        self.jobs = JobsFacade(self)
        self.monitors = MonitorsFacade(self)
        self.usage = UsageFacade(self)

    async def __aenter__(self) -> NotehubClient:
        if self._closed:
            raise RuntimeError("NotehubClient is closed")
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the client and its HTTP transport when the client owns it."""
        self._closed = True
        if self._owns_http:
            await self._http.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, QueryValue] | None = None,
        json: JSONValue = None,
        data: str | bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JSONValue:
        """Request a relative /v1/ endpoint; return JSON or None for an empty response.

        No retries or redirects are performed. API response bodies are not used in
        exception messages because they can echo credentials or application data.
        """
        if self._closed:
            raise RuntimeError("NotehubClient is closed")
        if (
            not path
            or path.startswith("/")
            or "://" in path
            or "#" in path
            or "?" in path
            or "\\" in path
            or any(unquote(part) in {".", ".."} for part in path.split("/"))
        ):
            raise ValueError("path must be relative to /v1/; use params for query values")
        if json is not None and data is not None:
            raise ValueError("json and data are mutually exclusive")
        auth = await self._provider() if self._provider else self._token
        auth = validate_bearer_token(auth)
        request_headers = dict(headers or {})
        if any(k.lower() == "authorization" for k in request_headers):
            raise ValueError("Authentication is controlled by token or token_provider")
        request_headers["Authorization"] = f"Bearer {auth}"
        try:
            response = await self._http.request(
                method,
                f"{self._base_url}/v1/{path}",
                params=params,
                json=json,
                content=data,
                headers=request_headers,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise NotehubTransportError("Notehub transport failed") from None
        if not 200 <= response.status_code < 300:
            error_types: dict[int, type[NotehubAPIError]] = {
                HTTPStatus.UNAUTHORIZED.value: NotehubAuthenticationError,
                HTTPStatus.FORBIDDEN.value: NotehubPermissionError,
                HTTPStatus.TOO_MANY_REQUESTS.value: NotehubRateLimitError,
            }
            error = error_types.get(response.status_code, NotehubAPIError)
            raise error(
                response.status_code,
                f"Notehub returned HTTP {response.status_code}",
                retry_after=response.headers.get("Retry-After"),
            )
        if response.status_code == 204 or not response.content:
            return None
        try:
            return validate_json_value(response.json())
        except ValueError:
            raise NotehubResponseError("Notehub returned invalid JSON") from None
