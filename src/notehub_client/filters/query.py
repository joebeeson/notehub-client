"""Composable immutable query values and filter factories."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..constants import EventDateTypeWire, EventSortFieldWire, EventSortOrderWire
from ..typing.query import QueryFilter, QueryValue
from ._validation import _date_params, _normalize_select_fields

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from datetime import datetime
    from typing import Self

    from ..typing.query import (
        EventDateTypeValue,
        EventSortFieldValue,
        EventSortOrderValue,
    )

__all__ = [
    "Query",
    "combine",
    "date_range",
    "devices",
    "events",
    "files",
    "fleets",
    "merge_query_params",
    "sensors",
    "serial_numbers",
    "sessions",
]


@dataclass(frozen=True, slots=True)
class Query(Mapping[str, QueryValue]):
    """Immutable wire query parameters with composable fluent conveniences.

    >>> dict(Query().devices("dev:one").files("sensors.qo"))
    {'deviceUID': ('dev:one',), 'files': 'sensors.qo'}
    """

    _items: tuple[tuple[str, QueryValue], ...] = ()

    def __post_init__(self) -> None:
        normalized: list[tuple[str, QueryValue]] = []
        for key, value in self._items:
            if isinstance(value, list):
                value = tuple(value)
            if not isinstance(key, str) or not key:
                raise ValueError("query keys must be nonempty strings")
            if isinstance(value, tuple):
                if any(not isinstance(item, str) for item in value):
                    raise ValueError("repeated query values must be strings")
            elif isinstance(value, float):
                if not math.isfinite(value):
                    raise ValueError("query numbers must be finite")
            elif not isinstance(value, (str, int, bool)):
                raise ValueError(
                    "query values must be strings, numbers, booleans, or string sequences"
                )
            normalized.append((key, value))
        object.__setattr__(self, "_items", tuple(normalized))
        keys = [key for key, _ in self._items]
        if len(set(keys)) != len(keys):
            raise ValueError("query keys cannot be repeated; use a sequence value")

    @classmethod
    def from_value(cls, value: QueryFilter | Mapping[str, QueryValue]) -> Query:
        """Normalize a mapping or structural filter into an immutable query."""
        if isinstance(value, Mapping):
            pairs = value.items()
        elif isinstance(value, QueryFilter):
            pairs = value.to_query_params().items()
        else:
            raise TypeError("query values must be mappings or implement to_query_params()")
        return cls(
            tuple((key, tuple(item) if isinstance(item, list) else item) for key, item in pairs)
        )

    def __getitem__(self, key: str) -> QueryValue:
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __rich_repr__(self) -> Iterator[object]:
        yield from self._items

    def to_query_params(self) -> dict[str, QueryValue]:
        """Return a mutable mapping suitable for an HTTP request."""
        return dict(self._items)

    def combine(self, *others: QueryFilter | Mapping[str, QueryValue]) -> Self:
        """Return a query containing these values and non-overlapping additions.

        Raises ``ValueError`` when any query key appears in more than one input.
        """
        pairs = list(self._items)
        seen = set(self)
        for other in others:
            next_query = Query.from_value(other)
            overlap = seen.intersection(next_query)
            if overlap:
                raise ValueError(f"Query parameters specified twice: {', '.join(sorted(overlap))}")
            pairs.extend(next_query._items)
            seen.update(next_query)
        return type(self)(tuple(pairs))

    def _set(self, **params: QueryValue) -> Self:
        updates = dict(params)
        pairs = [(key, value) for key, value in self._items if key not in updates]
        pairs.extend(updates.items())
        return type(self)(tuple(pairs))

    def devices(self, *uids: str) -> Self:
        """Add device UIDs as repeated ``deviceUID`` values."""
        return self._append("deviceUID", *uids)

    def files(self, *names: str) -> Self:
        """Add file names to Notehub's comma-separated ``files`` parameter."""
        if any(not isinstance(name, str) or not name for name in names):
            raise ValueError("file names must be nonempty strings")
        current = self.get("files")
        existing = tuple(current.split(",")) if isinstance(current, str) else ()
        return self._set(files=",".join((*existing, *names)))

    def sensors(self, *uids: str) -> Self:
        """Add sensor UIDs as repeated ``sensorUID`` values."""
        return self._append("sensorUID", *uids)

    def fleets(self, *uids: str) -> Self:
        """Add fleet UIDs as repeated ``fleetUID`` values."""
        return self._append("fleetUID", *uids)

    def serial_numbers(self, *values: str) -> Self:
        """Add device serial numbers as repeated ``serialNumber`` values."""
        return self._append("serialNumber", *values)

    def sessions(self, *uids: str) -> Self:
        """Add session UIDs as repeated ``sessionUID`` values."""
        return self._append("sessionUID", *uids)

    def events(self, *uids: str) -> Self:
        """Add event UIDs as repeated ``eventUID`` values."""
        return self._append("eventUID", *uids)

    def date_range(
        self,
        start: int | datetime | None = None,
        end: int | datetime | None = None,
    ) -> Self:
        """Set optional Unix-second or timezone-aware datetime bounds for event dates."""
        return self._set(**_date_params(start, end))

    def date_type(self, value: EventDateTypeWire | EventDateTypeValue) -> Self:
        """Set whether event dates are based on capture or upload time."""
        return self._set(dateType=EventDateTypeWire(value).value)

    def sort_by(self, value: EventSortFieldWire | EventSortFieldValue) -> Self:
        """Set the Notehub event field used to sort matching results."""
        return self._set(sortBy=EventSortFieldWire(value).value)

    def sort_order(self, value: EventSortOrderWire | EventSortOrderValue) -> Self:
        """Set ascending or descending order for event results."""
        return self._set(sortOrder=EventSortOrderWire(value).value)

    def system_files_only(self, enabled: bool = True) -> Self:
        """Include only system Notefiles when enabled."""
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        return self._set(systemFilesOnly=enabled)

    def select_fields(self, value: str | Sequence[str]) -> Self:
        """Set event fields as a comma-separated string or a sequence of names."""
        return self._set(selectFields=_normalize_select_fields(value))

    def since(self, value: str) -> Self:
        """Set a Notehub cursor value for retrieving events changed since it."""
        if not value:
            raise ValueError("since must be nonempty")
        return self._set(since=value)

    def _append(self, key: str, *values: str) -> Self:
        if not values:
            return self
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError("selector values must be nonempty strings")
        current = self.get(key, ())
        prior = (
            current
            if isinstance(current, tuple)
            else (current,)
            if isinstance(current, str)
            else ()
        )
        return self._set(**{key: (*prior, *values)})


def merge_query_params(
    filters: QueryFilter | Mapping[str, QueryValue] | None,
    extra: Mapping[str, QueryValue],
) -> dict[str, QueryValue]:
    """Combine filter values and explicit parameters, rejecting duplicate keys."""
    query = Query.from_value(filters).to_query_params() if filters is not None else {}
    overlap = query.keys() & extra.keys()
    if overlap:
        raise ValueError(f"Query parameters specified twice: {', '.join(sorted(overlap))}")
    return {**query, **extra}


def combine(*values: QueryFilter | Mapping[str, QueryValue]) -> Query:
    """Combine query components, rejecting duplicate wire keys."""
    return Query().combine(*values)


def devices(*uids: str) -> Query:
    """Create a query filtered by one or more device UIDs."""
    return Query().devices(*uids)


def files(*names: str) -> Query:
    """Create a query filtered by one or more Notefile names."""
    return Query().files(*names)


def sensors(*uids: str) -> Query:
    """Create a query filtered by one or more sensor UIDs."""
    return Query().sensors(*uids)


def fleets(*uids: str) -> Query:
    """Create a query filtered by one or more fleet UIDs."""
    return Query().fleets(*uids)


def serial_numbers(*values: str) -> Query:
    """Create a query filtered by one or more device serial numbers."""
    return Query().serial_numbers(*values)


def sessions(*uids: str) -> Query:
    """Create a query filtered by one or more session UIDs."""
    return Query().sessions(*uids)


def events(*uids: str) -> Query:
    """Create a query filtered by one or more event UIDs."""
    return Query().events(*uids)


def date_range(
    start: int | datetime | None = None, end: int | datetime | None = None
) -> Query:
    """Create an event query with Unix-second or timezone-aware datetime bounds."""
    return Query().date_range(start, end)
