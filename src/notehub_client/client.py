"""Async Notehub REST client."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import cast
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
from .types import Device, Event, JSONObject, JSONValue, QueryValue

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
        params: Mapping[str, QueryValue] | None = None,
        json: JSONValue = None,
        data: str | bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JSONValue:
        auth = await self._provider() if self._provider else self._token
        request_headers = {"Authorization": f"Bearer {auth}", **(headers or {})}
        url = path if path.startswith("https://") else f"{self._base_url}/v1/{path.lstrip('/')}"
        try:
            response = await self._http.request(
                method, url, params=params, json=json, content=data, headers=request_headers
            )
        except httpx.HTTPError as err:
            raise NotehubTransportError(f"Notehub request failed: {err}") from err
        if response.status_code == 204 or not response.content:
            payload = None
        else:
            try:
                payload = cast(JSONValue, response.json())
            except ValueError:
                payload = response.text
        if response.is_error:
            error = {
                401: NotehubAuthenticationError,
                403: NotehubPermissionError,
                429: NotehubRateLimitError,
            }.get(response.status_code, NotehubAPIError)
            message = (
                str(payload.get("message", payload)) if isinstance(payload, dict) else str(payload)
            )
            raise error(
                response.status_code,
                message,
                payload=payload,
                retry_after=response.headers.get("Retry-After"),
            )
        return payload

    async def _pages(
        self, path: str, *, params: dict[str, QueryValue] | None = None
    ) -> AsyncIterator[JSONObject]:
        query = {"pageSize": 100, "pageNum": 1, **(params or {})}
        while True:
            page = _object(await self.request("GET", path, params=query), "paginated")
            if not isinstance(page, dict):
                raise NotehubAPIError(
                    200, "Expected a JSON object for a paginated response", payload=page
                )
            yield page
            if not page.get("has_more"):
                return
            page_num = query.get("pageNum", 1)
            query["pageNum"] = page_num + 1 if isinstance(page_num, int) else 2

    async def iter_devices(self, project_uid: str) -> AsyncIterator[Device]:
        async for page in self._pages(f"projects/{_q(project_uid)}/devices"):
            for device in _object_list(page.get("devices"), "devices"):
                if not isinstance(device, dict):
                    continue
                yield cast(Device, device)

    async def get_devices(self, project_uid: str) -> list[Device]:
        return [item async for item in self.iter_devices(project_uid)]

    async def get_project_events(
        self, project_uid: str, *, cursor: str | None = None, **filters: QueryValue
    ) -> JSONObject:
        params = {"pageSize": 100, **filters}
        if cursor is not None:
            params["cursor"] = cursor
        payload = await self.request("GET", f"projects/{_q(project_uid)}/events", params=params)
        if not isinstance(payload, dict):
            raise NotehubAPIError(
                200, "Expected an object from the events endpoint", payload=payload
            )
        return payload

    async def iter_project_events(
        self, project_uid: str, *, cursor: str = "0", **filters: QueryValue
    ) -> AsyncIterator[Event]:
        while True:
            page = await self.get_project_events(project_uid, cursor=cursor, **filters)
            for event in _object_list(page.get("events"), "events"):
                if not isinstance(event, dict):
                    continue
                yield cast(Event, event)
            next_cursor = page.get("next_cursor")
            if not page.get("has_more"):
                return
            if not next_cursor or str(next_cursor) == str(cursor):
                raise NotehubAPIError(
                    200, "Event pagination cursor missing or did not advance", payload=page
                )
            cursor = str(next_cursor)

    async def get_project(self, project_uid: str) -> JSONObject:
        return _object(await self.request("GET", f"projects/{_q(project_uid)}"), "project")

    async def get_projects(self, **params: QueryValue) -> JSONObject:
        return _object(await self.request("GET", "projects", params=params), "projects")

    async def add_qi_note(
        self, project_uid: str, device_uid: str, notefile: str, body: JSONObject
    ) -> JSONValue:
        return await self.request(
            "POST", f"{_device(project_uid, device_uid)}/notes/{_q(notefile)}", json={"body": body}
        )

    async def add_db_note(
        self, project_uid: str, device_uid: str, notefile: str, note_id: str, body: JSONObject
    ) -> JSONValue:
        return await self.request(
            "POST",
            f"{_device(project_uid, device_uid)}/notes/{_q(notefile)}/{_q(note_id)}",
            json={"body": body},
        )

    async def update_db_note(
        self, project_uid: str, device_uid: str, notefile: str, note_id: str, body: JSONObject
    ) -> JSONValue:
        return await self.request(
            "PUT",
            f"{_device(project_uid, device_uid)}/notes/{_q(notefile)}/{_q(note_id)}",
            json={"body": body},
        )

    async def delete_note(
        self, project_uid: str, device_uid: str, notefile: str, note_id: str
    ) -> JSONValue:
        return await self.request(
            "DELETE", f"{_device(project_uid, device_uid)}/notes/{_q(notefile)}/{_q(note_id)}"
        )

    async def set_environment_variables(
        self, project_uid: str, device_uid: str, values: dict[str, str]
    ) -> JSONValue:
        return await self.request(
            "PUT",
            f"{_device(project_uid, device_uid)}/environment_variables",
            json={"environment_variables": cast(JSONValue, values)},
        )

    async def delete_environment_variable(
        self, project_uid: str, device_uid: str, key: str
    ) -> JSONValue:
        return await self.request(
            "DELETE", f"{_device(project_uid, device_uid)}/environment_variables/{_q(key)}"
        )


def _q(value: str) -> str:
    return quote(value, safe=":.#")


def _device(project: str, device: str) -> str:
    return f"projects/{_q(project)}/devices/{_q(device)}"


def _object(payload: JSONValue, endpoint: str) -> JSONObject:
    if not isinstance(payload, dict):
        raise NotehubAPIError(
            200, f"Expected a JSON object from the {endpoint} endpoint", payload=payload
        )
    return payload


def _object_list(payload: JSONValue, field: str) -> list[JSONObject]:
    if not isinstance(payload, list):
        raise NotehubAPIError(
            200, f"Expected a list in the {field} response field", payload=payload
        )
    return [item for item in payload if isinstance(item, dict)]
