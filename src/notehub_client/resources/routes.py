"""Project-scoped read operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ..errors import NotehubResponseError
from ..filters import merge_query_params
from ..helpers import encode_path_segments

if TYPE_CHECKING:
    from ..typing import NotehubRouteSummary, QueryFilter, QueryValue
    from .base import RequestClient


class RoutesFacade:
    """Operations for routes."""

    def __init__(self, client: RequestClient) -> None:
        self._client = client

    async def list(
        self, project_uid: str, *, filters: QueryFilter | None = None, **params: QueryValue
    ) -> list[NotehubRouteSummary]:
        """List project routes, raising if Notehub returns a malformed payload."""
        payload = await self._client.request(
            "GET",
            encode_path_segments("projects", project_uid, "routes"),
            params=merge_query_params(filters, params),
        )
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise NotehubResponseError("Expected a list of JSON objects for list_routes")
        return cast("list[NotehubRouteSummary]", payload)
