"""Shared validation for filter model values."""

from __future__ import annotations

from ..typing.query import QueryValue


def _validate_dates(start: int | None, end: int | None) -> None:
    for name, value in (("start_date", start), ("end_date", end)):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"{name} must be a nonnegative integer")
    if start is not None and end is not None and start > end:
        raise ValueError("start_date must be no later than end_date")


def _date_params(start: int | None, end: int | None) -> dict[str, QueryValue]:
    result: dict[str, QueryValue] = {}
    if start is not None:
        result["startDate"] = start
    if end is not None:
        result["endDate"] = end
    return result
