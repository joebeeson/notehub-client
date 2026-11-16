"""Recursive JSON type aliases."""

from typing import TypeAlias

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject: TypeAlias = dict[str, JSONValue]

__all__ = ["JSONObject", "JSONScalar", "JSONValue"]
