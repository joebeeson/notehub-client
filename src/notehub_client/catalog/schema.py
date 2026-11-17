"""Traversal of Draft 07 schema locations, excluding literal example data."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_MAPPINGS = {"properties", "patternProperties", "definitions", "$defs"}
_SINGLE = {
    "additionalProperties",
    "additionalItems",
    "contains",
    "propertyNames",
    "not",
    "if",
    "then",
    "else",
}
_ARRAYS = {"allOf", "anyOf", "oneOf"}


def map_schema(schema: Any, transform: Callable[[dict[str, Any]], dict[str, Any]]) -> Any:
    """Transform schema objects recursively without interpreting instance data."""
    if not isinstance(schema, dict):
        return schema
    result = dict(schema)
    for key, value in schema.items():
        if key in _MAPPINGS:
            result[key] = {name: map_schema(child, transform) for name, child in value.items()}
        elif key in _SINGLE:
            result[key] = map_schema(value, transform)
        elif key in _ARRAYS:
            result[key] = [map_schema(child, transform) for child in value]
        elif key == "items":
            result[key] = (
                [map_schema(child, transform) for child in value]
                if isinstance(value, list)
                else map_schema(value, transform)
            )
        elif key == "dependencies":
            result[key] = {name: map_schema(child, transform) for name, child in value.items()}
    return transform(result)
