"""Stateless Notehub domain facades sharing the owning client's transport."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ..filters import merge_query_params
from ..helpers import (
    encode_path_segments,
    require_collection,
    require_json_object,
)

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

    def __init__(self, client: RequestClient) -> None:
        self._client = client

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
