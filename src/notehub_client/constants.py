"""Shared Notehub defaults, service locations, and wire enum values."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from .typing.query import EventDateTypeValue, EventSortFieldValue, EventSortOrderValue

NOTEHUB_API_ORIGIN: Final[str] = "https://api.notefile.net"
DEFAULT_TIMEOUT: Final[float] = 30.0
DEFAULT_PAGE_SIZE: Final[int] = 100

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_TIMEOUT",
    "NOTEHUB_API_ORIGIN",
    "EventDateTypeWire",
    "EventSortFieldWire",
    "EventSortOrderWire",
]


class EventDateTypeWire(str, Enum):
    """Event date basis accepted by Notehub's event query endpoint."""

    _value_: EventDateTypeValue

    CAPTURED = "captured"
    UPLOADED = "uploaded"

    @property
    def query_key(self) -> Literal["dateType"]:
        """Return the Notehub query parameter for this enum."""
        return "dateType"


class EventSortFieldWire(str, Enum):
    """Event sort field accepted by Notehub's event query endpoint."""

    _value_: EventSortFieldValue

    BEST_ID = "best_id"
    DEVICE_SERIAL = "device_serial"
    DEVICE_UID = "device_uid"
    CAPTURED = "captured"
    MODIFIED = "modified"
    DEVICE_LOCATION = "device_location"
    TOWER_LOCATION = "tower_location"
    TRIANGULATED_LOCATION = "triangulated_location"
    BEST_LOCATION = "best_location"

    @property
    def query_key(self) -> Literal["sortBy"]:
        """Return the Notehub query parameter for this enum."""
        return "sortBy"


class EventSortOrderWire(str, Enum):
    """Sort direction accepted by Notehub's event query endpoint."""

    _value_: EventSortOrderValue

    ASC = "asc"
    DESC = "desc"

    @property
    def query_key(self) -> Literal["sortOrder"]:
        """Return the Notehub query parameter for this enum."""
        return "sortOrder"
