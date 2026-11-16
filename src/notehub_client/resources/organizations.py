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
    from ..filters import BalanceHistoryFilters
    from ..typing import (
        BalanceHistoryResponse,
        OrganizationDetails,
        OrganizationsResponse,
        QueryFilter,
        QueryValue,
    )
    from .base import RequestClient


class OrganizationsFacade:
    """Read organizations and organization-level billing information."""

    def __init__(self, client: RequestClient) -> None:
        self._client = client

    async def get(self, organization_uid: str) -> OrganizationDetails:
        """Fetch an organization and its available account details."""
        payload = await self._client.request(
            "GET", encode_path_segments("organizations", organization_uid)
        )
        return cast("OrganizationDetails", require_json_object(payload, "get_organization"))

    async def balance_history(
        self,
        organization_uid: str,
        *,
        filters: BalanceHistoryFilters | None = None,
        **params: QueryValue,
    ) -> BalanceHistoryResponse:
        """Read event-capacity usage history for an organization."""
        payload = await self._client.request(
            "GET",
            encode_path_segments("organizations", organization_uid, "balance-history"),
            params=merge_query_params(filters, params),
        )
        return cast(
            "BalanceHistoryResponse",
            require_collection(payload, "data", paginated=False, optional=True),
        )

    async def list(
        self, *, filters: QueryFilter | None = None, **params: QueryValue
    ) -> OrganizationsResponse:
        """List organizations visible to the authenticated user."""
        payload = await self._client.request(
            "GET", encode_path_segments("organizations"), params=merge_query_params(filters, params)
        )
        return cast(
            "OrganizationsResponse",
            require_collection(payload, "organizations", paginated=False, optional=True),
        )
