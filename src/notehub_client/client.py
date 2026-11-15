"""Async Notehub REST client."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import quote

import httpx

from .errors import (
    NotehubAPIError,
    NotehubAuthenticationError,
    NotehubPermissionError,
    NotehubRateLimitError,
    NotehubTransportError,
)
from .resources import NotehubResources

TokenProvider = Callable[[], Awaitable[str]]
BASE_URL = "https://api.notefile.net"


class NotehubClient:
    """Async Notehub client. A supplied HTTPX client remains caller-owned."""

    def __init__(
        self,
        token: str | None = None,
        *,
        token_provider: TokenProvider | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
        base_url: str = BASE_URL,
    ):
        if not token and token_provider is None:
            raise ValueError("Provide a personal access token or async token_provider")
        self._token = token
        self._provider = token_provider
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._base_url = base_url.rstrip("/")
        self.resources = NotehubResources(self)

    async def __aenter__(self) -> NotehubClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        auth = await self._provider() if self._provider else self._token
        request_headers = {"Authorization": f"Bearer {auth}", **(headers or {})}
        url = path if path.startswith("https://") else f"{self._base_url}/v1/{path.lstrip('/')}"
        try:
            response = await self._http.request(
                method, url, params=params, json=json, data=data, headers=request_headers
            )
        except httpx.HTTPError as err:
            raise NotehubTransportError(f"Notehub request failed: {err}") from err
        if response.status_code == 204 or not response.content:
            payload = None
        else:
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
        if response.is_error:
            error = {
                401: NotehubAuthenticationError,
                403: NotehubPermissionError,
                429: NotehubRateLimitError,
            }.get(response.status_code, NotehubAPIError)
            message = (
                payload.get("message", str(payload)) if isinstance(payload, dict) else str(payload)
            )
            raise error(
                response.status_code,
                message,
                payload=payload,
                retry_after=response.headers.get("Retry-After"),
            )
        return payload

    async def _pages(
        self, path: str, key: str, *, params: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        query = {"pageSize": 100, "pageNum": 1, **(params or {})}
        while True:
            page = await self.request("GET", path, params=query)
            yield page
            if not page.get("has_more"):
                return
            query["pageNum"] += 1

    async def iter_devices(self, project_uid: str) -> AsyncIterator[dict[str, Any]]:
        async for page in self._pages(f"projects/{_q(project_uid)}/devices", "devices"):
            for device in page.get("devices", []):
                yield device

    async def get_devices(self, project_uid: str) -> list[dict[str, Any]]:
        return [item async for item in self.iter_devices(project_uid)]

    async def get_project_events(
        self, project_uid: str, *, cursor: str | None = None, **filters: Any
    ) -> dict[str, Any]:
        params = {"pageSize": 100, **filters}
        if cursor is not None:
            params["cursor"] = cursor
        return await self.request("GET", f"projects/{_q(project_uid)}/events", params=params)

    async def iter_project_events(
        self, project_uid: str, *, cursor: str = "0", **filters: Any
    ) -> AsyncIterator[dict[str, Any]]:
        while True:
            page = await self.get_project_events(project_uid, cursor=cursor, **filters)
            for event in page.get("events", []):
                yield event
            next_cursor = page.get("next_cursor")
            if not page.get("has_more"):
                return
            if not next_cursor or str(next_cursor) == str(cursor):
                raise NotehubAPIError(
                    200, "Event pagination cursor missing or did not advance", payload=page
                )
            cursor = str(next_cursor)

    async def get_project(self, project_uid: str) -> dict[str, Any]:
        return await self.request("GET", f"projects/{_q(project_uid)}")

    async def get_projects(self, **params: Any) -> dict[str, Any]:
        return await self.request("GET", "projects", params=params)

    async def add_qi_note(
        self, project_uid: str, device_uid: str, notefile: str, body: dict[str, Any]
    ) -> Any:
        return await self.request(
            "POST", f"{_device(project_uid, device_uid)}/notes/{_q(notefile)}", json={"body": body}
        )

    async def add_db_note(
        self, project_uid: str, device_uid: str, notefile: str, note_id: str, body: dict[str, Any]
    ) -> Any:
        return await self.request(
            "POST",
            f"{_device(project_uid, device_uid)}/notes/{_q(notefile)}/{_q(note_id)}",
            json={"body": body},
        )

    async def update_db_note(
        self, project_uid: str, device_uid: str, notefile: str, note_id: str, body: dict[str, Any]
    ) -> Any:
        return await self.request(
            "PUT",
            f"{_device(project_uid, device_uid)}/notes/{_q(notefile)}/{_q(note_id)}",
            json={"body": body},
        )

    async def delete_note(
        self, project_uid: str, device_uid: str, notefile: str, note_id: str
    ) -> Any:
        return await self.request(
            "DELETE", f"{_device(project_uid, device_uid)}/notes/{_q(notefile)}/{_q(note_id)}"
        )

    async def set_environment_variables(
        self, project_uid: str, device_uid: str, values: dict[str, str]
    ) -> Any:
        return await self.request(
            "PUT",
            f"{_device(project_uid, device_uid)}/environment_variables",
            json={"environment_variables": values},
        )

    async def delete_environment_variable(self, project_uid: str, device_uid: str, key: str) -> Any:
        return await self.request(
            "DELETE", f"{_device(project_uid, device_uid)}/environment_variables/{_q(key)}"
        )


def _q(value: str) -> str:
    return quote(value, safe=":.#")


def _device(project: str, device: str) -> str:
    return f"projects/{_q(project)}/devices/{_q(device)}"

