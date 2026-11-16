"""Project-scoped read operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ..filters import merge_query_params
from ..helpers import encode_path_segments, require_collection

if TYPE_CHECKING:
    from ..typing import GetJobsResponse, QueryFilter, QueryValue
    from .base import RequestClient


class JobsFacade:
    """Operations for jobs."""

    def __init__(self, client: RequestClient) -> None:
        self._client = client

    async def list(
        self, project_uid: str, *, filters: QueryFilter | None = None, **params: QueryValue
    ) -> GetJobsResponse:
        """List jobs configured for a project."""
        payload = await self._client.request(
            "GET",
            encode_path_segments("projects", project_uid, "jobs"),
            params=merge_query_params(filters, params),
        )
        return cast("GetJobsResponse", require_collection(payload, "jobs", paginated=False))
