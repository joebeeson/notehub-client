"""Resolution and validation helpers for composed Notehub values."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from ._validation import mapping_path, require_identifier
from .converters import (
    environment_value,
    environment_values,
    json_value,
    note_body,
    notehub_identifier,
    notehub_target,
)
from .models import DeviceTarget, NoteTarget

if TYPE_CHECKING:
    from ..typing import JSONValue
    from .composer import Composer

__all__ = [
    "resolve_environment",
    "resolve_identifier",
    "resolve_json",
    "resolve_note_body",
    "resolve_target",
]


def resolve_identifier(
    value: object, name: str = "identifier", *, composer: Composer | None = None
) -> str:
    """Resolve and validate one nonempty path identifier."""
    result = (composer.notehub_identifier if composer is not None else notehub_identifier)(value)
    return require_identifier(result, name)


def resolve_target(value: object, *, composer: Composer | None = None) -> DeviceTarget | NoteTarget:
    """Resolve an application object to a validated device or note target."""
    result = (composer.notehub_target if composer is not None else notehub_target)(value)
    if not isinstance(result, (DeviceTarget, NoteTarget)):
        raise TypeError("target converter must return a DeviceTarget or NoteTarget")
    return result


def resolve_note_body(value: object, *, composer: Composer | None = None) -> dict[str, JSONValue]:
    """Resolve a top-level note body and recursively normalize its JSON values."""
    body = (composer.note_body if composer is not None else note_body)(value)
    if not isinstance(body, Mapping):
        raise TypeError("note body converter must return a mapping")
    result = resolve_json(body, composer=composer)
    if not isinstance(result, dict):
        raise TypeError("note body must resolve to a JSON object")
    return result


def resolve_json(value: object, *, composer: Composer | None = None) -> JSONValue:
    """Walk a value tree and convert application values into ordinary JSON data.

    Mappings are copied with string keys. Lists and tuples become lists. Custom
    values are converted through ``json_value``; that conversion may return a
    scalar, mapping, sequence, or another adaptable value. Cycles, non-finite
    floats, and unsupported objects raise ``ValueError`` or ``TypeError`` with
    the location but without the value contents.
    """
    active: set[int] = set()

    def walk(node: object, path: str) -> JSONValue:
        identity = id(node)
        if identity in active:
            raise ValueError(f"cyclic value at {path}")
        active.add(identity)
        try:
            converted = (composer.json_value if composer is not None else json_value)(node)
            if converted is not node:
                return walk(converted, path)
            if node is None or isinstance(node, (str, bool, int)):
                return node
            if isinstance(node, float):
                if not math.isfinite(node):
                    raise ValueError(f"non-finite number at {path}")
                return node
            if isinstance(node, Mapping):
                result: dict[str, JSONValue] = {}
                for key, child in node.items():
                    if not isinstance(key, str):
                        raise TypeError(f"non-string object key at {path}")
                    result[key] = walk(child, mapping_path(path, key))
                return result
            if isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
                return [walk(child, f"{path}[{index}]") for index, child in enumerate(node)]
            raise TypeError(f"unsupported JSON value at {path}: {type(node).__name__}")
        finally:
            active.remove(identity)

    return walk(value, "$")


def resolve_environment(values: object, *, composer: Composer | None = None) -> dict[str, str]:
    """Resolve an environment mapping and convert every value to a string."""
    source = (composer.environment_values if composer is not None else environment_values)(values)
    if not isinstance(source, Mapping):
        raise TypeError("environment values converter must return a mapping")
    result: dict[str, str] = {}
    for key, value in source.items():
        if not isinstance(key, str):
            raise TypeError("environment variable names must be strings")
        converted = (composer.environment_value if composer is not None else environment_value)(
            value
        )
        if not isinstance(converted, str):
            raise TypeError(
                f"environment value converter must return a string at {mapping_path('$', key)}"
            )
        result[key] = converted
    return result
