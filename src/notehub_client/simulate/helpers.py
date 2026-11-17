"""Value helpers shared by simulation authoring and execution."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any

from ..compose import resolve_environment, resolve_identifier, resolve_note_body

__all__ = ["environment", "freeze", "identifier", "note_body", "timestamp"]


def freeze(value: Any) -> Any:
    """Copy JSON-shaped containers into recursively immutable containers."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


def environment(value: object) -> Mapping[str, str]:
    """Normalize environment values through the library's composition adapters."""
    return MappingProxyType(resolve_environment(value))


def identifier(value: object) -> str:
    """Resolve a simulation address through the normal identifier adapters."""
    return resolve_identifier(value)


def note_body(value: object) -> Mapping[str, Any]:
    """Normalize and freeze a Note body, including custom composition sources."""
    return freeze(resolve_note_body(value))


def timestamp(value: datetime) -> datetime:
    """Require an aware clock and normalize it to UTC."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("time must be timezone-aware")
    return value.astimezone(timezone.utc)
