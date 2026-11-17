"""Stateless Notehub domain facades sharing the owning client's transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from ..filters import merge_query_params
from ..helpers import (
    encode_path_segments,
    require_collection,
    require_json_object,
)
from .devices import DeviceHandle, DevicesFacade

if TYPE_CHECKING:
    from ..typing import (
        Project,
        ProjectsResponse,
        QueryFilter,
        QueryValue,
    )
    from .base import RequestClient


class ProjectsFacade:
    """Operations for the projects domain."""

    def __init__(self, client: RequestClient, *, devices: DevicesFacade | None = None) -> None:
        self._client = client
        self._devices = devices if devices is not None else DevicesFacade(client)

    def __getitem__(self, project_uid: str) -> ProjectHandle:
        return ProjectHandle(project_uid, self, ProjectDevices(project_uid, self._devices))

    async def get(self, project_uid: str) -> Project:
        """Fetch a project by its UID."""
        return cast(
            "Project",
            require_json_object(
                await self._client.request("GET", encode_path_segments("projects", project_uid)),
                "project",
            ),
        )

    async def list(
        self, *, filters: QueryFilter | None = None, **params: QueryValue
    ) -> ProjectsResponse:
        """List projects visible to the authenticated user."""
        return cast(
            "ProjectsResponse",
            require_collection(
                await self._client.request(
                    "GET", "projects", params=merge_query_params(filters, params)
                ),
                "projects",
                optional=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class ProjectDevices:
    project_uid: str
    _devices: DevicesFacade

    def __getitem__(self, device_uid: str) -> DeviceHandle:
        return self._devices[self.project_uid, device_uid]


@dataclass(frozen=True, slots=True)
class ProjectHandle:
    project_uid: str
    _projects: ProjectsFacade
    devices: ProjectDevices

    async def get(self) -> Project:
        return await self._projects.get(self.project_uid)
