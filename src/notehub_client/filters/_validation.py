"""Shared validation for filter model values."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..typing.query import QueryValue


def _normalize_string_sequence(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence of nonempty strings")
    normalized = tuple(value)
    if any(not isinstance(item, str) or not item for item in normalized):
        raise ValueError(f"{name} must contain only nonempty strings")
    return normalized


def _normalize_select_fields(value: str | Sequence[str]) -> str:
    if isinstance(value, str):
        if not value:
            raise ValueError("select_fields must be nonempty")
        return value
    fields = _normalize_string_sequence(value, "select_fields")
    if not fields:
        raise ValueError("select_fields must contain at least one field name")
    return ",".join(fields)


def _timestamp_seconds(value: int | datetime | None, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is int:
        seconds = value
    elif isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError(f"{name} datetime must be timezone-aware")
        utc_value = value.astimezone(timezone.utc)
        # Notehub accepts whole Unix seconds; discard any subsecond precision.
        seconds = (utc_value - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(seconds=1)
    else:
        raise ValueError(
            f"{name} must be a nonnegative integer Unix timestamp or timezone-aware datetime"
        )
    if seconds < 0:
        raise ValueError(f"{name} must be a nonnegative Unix timestamp")
    return seconds


def _normalize_dates(
    start: int | datetime | None, end: int | datetime | None
) -> tuple[int | None, int | None]:
    start_seconds = _timestamp_seconds(start, "start_date")
    end_seconds = _timestamp_seconds(end, "end_date")
    if start_seconds is not None and end_seconds is not None and start_seconds > end_seconds:
        raise ValueError("start_date must be no later than end_date")
    return start_seconds, end_seconds


def _date_params(start: int | datetime | None, end: int | datetime | None) -> dict[str, QueryValue]:
    result: dict[str, QueryValue] = {}
    start_seconds, end_seconds = _normalize_dates(start, end)
    if start_seconds is not None:
        result["startDate"] = start_seconds
    if end_seconds is not None:
        result["endDate"] = end_seconds
    return result
