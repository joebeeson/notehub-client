"""Independent outbound adaptation registries for each client."""

from __future__ import annotations

from collections.abc import Callable
from functools import singledispatch
from typing import Any

from ..typing.json import JSONValue
from . import converters
from .helpers import (
    resolve_environment,
    resolve_identifier,
    resolve_json,
    resolve_note_body,
    resolve_target,
)
from .models import DeviceTarget, NoteTarget


class Adapter:
    """A local single-dispatch callable with a snapshot-able registry."""

    def __init__(self, fallback: Callable[[Any], object], *, frozen: bool = False) -> None:
        self._dispatch = singledispatch(fallback)
        self._frozen = frozen

    def __call__(self, value: object) -> object:
        """Dispatch one value through this adapter's local registry."""
        return self._dispatch(value)

    def register(self, cls: Any, func: Any = None) -> Any:
        """Register by explicit class or annotated decorator before snapshotting."""
        if self._frozen:
            raise RuntimeError("client adapter registrations are frozen")
        if func is not None:
            return self._dispatch.register(cls, func)
        if isinstance(cls, type):
            # Route decorator application through the freeze check too.
            return lambda handler: self.register(cls, handler)
        return self._dispatch.register(cls)

    def copy(self, *, frozen: bool = False) -> Adapter:
        """Copy registrations, retaining the same user handler callables."""
        result = Adapter(self._dispatch.registry[object])
        for cls, handler in self._dispatch.registry.items():
            result.register(cls, handler)
        result._frozen = frozen
        return result


class Composer:
    """Configure explicit adaptation for notes, environment values, and addresses.

    Register handlers on the six adapter attributes before passing this object
    to a client. Structural ``to_*`` methods remain the default fallbacks.
    """

    def __init__(self) -> None:
        self.note_body = Adapter(converters.note_body)
        self.json_value = Adapter(converters.json_value)
        self.environment_values = Adapter(converters.environment_values)
        self.environment_value = Adapter(converters.environment_value)
        self.notehub_identifier = Adapter(converters.notehub_identifier)
        self.notehub_target = Adapter(converters.notehub_target)

    def copy(self, *, frozen: bool = False) -> Composer:
        """Snapshot all adapters, optionally rejecting new registrations."""
        result = Composer()
        for name in (
            "note_body",
            "json_value",
            "environment_values",
            "environment_value",
            "notehub_identifier",
            "notehub_target",
        ):
            setattr(result, name, getattr(self, name).copy(frozen=frozen))
        return result

    def resolve_json(self, value: object) -> JSONValue:
        """Adapt and validate a nested JSON value tree."""
        return resolve_json(value, composer=self)

    def resolve_note_body(self, value: object) -> dict[str, JSONValue]:
        """Adapt and validate a top-level note body."""
        return resolve_note_body(value, composer=self)

    def resolve_environment(self, value: object) -> dict[str, str]:
        """Adapt a complete environment variable mapping."""
        return resolve_environment(value, composer=self)

    def resolve_identifier(self, value: object, name: str = "identifier") -> str:
        """Adapt and validate one path identifier."""
        return resolve_identifier(value, name, composer=self)

    def resolve_target(self, value: object) -> DeviceTarget | NoteTarget:
        """Adapt a complete device or note target."""
        return resolve_target(value, composer=self)
