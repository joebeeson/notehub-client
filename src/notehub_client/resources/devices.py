"""Stateless Notehub domain facades sharing the owning client's transport."""

from __future__ import annotations

import builtins
from logging import getLogger
from typing import TYPE_CHECKING, cast

from ..errors import NotehubResponseError
from ..filters import Pagination, merge_query_params
from ..helpers import (
    encode_path_segments,
    require_collection,
    require_device_collection,
    require_json_object,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from ..typing import (
        Device,
        DevicesResponse,
        GetDeviceEnvironmentVariablesResponse,
        JSONObject,
        JSONValue,
        LatestResponse,
        QueryFilter,
        QueryValue,
        SessionResponse,
    )
    from .base import RequestClient

LOGGER = getLogger(__name__)


class DevicesFacade:
    """Read and manage devices within Notehub projects and fleets."""

    def __init__(self, client: RequestClient) -> None:
        self._client = client

    async def list(
        self,
        project_uid: str,
        *,
        filters: QueryFilter | None = None,
        pagination: Pagination | None = None,
    ) -> DevicesResponse:
        """Fetch one page of devices in a project."""
        page = pagination or Pagination()
        query = merge_query_params(filters, page.to_query_params())
        payload = await self._client.request(
            "GET", encode_path_segments("projects", project_uid, "devices"), params=query
        )
        return cast("DevicesResponse", require_device_collection(payload))

    async def iter(
        self,
        project_uid: str,
        *,
        filters: QueryFilter | None = None,
        pagination: Pagination | None = None,
    ) -> AsyncIterator[Device]:
        """Yield project devices page by page until the collection is exhausted."""
        page_size = (pagination or Pagination()).page_size
        page_num = (pagination or Pagination()).page_num or 1
        while True:
            page = await self.list(
                project_uid,
                filters=filters,
                pagination=Pagination(page_size=page_size, page_num=page_num),
            )
            for device in page["devices"]:
                yield device
            if not page["has_more"]:
                return
            if not page["devices"]:
                raise NotehubResponseError("Empty device page claims more results")
            page_num += 1

    async def collect(
        self,
        project_uid: str,
        *,
        filters: QueryFilter | None = None,
        pagination: Pagination | None = None,
    ) -> builtins.list[Device]:
        """Collect all devices; use iter() for large inventories."""
        return [
            item async for item in self.iter(project_uid, filters=filters, pagination=pagination)
        ]

    async def get(
        self,
        project_uid: str,
        device_uid: str,
        *,
        filters: QueryFilter | None = None,
        **params: QueryValue,
    ) -> Device:
        """Fetch a device by its project and device UIDs."""
        payload = await self._client.request(
            "GET",
            encode_path_segments("projects", project_uid, "devices", device_uid),
            params=merge_query_params(filters, params),
        )
        device = require_json_object(payload, "get_device")
        if not isinstance(device.get("uid"), str):
            raise NotehubResponseError("Device is missing a string uid")
        return cast("Device", device)

    async def list_sessions(
        self,
        project_uid: str,
        device_uid: str,
        *,
        filters: QueryFilter | None = None,
        **params: QueryValue,
    ) -> SessionResponse:
        """List sessions recorded for a device."""
        payload = await self._client.request(
            "GET",
            encode_path_segments("projects", project_uid, "devices", device_uid, "sessions"),
            params=merge_query_params(filters, params),
        )
        return cast("SessionResponse", require_collection(payload, "sessions", paginated=True))

    async def latest(
        self,
        project_uid: str,
        device_uid: str,
        *,
        filters: QueryFilter | None = None,
        **params: QueryValue,
    ) -> LatestResponse:
        """Fetch the latest event records for a device."""
        payload = await self._client.request(
            "GET",
            encode_path_segments("projects", project_uid, "devices", device_uid, "latest"),
            params=merge_query_params(filters, params),
        )
        return cast(
            "LatestResponse",
            require_collection(payload, "latest_events", paginated=False, optional=True),
        )

    async def get_environment(
        self,
        project_uid: str,
        device_uid: str,
        *,
        filters: QueryFilter | None = None,
        **params: QueryValue,
    ) -> GetDeviceEnvironmentVariablesResponse:
        """Read the device's configured and effective environment variables."""
        payload = await self._client.request(
            "GET",
            encode_path_segments(
                "projects", project_uid, "devices", device_uid, "environment_variables"
            ),
            params=merge_query_params(filters, params),
        )
        return cast(
            "GetDeviceEnvironmentVariablesResponse",
            require_json_object(payload, "get_device_environment"),
        )

    async def set_environment(
        self, project_uid: str, device_uid: str, values: Mapping[str, str]
    ) -> JSONValue:
        """Set environment-variable values on a device."""
        variables: JSONObject = {k: v for k, v in values.items()}
        result = await self._client.request(
            "PUT",
            encode_path_segments(
                "projects", project_uid, "devices", device_uid, "environment_variables"
            ),
            json={"environment_variables": variables},
        )
        LOGGER.info(
            "Device environment updated: project_uid=%r device_uid=%r value_count=%r",
            project_uid,
            device_uid,
            len(values),
        )
        return result

    async def delete_environment_variable(
        self, project_uid: str, device_uid: str, key: str
    ) -> JSONValue:
        """Remove one environment-variable override from a device."""
        result = await self._client.request(
            "DELETE",
            encode_path_segments(
                "projects", project_uid, "devices", device_uid, "environment_variables", key
            ),
        )
        LOGGER.info(
            "Device environment variable removed: project_uid=%r device_uid=%r variable_name=%r",
            project_uid,
            device_uid,
            key,
        )
        return result

    async def list_for_fleet(
        self,
        project_uid: str,
        fleet_uid: str,
        *,
        filters: QueryFilter | None = None,
        **params: QueryValue,
    ) -> DevicesResponse:
        """Fetch devices assigned to a fleet within a project."""
        payload = await self._client.request(
            "GET",
            encode_path_segments("projects", project_uid, "fleets", fleet_uid, "devices"),
            params=merge_query_params(filters, params),
        )
        return cast("DevicesResponse", require_device_collection(payload))
