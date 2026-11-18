"""Project and fleet event operations."""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, TypeVar, cast

from ..catalog import ContractKey
from ..constants import DEFAULT_PAGE_SIZE
from ..filters import CursorPagination, merge_query_params
from ..helpers import encode_path_segments, require_collection
from ..payloads import DecodedEvent, PayloadDecoder
from ._pagination import iter_cursor_pages

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

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
        return await self._list_page(project_uid, query)

    async def _list_page(self, project_uid: str, query: dict[str, QueryValue]) -> EventsResponse:
        query.setdefault("pageSize", DEFAULT_PAGE_SIZE)
        if "cursor" in query and {"pageNum", "sortBy", "sortOrder"} & query.keys():
            raise ValueError("cursor cannot be combined with pageNum or sorting")
        payload = await self._client.request(
            "GET", encode_path_segments("projects", project_uid, "events"), params=query
        )
        return cast("EventsResponse", require_collection(payload, "events", paginated=True))

    async def iter_pages(
        self,
        project_uid: str,
        *,
        filters: QueryFilter | None = None,
        pagination: CursorPagination | None = None,
        **params: QueryValue,
    ) -> AsyncGenerator[EventsResponse, None]:
        """Yield event pages, including empty pages, until ``has_more`` is false.

        Supply cursor and page size in the query or via ``pagination``. Duplicate
        keys are rejected. The query is resolved once at the start of iteration.
        For a resumable read, save a nonempty ``next_cursor`` only after processing
        the whole page, including the terminal page when it has a cursor.
        """
        query = merge_query_params(filters, params)
        if pagination is not None:
            query = merge_query_params(query, pagination.to_query_params())
        async for page in iter_cursor_pages(
            lambda page_query: self._list_page(project_uid, page_query), query, resource="Event"
        ):
            yield page

    async def iter(
        self,
        project_uid: str,
        *,
        filters: QueryFilter | None = None,
        pagination: CursorPagination | None = None,
        **params: QueryValue,
    ) -> AsyncIterator[Event]:
        """Yield individual events while following the same cursors as iter_pages()."""
        async for page in self.iter_pages(
            project_uid, filters=filters, pagination=pagination, **params
        ):
            for event in page["events"]:
                yield event

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
