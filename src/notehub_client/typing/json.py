"""Recursive JSON type aliases."""

from typing import TypeAlias

from typing_extensions import TypeAliasType

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue = TypeAliasType("JSONValue", JSONScalar | list["JSONValue"] | dict[str, "JSONValue"])
JSONObject: TypeAlias = dict[str, JSONValue]

__all__ = ["JSONObject", "JSONScalar", "JSONValue"]
