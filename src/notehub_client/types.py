"""Python types for JSON and commonly used Notehub responses."""

from __future__ import annotations

from typing import NotRequired, TypeAlias, TypedDict

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject: TypeAlias = dict[str, JSONValue]
QueryValue: TypeAlias = str | int | float | bool | list[str] | tuple[str, ...]


class Device(TypedDict):
    """Common Notehub device fields; unknown fields remain available."""

    uid: str
    serial_number: NotRequired[str]
    provisioned: NotRequired[str]
    last_activity: NotRequired[str]
    product_uid: NotRequired[str]
    fleet_uids: NotRequired[list[str]]
    tags: NotRequired[str]
    voltage: NotRequired[float]
    temperature: NotRequired[float]


class Event(TypedDict):
    """Common Notehub event fields with application-defined body JSON."""

    event: str
    device: NotRequired[str]
    when: NotRequired[int | float]
    received: NotRequired[int | float]
    file: NotRequired[str]
    req: NotRequired[str]
    body: NotRequired[JSONObject]
    next_cursor: NotRequired[str]
    has_more: NotRequired[bool]
