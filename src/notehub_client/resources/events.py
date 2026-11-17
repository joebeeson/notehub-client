"""Project and fleet event operations."""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, TypeVar, cast

from ..catalog import ContractKey
from ..constants import DEFAULT_PAGE_SIZE
from ..errors import NotehubResponseError
from ..filters import CursorPagination, merge_query_params
from ..helpers import encode_path_segments, require_collection
from ..payloads import DecodedEvent, PayloadDecoder

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ..typing import Event, EventsResponse, QueryFilter, QueryValue
    from .base import RequestClient


T = TypeVar("T")


class EventsFacade:
    """Operations for project and fleet event collections."""

    def __init__(self, client: RequestClient, *, payloads: PayloadDecoder | None = None) -> None:
        self._client = client
        self._payloads = payloads if payloads is not None else PayloadDecoder()

    async def list(
        self,
        project_uid: str,
        *,
        filters: QueryFilter | None = None,
        pagination: CursorPagination | None = None,
        **params: QueryValue,
    ) -> EventsResponse:
        """Fetch one cursor-paginated page of project events."""
        query = merge_query_params(filters, params)
        if pagination is not None:
            query = merge_query_params(query, pagination.to_query_params())
        query.setdefault("pageSize", DEFAULT_PAGE_SIZE)
        if "cursor" in query and {"pageNum", "sortBy", "sortOrder"} & query.keys():
            raise ValueError("cursor cannot be combined with pageNum or sorting")
        payload = await self._client.request(
            "GET", encode_path_segments("projects", project_uid, "events"), params=query
        )
        return cast("EventsResponse", require_collection(payload, "events", paginated=True))

    async def iter(
        self,
        project_uid: str,
        *,
        filters: QueryFilter | None = None,
        pagination: CursorPagination | None = None,
        **params: QueryValue,
    ) -> AsyncIterator[Event]:
        """Yield matching project events while following Notehub's cursors."""
        current = pagination or CursorPagination()
        seen = {current.cursor}
        while True:
            page = await self.list(
                project_uid,
                filters=filters,
                pagination=current,
                **params,
            )
            for event in page["events"]:
                yield event
            if not page["has_more"]:
                return
            next_cursor = page.get("next_cursor")
            if not next_cursor or next_cursor in seen:
                raise NotehubResponseError(
                    "Event cursor missing or repeated while more results remain"
                )
            seen.add(next_cursor)
            current = CursorPagination(cursor=next_cursor, page_size=current.page_size)

    async def iter_decoded(
        self,
        project_uid: str,
        *,
        as_type: type[T],
        contract: ContractKey | None = None,
        filters: QueryFilter | None = None,
        pagination: CursorPagination | None = None,
        **params: QueryValue,
    ) -> AsyncIterator[DecodedEvent[T]]:
        """Decode each event explicitly, propagating selection and conversion failures."""
        async for event in self.iter(project_uid, filters=filters, pagination=pagination, **params):
            yield self._payloads.decode(event, as_type=as_type, contract=contract)

    async def collect(
        self,
        project_uid: str,
        *,
        filters: QueryFilter | None = None,
        pagination: CursorPagination | None = None,
        **params: QueryValue,
    ) -> builtins.list[Event]:
        """Collect all matching project events in memory."""
        return [
            event
            async for event in self.iter(
                project_uid,
                filters=filters,
                pagination=pagination,
                **params,
            )
        ]

    async def list_for_fleet(
        self,
        project_uid: str,
        fleet_uid: str,
        *,
        filters: QueryFilter | None = None,
        **params: QueryValue,
    ) -> EventsResponse:
        """Fetch one page of events associated with a project fleet."""
        payload = await self._client.request(
            "GET",
            encode_path_segments("projects", project_uid, "fleets", fleet_uid, "events"),
            params=merge_query_params(filters, params),
        )
        return cast("EventsResponse", require_collection(payload, "events", paginated=True))
