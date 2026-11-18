"""Stateless Notehub domain facades sharing the owning client's transport."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ..filters import merge_query_params
from ..helpers import (
    encode_path_segments,
    require_collection,
)

if TYPE_CHECKING:
    from ..typing import (
        FleetsResponse,
        QueryFilter,
        QueryValue,
    )
    from .base import RequestClient


class FleetsFacade:
    """Operations for the fleets domain."""

    def __init__(self, client: RequestClient) -> None:
        self._client = client

    async def list(
        self, project_uid: str, *, filters: QueryFilter | None = None, **params: QueryValue
    ) -> FleetsResponse:
        """List fleets belonging to a project."""
        payload = await self._client.request(
            "GET",
            encode_path_segments("projects", project_uid, "fleets"),
            params=merge_query_params(filters, params),
        )
        return cast("FleetsResponse", require_collection(payload, "fleets", require_uid=True))
