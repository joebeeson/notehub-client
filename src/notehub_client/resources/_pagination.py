"""Cursor traversal shared by read-only resource facades."""

from __future__ import annotations

from typing import TYPE_CHECKING, NotRequired, TypedDict, TypeVar

from ..errors import NotehubResponseError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from ..typing import QueryValue


class _CursorPage(TypedDict):
    has_more: bool
    next_cursor: NotRequired[str]


_Page = TypeVar("_Page", bound=_CursorPage)


async def iter_cursor_pages(
    load: Callable[[dict[str, QueryValue]], Awaitable[_Page]],
    query: dict[str, QueryValue],
    *,
    resource: str,
) -> AsyncIterator[_Page]:
    """Follow a cursor, rejecting missing or repeated continuation cursors."""
    query = {
        key: tuple(value) if isinstance(value, list) else value for key, value in query.items()
    }
    cursor = query.setdefault("cursor", "0")
    if not isinstance(cursor, str) or not cursor:
        raise ValueError("cursor must be a nonempty string")
    seen = {cursor}
    while True:
        page = await load(query)
        if not page["has_more"]:
            yield page
            return
        next_cursor = page.get("next_cursor")
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen:
            raise NotehubResponseError(
                f"{resource} cursor missing or repeated while more results remain"
            )
        seen.add(next_cursor)
        query = {**query, "cursor": next_cursor}
        yield page
