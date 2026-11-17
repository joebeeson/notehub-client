"""Immutable scenario descriptions and simulation outcome values."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any

from ..compose import DeviceTarget, NoteTarget
from .behaviors import readings
from .helpers import environment, identifier, note_body, timestamp

__all__ = ["Device", "Event", "Fault", "Fleet", "Project", "QueuedNote", "SyncResult"]


@dataclass(frozen=True, slots=True)
class Description:
    """Rich representation shared by immutable simulation descriptions."""

    def __rich_repr__(self) -> Iterator[object]:
        for item in fields(self):
            if item.name != "body":
                yield item.name, getattr(self, item.name)


@dataclass(frozen=True, slots=True)
class Project(Description):
    """A simulated Notehub project and its environment defaults."""

    uid: str
    label: str = ""
    environment: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "uid", identifier(self.uid))
        if not isinstance(self.label, str):
            raise ValueError("label must be a string")
        object.__setattr__(self, "environment", environment(self.environment))

    def to_notehub_identifier(self) -> str:
        """Return this project's address."""
        return self.uid


@dataclass(frozen=True, slots=True)
class Fleet(Description):
    """A named fleet within a project."""

    project_uid: str
    uid: str
    label: str = ""
    environment: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_uid", identifier(self.project_uid))
        object.__setattr__(self, "uid", identifier(self.uid))
        if not isinstance(self.label, str):
            raise ValueError("label must be a string")
        object.__setattr__(self, "environment", environment(self.environment))


@dataclass(frozen=True, slots=True)
class Device(Description):
    """Initial Notecard membership, identity, and environment values."""

    project_uid: str
    uid: str
    fleet_uids: tuple[str, ...] = ()
    serial_number: str = ""
    product_uid: str = "product:simulation"
    environment: Mapping[str, str] = field(default_factory=dict)
    defaults: Mapping[str, str] = field(default_factory=dict)
    readings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_uid", identifier(self.project_uid))
        object.__setattr__(self, "uid", identifier(self.uid))
        object.__setattr__(self, "product_uid", identifier(self.product_uid))
        if not isinstance(self.serial_number, str):
            raise ValueError("serial_number must be a string")
        object.__setattr__(self, "fleet_uids", tuple(identifier(x) for x in self.fleet_uids))
        object.__setattr__(self, "environment", environment(self.environment))
        object.__setattr__(self, "defaults", environment(self.defaults))
        object.__setattr__(self, "readings", readings(self.readings))

    def to_notehub_target(self) -> DeviceTarget:
        """Return the address for normal client environment operations."""
        return DeviceTarget(self.project_uid, self.uid)

    def to_notehub_identifier(self) -> str:
        """Return this device's UID."""
        return self.uid

    def note(self, notefile: str) -> NoteTarget:
        """Address a queue Note for normal client operations."""
        return NoteTarget(self.project_uid, self.uid, notefile)


@dataclass(frozen=True, slots=True)
class QueuedNote(Description):
    """One Note in a scenario queue; timestamps default to the scenario clock."""

    project_uid: str
    device_uid: str
    file: str
    body: Mapping[str, Any] = field(default_factory=dict)
    when: datetime | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        for name in ("project_uid", "device_uid", "file"):
            object.__setattr__(self, name, identifier(getattr(self, name)))
        object.__setattr__(self, "body", note_body(self.body))
        if self.note is not None:
            object.__setattr__(self, "note", identifier(self.note))
        if self.when is not None:
            object.__setattr__(self, "when", timestamp(self.when))


@dataclass(frozen=True, slots=True)
class Event(QueuedNote):
    """A historical Notehub event, already received before the run starts."""

    event: str | None = None
    received: datetime | None = None
    sensor: str | None = None
    session: str | None = None

    def __post_init__(self) -> None:
        QueuedNote.__post_init__(self)
        for name in ("event", "sensor", "session"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, identifier(getattr(self, name)))
        if self.received is not None:
            object.__setattr__(self, "received", timestamp(self.received))


@dataclass(frozen=True, slots=True)
class Fault(Description):
    """One matching request fails; None status simulates a connection failure."""

    method: str
    path: str
    status_code: int | None = 500
    retry_after: str | None = None

    def __post_init__(self) -> None:
        if not self.method or not self.path or self.path.startswith("/"):
            raise ValueError("fault requires a method and a path relative to /v1/")
        if self.status_code is not None and not 400 <= self.status_code <= 599:
            raise ValueError("fault status_code must be 400..599 or None")
        object.__setattr__(self, "method", self.method.upper())


@dataclass(frozen=True, slots=True)
class SyncResult(Description):
    """Observed simulated transfers, distinct from host command execution."""

    session: str
    sent: int
    received: int
