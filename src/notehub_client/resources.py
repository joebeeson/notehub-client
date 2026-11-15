"""Named operations for Notehub API areas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .types import JSONValue, QueryValue

if TYPE_CHECKING:
    from .client import NotehubClient


class NotehubResources:
    """Operations grouped outside the project's primary device and event flow."""

    def __init__(self, client: NotehubClient) -> None:
        self._client = client

    async def list_organizations(self, **params: QueryValue) -> JSONValue:
        return await self._client.request("GET", "organizations", params=params)

    async def list_fleets(self, project_uid: str, **params: QueryValue) -> JSONValue:
        return await self._client.request("GET", f"projects/{project_uid}/fleets", params=params)

    async def get_fleet_devices(
        self, project_uid: str, fleet_uid: str, **params: QueryValue
    ) -> JSONValue:
        return await self._client.request(
            "GET", f"projects/{project_uid}/fleets/{fleet_uid}/devices", params=params
        )

    async def get_fleet_events(
        self, project_uid: str, fleet_uid: str, **params: QueryValue
    ) -> JSONValue:
        return await self._client.request(
            "GET", f"projects/{project_uid}/fleets/{fleet_uid}/events", params=params
        )

    async def get_device(self, project_uid: str, device_uid: str) -> JSONValue:
        return await self._client.request("GET", f"projects/{project_uid}/devices/{device_uid}")

    async def get_device_sessions(
        self, project_uid: str, device_uid: str, **params: QueryValue
    ) -> JSONValue:
        return await self._client.request(
            "GET", f"projects/{project_uid}/devices/{device_uid}/sessions", params=params
        )

    async def get_device_latest(self, project_uid: str, device_uid: str) -> JSONValue:
        return await self._client.request(
            "GET", f"projects/{project_uid}/devices/{device_uid}/latest"
        )

    async def get_device_environment(self, project_uid: str, device_uid: str) -> JSONValue:
        return await self._client.request(
            "GET", f"projects/{project_uid}/devices/{device_uid}/environment_variables"
        )

    async def list_routes(self, project_uid: str, **params: QueryValue) -> JSONValue:
        return await self._client.request("GET", f"projects/{project_uid}/routes", params=params)

    async def list_jobs(self, project_uid: str, **params: QueryValue) -> JSONValue:
        return await self._client.request("GET", f"projects/{project_uid}/jobs", params=params)

    async def list_monitors(self, project_uid: str, **params: QueryValue) -> JSONValue:
        return await self._client.request("GET", f"projects/{project_uid}/monitors", params=params)

    async def get_usage(self, project_uid: str, **params: QueryValue) -> JSONValue:
        return await self._client.request("GET", f"projects/{project_uid}/usage", params=params)
