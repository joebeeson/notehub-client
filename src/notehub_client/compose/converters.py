"""Default structural adaptation functions without global registrations."""

from __future__ import annotations

from collections.abc import Mapping

from ..typing.compose import (
    EnvironmentValueSource,
    EnvironmentValuesSource,
    IdentifierSource,
    JSONValueSource,
    NoteBodySource,
    TargetSource,
)
from .models import DeviceTarget, NoteTarget

__all__ = [
    "environment_value",
    "environment_values",
    "json_value",
    "note_body",
    "notehub_identifier",
    "notehub_target",
]


def note_body(value: object) -> object:
    """Convert an application object to its top-level note body."""
    if isinstance(value, NoteBodySource):
        return value.to_note_body()
    if isinstance(value, Mapping):
        return value
    raise TypeError("note body must be a mapping or implement to_note_body()")


def json_value(value: object) -> object:
    """Convert an application object used as a nested JSON value."""
    if isinstance(value, JSONValueSource):
        return value.to_json_value()
    return value


def environment_values(value: object) -> object:
    """Convert an application object to environment variable values."""
    if isinstance(value, EnvironmentValuesSource):
        return value.to_environment_values()
    if isinstance(value, Mapping):
        return value
    raise TypeError("environment values must be a mapping or implement to_environment_values()")


def environment_value(value: object) -> object:
    """Convert one environment value to the string sent to Notehub."""
    if isinstance(value, EnvironmentValueSource):
        return value.to_environment_value()
    if isinstance(value, str):
        return value
    raise TypeError("environment values must be strings or implement to_environment_value()")


def notehub_identifier(value: object) -> object:
    """Convert an application object to one Notehub path identifier."""
    if isinstance(value, IdentifierSource):
        return value.to_notehub_identifier()
    if isinstance(value, str):
        return value
    raise TypeError("identifier must be a string or implement to_notehub_identifier()")


def notehub_target(value: object) -> object:
    """Convert an application object to a device or note target."""
    if isinstance(value, TargetSource):
        return value.to_notehub_target()
    if isinstance(value, (DeviceTarget, NoteTarget)):
        return value
    raise TypeError("target must be a DeviceTarget or NoteTarget, or implement to_notehub_target()")
