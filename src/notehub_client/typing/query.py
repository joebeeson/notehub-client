"""Query parameter types and structural protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping

QueryScalar: TypeAlias = str | int | float | bool
QueryValue: TypeAlias = QueryScalar | list[str] | tuple[str, ...]
EventDateTypeValue: TypeAlias = Literal["captured", "uploaded"]
EventSortFieldValue: TypeAlias = Literal[
    "best_id",
    "device_serial",
    "device_uid",
    "captured",
    "modified",
    "device_location",
    "tower_location",
    "triangulated_location",
    "best_location",
]
EventSortOrderValue: TypeAlias = Literal["asc", "desc"]


# Filters are structural: immutable dataclasses and application types can implement this.
@runtime_checkable
class QueryFilter(Protocol):
    """Structural interface implemented by objects that provide query parameters.

    Implementations can be supplied to resource methods or composed with
    :class:`notehub_client.filters.Query` without inheriting from this protocol.
    """

    def to_query_params(self) -> Mapping[str, QueryValue]:
        """Return the filter as Notehub wire keys and query values."""
        ...


__all__ = [
    "EventDateTypeValue",
    "EventSortFieldValue",
    "EventSortOrderValue",
    "QueryFilter",
    "QueryScalar",
    "QueryValue",
]
