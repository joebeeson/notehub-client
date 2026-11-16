"""Project-scoped read operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ..filters import merge_query_params
from ..helpers import encode_path_segments, require_collection

if TYPE_CHECKING:
    from ..typing import QueryFilter, QueryValue, UsageApiResponse
    from .base import RequestClient


class UsageFacade:
    """Operations for usage."""

    def __init__(self, client: RequestClient) -> None:
        self._client = client

    async def get(
        self, project_uid: str, *, filters: QueryFilter | None = None, **params: QueryValue
    ) -> UsageApiResponse:
        """Read API usage totals for a project."""
        payload = await self._client.request(
            "GET",
            encode_path_segments("projects", project_uid, "usage", "api"),
            params=merge_query_params(filters, params),
        )
        return cast("UsageApiResponse", require_collection(payload, "data", paginated=False))
