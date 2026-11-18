"""Validated endpoint-specific filter models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..constants import EventDateTypeWire, EventSortFieldWire, EventSortOrderWire
from ._validation import (
    _date_params,
    _normalize_dates,
    _normalize_select_fields,
    _normalize_string_sequence,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from datetime import datetime

    from ..typing.query import (
        EventDateTypeValue,
        EventSortFieldValue,
        EventSortOrderValue,
        QueryValue,
    )

__all__ = ["BalanceHistoryFilters", "DeviceFilters", "EventFilters"]


@dataclass(frozen=True, slots=True, kw_only=True)
class BalanceHistoryFilters:
    """Select a range using Unix seconds or timezone-aware datetimes.

    Datetimes are converted to UTC Unix seconds; subsecond precision is dropped.
    """

    start_date: int | datetime | None = None
    end_date: int | datetime | None = None

    def __post_init__(self) -> None:
        start, end = _normalize_dates(self.start_date, self.end_date)
        object.__setattr__(self, "start_date", start)
        object.__setattr__(self, "end_date", end)

    def to_query_params(self) -> dict[str, QueryValue]:
        """Return the supplied range using Notehub's ``startDate`` and ``endDate`` keys."""
        return _date_params(self.start_date, self.end_date)

    def __iter__(self) -> Iterator[tuple[str, QueryValue]]:
        return iter(self.to_query_params().items())

    def __rich_repr__(self) -> Iterator[object]:
        yield "start_date", self.start_date, None
        yield "end_date", self.end_date, None


@dataclass(frozen=True, slots=True, kw_only=True)
class EventFilters:
    """Build event-list filters with Notehub wire keys and value validation.

    File names are serialized as a comma-separated value; other selectors become
    repeated query values. Sequence inputs are normalized to tuples. Date bounds
    accept Unix timestamps or timezone-aware datetimes and are stored as UTC Unix
    seconds with subsecond precision dropped.
    """

    files: Sequence[str] = ()
    device_uids: Sequence[str] = ()
    sensor_uids: Sequence[str] = ()
    fleet_uids: Sequence[str] = ()
    serial_numbers: Sequence[str] = ()
    session_uids: Sequence[str] = ()
    event_uids: Sequence[str] = ()
    start_date: int | datetime | None = None
    end_date: int | datetime | None = None
    date_type: EventDateTypeValue | EventDateTypeWire | None = None
    sort_by: EventSortFieldValue | EventSortFieldWire | None = None
    sort_order: EventSortOrderValue | EventSortOrderWire | None = None
    system_files_only: bool | None = None
    select_fields: str | Sequence[str] | None = None
    since: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "files",
            "device_uids",
            "sensor_uids",
            "fleet_uids",
            "serial_numbers",
            "session_uids",
            "event_uids",
        ):
            object.__setattr__(
                self,
                name,
                _normalize_string_sequence(getattr(self, name), name),
            )
        start, end = _normalize_dates(self.start_date, self.end_date)
        object.__setattr__(self, "start_date", start)
        object.__setattr__(self, "end_date", end)
        if self.system_files_only is not None and type(self.system_files_only) is not bool:
            raise ValueError("system_files_only must be a boolean")
        if self.select_fields is not None:
            object.__setattr__(
                self,
                "select_fields",
                _normalize_select_fields(self.select_fields),
            )
        if self.since is not None and not self.since:
            raise ValueError("since must be nonempty")
        for name, enum in (
            ("date_type", EventDateTypeWire),
            ("sort_by", EventSortFieldWire),
            ("sort_order", EventSortOrderWire),
        ):
            value = getattr(self, name)
            if value is not None:
                try:
                    enum(value)
                except (TypeError, ValueError):
                    raise ValueError(f"{name} is not supported") from None

    def to_query_params(self) -> dict[str, QueryValue]:
        """Return event selectors and options in Notehub's query format."""
        result: dict[str, QueryValue] = {}
        for field_name, key in (
            ("files", "files"),
            ("device_uids", "deviceUID"),
            ("sensor_uids", "sensorUID"),
            ("fleet_uids", "fleetUID"),
            ("serial_numbers", "serialNumber"),
            ("session_uids", "sessionUID"),
            ("event_uids", "eventUID"),
        ):
            values = tuple(getattr(self, field_name))
            if values:
                result[key] = ",".join(values) if key == "files" else values
        result.update(_date_params(self.start_date, self.end_date))
        for value, enum in (
            (self.date_type, EventDateTypeWire),
            (self.sort_by, EventSortFieldWire),
            (self.sort_order, EventSortOrderWire),
        ):
            if value is not None:
                item = enum(value)
                result[item.query_key] = item.value
        for key, value in (
            ("systemFilesOnly", self.system_files_only),
            ("since", self.since),
        ):
            if value is not None:
                result[key] = value
        if self.select_fields is not None:
            fields = self.select_fields
            result["selectFields"] = fields if isinstance(fields, str) else ",".join(fields)
        return result

    def __iter__(self) -> Iterator[tuple[str, QueryValue]]:
        return iter(self.to_query_params().items())

    def __rich_repr__(self) -> Iterator[object]:
        for name in (
            "files",
            "device_uids",
            "sensor_uids",
            "fleet_uids",
            "serial_numbers",
            "session_uids",
            "event_uids",
            "start_date",
            "end_date",
            "date_type",
            "sort_by",
            "sort_order",
            "system_files_only",
            "select_fields",
            "since",
        ):
            default = (
                ()
                if name
                in {
                    "files",
                    "device_uids",
                    "sensor_uids",
                    "fleet_uids",
                    "serial_numbers",
                    "session_uids",
                    "event_uids",
                }
                else None
            )
            yield name, getattr(self, name), default


@dataclass(frozen=True, slots=True, kw_only=True)
class DeviceFilters:
    """Select devices by their identifiers, metadata, firmware, or location."""

    device_uids: Sequence[str] = ()
    fleet_uids: Sequence[str] = ()
    tags: Sequence[str] = ()
    serial_numbers: Sequence[str] = ()
    notecard_firmware: Sequence[str] = ()
    locations: Sequence[str] = ()
    host_firmware: Sequence[str] = ()
    product_uids: Sequence[str] = ()
    skus: Sequence[str] = ()

    def __post_init__(self) -> None:
        for name in (
            "device_uids",
            "fleet_uids",
            "tags",
            "serial_numbers",
            "notecard_firmware",
            "locations",
            "host_firmware",
            "product_uids",
            "skus",
        ):
            object.__setattr__(
                self,
                name,
                _normalize_string_sequence(getattr(self, name), name),
            )

    def to_query_params(self) -> dict[str, QueryValue]:
        """Return each nonempty filter using its Notehub query key."""
        names = (
            "device_uids",
            "fleet_uids",
            "tags",
            "serial_numbers",
            "notecard_firmware",
            "locations",
            "host_firmware",
            "product_uids",
            "skus",
        )
        keys = (
            "deviceUID",
            "fleetUID",
            "tag",
            "serialNumber",
            "notecardFirmware",
            "location",
            "hostFirmware",
            "productUID",
            "sku",
        )
        return {
            key: tuple(getattr(self, name)) for name, key in zip(names, keys) if getattr(self, name)
        }

    def __iter__(self) -> Iterator[tuple[str, QueryValue]]:
        return iter(self.to_query_params().items())

    def __rich_repr__(self) -> Iterator[object]:
        for name in (
            "device_uids",
            "fleet_uids",
            "tags",
            "serial_numbers",
            "notecard_firmware",
            "locations",
            "host_firmware",
            "product_uids",
            "skus",
        ):
            yield name, getattr(self, name), ()
