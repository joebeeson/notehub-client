"""Page-number and cursor pagination values and constructors."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from ..constants import DEFAULT_PAGE_SIZE
from ..typing.query import QueryValue

__all__ = ["CursorPagination", "Pagination", "cursor", "page"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Pagination:
    """Page-number options for paginated collection endpoints."""

    page_size: int = DEFAULT_PAGE_SIZE
    page_num: int | None = None

    def __post_init__(self) -> None:
        if type(self.page_size) is not int or not 1 <= self.page_size <= 10_000:
            raise ValueError("page_size must be an integer from 1 to 10000")
        if self.page_num is not None and (type(self.page_num) is not int or self.page_num < 1):
            raise ValueError("page_num must be a positive integer")

    def to_query_params(self) -> dict[str, QueryValue]:
        """Return the Notehub page-size and optional one-based page number."""
        result: dict[str, QueryValue] = {"pageSize": self.page_size}
        if self.page_num is not None:
            result["pageNum"] = self.page_num
        return result

    def __iter__(self) -> Iterator[tuple[str, QueryValue]]:
        return iter(self.to_query_params().items())


@dataclass(frozen=True, slots=True, kw_only=True)
class CursorPagination:
    """Cursor options for cursor-paginated collection endpoints."""

    cursor: str = "0"
    page_size: int = DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        if not isinstance(self.cursor, str) or not self.cursor:
            raise ValueError("cursor must be a nonempty string")
        if type(self.page_size) is not int or not 1 <= self.page_size <= 10_000:
            raise ValueError("page_size must be an integer from 1 to 10000")

    def to_query_params(self) -> dict[str, QueryValue]:
        """Return the Notehub cursor and page-size query parameters."""
        return {"cursor": self.cursor, "pageSize": self.page_size}

    def __iter__(self) -> Iterator[tuple[str, QueryValue]]:
        return iter(self.to_query_params().items())


def page(page_size: int = DEFAULT_PAGE_SIZE, page_num: int | None = None) -> Pagination:
    """Build page-number pagination for collection endpoints."""
    return Pagination(page_size=page_size, page_num=page_num)


def cursor(value: str = "0", page_size: int = DEFAULT_PAGE_SIZE) -> CursorPagination:
    """Build cursor pagination for cursor-based collection endpoints."""
    return CursorPagination(cursor=value, page_size=page_size)
