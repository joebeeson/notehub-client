"""Validated endpoint-specific filter models."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from ..constants import EventDateTypeWire, EventSortFieldWire, EventSortOrderWire
from ..typing.query import (
    EventDateTypeValue,
    EventSortFieldValue,
    EventSortOrderValue,
    QueryValue,
)
from ._validation import _date_params, _validate_dates

__all__ = ["BalanceHistoryFilters", "DeviceFilters", "EventFilters"]


@dataclass(frozen=True, slots=True, kw_only=True)
class BalanceHistoryFilters:
    """Select an optional Unix-timestamp range for a balance-history request."""

    start_date: int | None = None
    end_date: int | None = None

    def __post_init__(self) -> None:
        _validate_dates(self.start_date, self.end_date)

    def to_query_params(self) -> dict[str, QueryValue]:
        """Return the supplied range using Notehub's ``startDate`` and ``endDate`` keys."""
        return _date_params(self.start_date, self.end_date)

    def __iter__(self) -> Iterator[tuple[str, QueryValue]]:
        return iter(self.to_query_params().items())


@dataclass(frozen=True, slots=True, kw_only=True)
class EventFilters:
    """Build event-list filters with Notehub wire keys and value validation.

    File names are serialized as a comma-separated value; the other selector
    tuples become repeated query values. Date bounds are Unix timestamps.
    """

    files: tuple[str, ...] = ()
    device_uids: tuple[str, ...] = ()
    sensor_uids: tuple[str, ...] = ()
    fleet_uids: tuple[str, ...] = ()
    serial_numbers: tuple[str, ...] = ()
    session_uids: tuple[str, ...] = ()
    event_uids: tuple[str, ...] = ()
    start_date: int | None = None
    end_date: int | None = None
    date_type: EventDateTypeValue | EventDateTypeWire | None = None
    sort_by: EventSortFieldValue | EventSortFieldWire | None = None
    sort_order: EventSortOrderValue | EventSortOrderWire | None = None
    system_files_only: bool | None = None
    select_fields: str | None = None
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
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(
                not isinstance(v, str) or not v for v in values
            ):
                raise ValueError(f"{name} must be a tuple of nonempty strings")
        _validate_dates(self.start_date, self.end_date)
        if self.system_files_only is not None and type(self.system_files_only) is not bool:
            raise ValueError("system_files_only must be a boolean")
        if self.select_fields is not None and not self.select_fields:
            raise ValueError("select_fields must be nonempty")
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
            values = getattr(self, field_name)
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
            ("selectFields", self.select_fields),
            ("since", self.since),
        ):
            if value is not None:
                result[key] = value
        return result

    def __iter__(self) -> Iterator[tuple[str, QueryValue]]:
        return iter(self.to_query_params().items())


@dataclass(frozen=True, slots=True, kw_only=True)
class DeviceFilters:
    """Select devices by their identifiers, metadata, firmware, or location."""

    device_uids: tuple[str, ...] = ()
    fleet_uids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    serial_numbers: tuple[str, ...] = ()
    notecard_firmware: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()
    host_firmware: tuple[str, ...] = ()
    product_uids: tuple[str, ...] = ()
    skus: tuple[str, ...] = ()

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
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(
                not isinstance(v, str) or not v for v in values
            ):
                raise ValueError(f"{name} must be a tuple of nonempty strings")

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
        return {key: getattr(self, name) for name, key in zip(names, keys) if getattr(self, name)}

    def __iter__(self) -> Iterator[tuple[str, QueryValue]]:
        return iter(self.to_query_params().items())
