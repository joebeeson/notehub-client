"""Structural protocols for application values adapted at client boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..compose import DeviceTarget, NoteTarget

__all__ = [
    "EnvironmentValueSource",
    "EnvironmentValuesSource",
    "IdentifierSource",
    "JSONValueSource",
    "NoteBodySource",
    "SecretValueSource",
    "TargetSource",
]


@runtime_checkable
class NoteBodySource(Protocol):
    """A structural source for a top-level note body object."""

    def to_note_body(self) -> Mapping[str, object]:
        """Return fields for the note body, without a Notehub request envelope."""
        ...


@runtime_checkable
class JSONValueSource(Protocol):
    """A structural source for a JSON value used anywhere in a note body."""

    def to_json_value(self) -> object:
        """Return a JSON scalar, mapping, sequence, or further adaptable value."""
        ...


@runtime_checkable
class EnvironmentValuesSource(Protocol):
    """A structural source for a mapping of device environment variables."""

    def to_environment_values(self) -> Mapping[str, object]:
        """Return environment variable names and values without an API envelope."""
        ...


@runtime_checkable
class EnvironmentValueSource(Protocol):
    """A structural source for one string-valued environment variable."""

    def to_environment_value(self) -> str:
        """Return the environment variable's wire string."""
        ...


@runtime_checkable
class IdentifierSource(Protocol):
    """A structural source for a project, device, notefile, note, or key string."""

    def to_notehub_identifier(self) -> str:
        """Return this object's Notehub path identifier."""
        ...


@runtime_checkable
class TargetSource(Protocol):
    """A structural source for a device or note operation target."""

    def to_notehub_target(self) -> DeviceTarget | NoteTarget:
        """Return the Notehub address represented by this object."""
        ...


@runtime_checkable
class SecretValueSource(Protocol):
    """A value that exposes its contents only when a caller explicitly reveals it.

    This structural contract is compatible with Pydantic secret types and does
    not require a wrapper subclass or a Pydantic dependency. CLI output masks
    these values by default. Ordinary ``repr()`` and ``__rich_repr__`` calls are
    separate from that formatter, so implementations should keep both safe too.
    """

    def get_secret_value(self) -> object:
        """Return the underlying value for an explicitly authorized reveal."""
        ...
