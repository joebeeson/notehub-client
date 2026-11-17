"""Stateless Notehub domain facades sharing the owning client's transport."""

from __future__ import annotations

import builtins
from contextlib import asynccontextmanager
from dataclasses import dataclass
from logging import getLogger
from typing import TYPE_CHECKING, cast

from ..compose import (
    Composer,
    DeviceTarget,
    resolve_environment,
    resolve_identifier,
    resolve_target,
)
from ..errors import NotehubResponseError
from ..filters import Pagination, merge_query_params
from ..helpers import (
    encode_path_segments,
    require_collection,
    require_device_collection,
    require_json_object,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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
_MISSING = object()


class DevicesFacade:
    """Read and manage devices within Notehub projects and fleets."""

    def __init__(self, client: RequestClient, *, composer: Composer | None = None) -> None:
        self._client = client
        self._composer = composer if composer is not None else Composer().copy(frozen=True)

    def __getitem__(self, key: tuple[str, str]) -> DeviceHandle:
        """Bind a project and device UID without making an API request."""
        if not isinstance(key, tuple) or len(key) != 2:
            raise TypeError("device lookup requires a (project_uid, device_uid) pair")
        project_uid, device_uid = key
        return DeviceHandle(
            DeviceTarget(
                resolve_identifier(project_uid, "project_uid", composer=self._composer),
                resolve_identifier(device_uid, "device_uid", composer=self._composer),
            ),
            self,
        )

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
        project_uid: object = _MISSING,
        device_uid: object = _MISSING,
        *,
        target: object = _MISSING,
        filters: QueryFilter | None = None,
        **params: QueryValue,
    ) -> GetDeviceEnvironmentVariablesResponse:
        """Read environment variables using identifiers or a device target."""
        device_target = _device_target(
            project_uid, device_uid, target=target, composer=self._composer
        )
        payload = await self._client.request(
            "GET",
            encode_path_segments(
                "projects",
                device_target.project_uid,
                "devices",
                device_target.device_uid,
                "environment_variables",
            ),
            params=merge_query_params(filters, params),
        )
        return cast(
            "GetDeviceEnvironmentVariablesResponse",
            require_json_object(payload, "get_device_environment"),
        )

    async def set_environment(
        self,
        project_uid: object = _MISSING,
        device_uid: object = _MISSING,
        values: object = _MISSING,
        *,
        target: object = _MISSING,
    ) -> JSONValue:
        """Set environment-variable values using identifiers or a device target."""
        if values is _MISSING and target is _MISSING and device_uid is not _MISSING:
            # Additive shorthand: set_environment(target, values).
            values = device_uid
            device_uid = _MISSING
        if values is _MISSING:
            raise TypeError("environment values are required")
        device_target = _device_target(
            project_uid, device_uid, target=target, composer=self._composer
        )
        variables: JSONObject = cast(
            "JSONObject", resolve_environment(values, composer=self._composer)
        )
        result = await self._client.request(
            "PUT",
            encode_path_segments(
                "projects",
                device_target.project_uid,
                "devices",
                device_target.device_uid,
                "environment_variables",
            ),
            json={"environment_variables": variables},
        )
        LOGGER.info(
            "Device environment updated: project_uid=%r device_uid=%r value_count=%r",
            device_target.project_uid,
            device_target.device_uid,
            len(variables),
        )
        return result

    async def delete_environment_variable(
        self,
        project_uid: object = _MISSING,
        device_uid: object = _MISSING,
        key: object = _MISSING,
        *,
        target: object = _MISSING,
    ) -> JSONValue:
        """Remove an environment variable using identifiers or a device target."""
        if key is _MISSING and target is _MISSING and device_uid is not _MISSING:
            # Additive shorthand: delete_environment_variable(target, key).
            key = device_uid
            device_uid = _MISSING
        if key is _MISSING:
            raise TypeError("environment variable key is required")
        device_target = _device_target(
            project_uid, device_uid, target=target, composer=self._composer
        )
        variable_name = resolve_identifier(
            key, "environment variable name", composer=self._composer
        )
        result = await self._client.request(
            "DELETE",
            encode_path_segments(
                "projects",
                device_target.project_uid,
                "devices",
                device_target.device_uid,
                "environment_variables",
                variable_name,
            ),
        )
        LOGGER.info(
            "Device environment variable removed: project_uid=%r device_uid=%r variable_name=%r",
            device_target.project_uid,
            device_target.device_uid,
            variable_name,
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


@dataclass(frozen=True, slots=True)
class DeviceHandle:
    """A device address bound to a client's device operations."""

    target: DeviceTarget
    _devices: DevicesFacade

    @property
    def project_uid(self) -> str:
        return self.target.project_uid

    @property
    def device_uid(self) -> str:
        return self.target.device_uid

    @property
    def environment(self) -> DeviceEnvironment:
        return DeviceEnvironment(self)

    def to_notehub_target(self) -> DeviceTarget:
        return self.target

    async def get(self) -> Device:
        return await self._devices.get(self.project_uid, self.device_uid)


@dataclass(frozen=True, slots=True)
class DeviceEnvironment:
    """Read and edit the device-level environment variable mapping."""

    _device: DeviceHandle

    async def read(self) -> dict[str, str]:
        response = await self._device._devices.get_environment(target=self._device)
        values = response.get("environment_variables", {})
        return dict(values)

    @asynccontextmanager
    async def edit(self):
        original = await self.read()
        values = dict(original)
        yield values
        changed = {key: value for key, value in values.items() if original.get(key) != value}
        removed = sorted(original.keys() - values.keys())
        # Validate all supplied values before issuing any write.
        normalized = resolve_environment(changed, composer=self._device._devices._composer)
        if normalized:
            await self._device._devices.set_environment(target=self._device, values=normalized)
        for key in removed:
            await self._device._devices.delete_environment_variable(target=self._device, key=key)


def _device_target(
    project_uid: object,
    device_uid: object,
    *,
    target: object,
    composer: Composer,
) -> DeviceTarget:
    if target is not _MISSING:
        if project_uid is not _MISSING or device_uid is not _MISSING:
            raise TypeError("provide either target or explicit device identifiers")
        resolved = resolve_target(target, composer=composer)
    elif device_uid is _MISSING:
        if project_uid is _MISSING:
            raise TypeError("a device target or project and device identifiers are required")
        resolved = resolve_target(project_uid, composer=composer)
    else:
        if project_uid is _MISSING:
            raise TypeError("project_uid is required")
        resolved = DeviceTarget(
            resolve_identifier(project_uid, "project_uid", composer=composer),
            resolve_identifier(device_uid, "device_uid", composer=composer),
        )
    if not isinstance(resolved, DeviceTarget):
        raise TypeError("device operations require a DeviceTarget")
    return resolved
