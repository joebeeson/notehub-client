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
from ._pagination import iter_cursor_pages

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

    from ..filters import CursorPagination
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
        return cast("Device", require_json_object(payload, "get_device", require_uid=True))

    async def list_sessions(
        self,
        project_uid: str,
        device_uid: str,
        *,
        filters: QueryFilter | None = None,
        pagination: Pagination | CursorPagination | None = None,
        **params: QueryValue,
    ) -> SessionResponse:
        """Fetch one numbered or cursor page of sessions recorded for a device."""
        query = merge_query_params(filters, params)
        if pagination is not None:
            query = merge_query_params(query, pagination.to_query_params())
        return await self._list_sessions_page(project_uid, device_uid, query)

    async def _list_sessions_page(
        self, project_uid: str, device_uid: str, query: dict[str, QueryValue]
    ) -> SessionResponse:
        if "cursor" in query and "pageNum" in query:
            raise ValueError("cursor cannot be combined with pageNum")
        payload = await self._client.request(
            "GET",
            encode_path_segments("projects", project_uid, "devices", device_uid, "sessions"),
            params=query,
        )
        return cast("SessionResponse", require_collection(payload, "sessions", paginated=True))

    async def iter_session_pages(
        self,
        project_uid: str,
        device_uid: str,
        *,
        filters: QueryFilter | None = None,
        pagination: CursorPagination | None = None,
        **params: QueryValue,
    ) -> AsyncIterator[SessionResponse]:
        """Follow session changes in cursor order, yielding whole pages for checkpointing.

        Save a nonempty ``next_cursor`` after processing the whole page, even
        when it is empty or terminal. A session can reappear after it changes.
        """
        query = merge_query_params(filters, params)
        if pagination is not None:
            query = merge_query_params(query, pagination.to_query_params())
        async for page in iter_cursor_pages(
            lambda page_query: self._list_sessions_page(project_uid, device_uid, page_query),
            query,
            resource="Session",
        ):
            yield page

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
        """Read device environment values and validate any supplied scope mappings.

        Device values are required. Defaults, effective values, and notes are
        validated when present; unknown response fields are preserved.
        """
        device_target = _device_target(
            project_uid, device_uid, target=target, composer=self._composer
        )
        payload = await self._client.request(
            "GET",
            _environment_path(device_target),
            params=merge_query_params(filters, params),
        )
        response = require_json_object(payload, "get_device_environment")
        if "environment_variables" not in response:
            raise NotehubResponseError("Missing environment_variables mapping")
        for field in (
            "environment_variables",
            "environment_variables_env_default",
            "environment_variables_effective",
            "environment_variable_notes",
        ):
            if field not in response:
                continue
            values = response[field]
            if not isinstance(values, dict) or any(
                not isinstance(value, str) for value in values.values()
            ):
                raise NotehubResponseError(f"Expected a string mapping for {field}")
        return cast("GetDeviceEnvironmentVariablesResponse", response)

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
        variables = resolve_environment(values, composer=self._composer)
        return await self._put_environment(device_target, variables)

    async def _put_environment(self, target: DeviceTarget, variables: dict[str, str]) -> JSONValue:
        result = await self._client.request(
            "PUT",
            _environment_path(target),
            json={"environment_variables": cast("JSONObject", variables)},
        )
        LOGGER.info(
            "Device environment updated: project_uid=%r device_uid=%r value_count=%r",
            target.project_uid,
            target.device_uid,
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
        path = _environment_path(device_target, variable_name)
        return await self._delete_environment(device_target, variable_name, path)

    async def _delete_environment(
        self, target: DeviceTarget, variable_name: str, path: str
    ) -> JSONValue:
        result = await self._client.request("DELETE", path)
        LOGGER.info(
            "Device environment variable removed: project_uid=%r device_uid=%r variable_name=%r",
            target.project_uid,
            target.device_uid,
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
        """Project UID bound to this handle."""
        return self.target.project_uid

    @property
    def device_uid(self) -> str:
        """Device UID bound to this handle."""
        return self.target.device_uid

    @property
    def environment(self) -> DeviceEnvironment:
        """Access device-level environment values through this handle."""
        return DeviceEnvironment(self)

    def to_notehub_target(self) -> DeviceTarget:
        """Return this handle's address for composed operations."""
        return self.target

    async def get(self) -> Device:
        """Fetch the current device record."""
        return await self._devices.get(self.project_uid, self.device_uid)


@dataclass(frozen=True, slots=True)
class DeviceEnvironment:
    """Read and edit the device-level environment variable mapping."""

    _device: DeviceHandle

    async def read(self) -> dict[str, str]:
        """Return a mutable copy of device values, excluding inherited values."""
        response = await self._device._devices.get_environment(target=self._device)
        values = response["environment_variables"]
        return dict(values)

    @asynccontextmanager
    async def edit(self) -> AsyncGenerator[dict[str, str], None]:
        """Read device values and apply local changes after a successful exit.

        Exceptions in the context body discard edits. Local preparation completes
        before the first write. Updates and deletions use separate requests, so
        an API failure can leave a partially applied edit.
        Concurrent remote changes are not detected or rolled back.
        """
        original = await self.read()
        values = dict(original)
        yield values
        changed = {key: value for key, value in values.items() if original.get(key) != value}
        removed = sorted(original.keys() - values.keys())
        if not changed and not removed:
            return
        devices = self._device._devices
        composer = devices._composer
        target = _device_target(_MISSING, _MISSING, target=self._device, composer=composer)
        updates = resolve_environment(changed, composer=composer) if changed else {}
        deletions = []
        for key in removed:
            name = resolve_identifier(key, "environment variable name", composer=composer)
            deletions.append((name, _environment_path(target, name)))
        if updates:
            await devices._put_environment(target, updates)
        for name, path in deletions:
            await devices._delete_environment(target, name, path)


def _environment_path(target: DeviceTarget, *keys: str) -> str:
    return encode_path_segments(
        "projects", target.project_uid, "devices", target.device_uid, "environment_variables", *keys
    )


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
