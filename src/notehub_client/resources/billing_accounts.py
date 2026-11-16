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
        BillingAccountDetails,
        BillingAccountsResponse,
        QueryFilter,
        QueryValue,
    )
    from .base import RequestClient


class BillingAccountsFacade:
    """Operations for the legacy billing accounts API.

    Notehub's organization endpoints are the current home for billing-account
    data; this facade remains for callers using the older endpoint family.
    """

    def __init__(self, client: RequestClient) -> None:
        self._client = client

    async def list(
        self, *, filters: QueryFilter | None = None, **params: QueryValue
    ) -> BillingAccountsResponse:
        """List billing accounts visible to the authenticated user."""
        payload = await self._client.request(
            "GET", "billing-accounts", params=merge_query_params(filters, params)
        )
        return cast(
            "BillingAccountsResponse",
            require_collection(payload, "billing_accounts", paginated=False, optional=True),
        )

    async def get(self, billing_account_uid: str) -> BillingAccountDetails:
        """Fetch one billing account and its available plan details."""
        payload = await self._client.request(
            "GET", encode_path_segments("billing-accounts", billing_account_uid)
        )
        return cast("BillingAccountDetails", require_json_object(payload, "get_billing_account"))

    async def balance_history(
        self,
        billing_account_uid: str,
        *,
        filters: BalanceHistoryFilters | None = None,
        **params: QueryValue,
    ) -> BalanceHistoryResponse:
        """Read event-capacity usage history for a billing account."""
        payload = await self._client.request(
            "GET",
            encode_path_segments("billing-accounts", billing_account_uid, "balance-history"),
            params=merge_query_params(filters, params),
        )
        return cast(
            "BalanceHistoryResponse",
            require_collection(payload, "data", paginated=False, optional=True),
        )
