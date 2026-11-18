"""Typed device behavior, explicit step effects, and named factory discovery.

Factories create fresh callables per device and run. Installed factories use the
``notehub_client.simulate.behaviors`` entry-point group and load only when selected.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from importlib import metadata
from math import isfinite
from random import Random
from typing import Any, Self

from ..typing.simulate import Behavior, BehaviorFactory
from .helpers import freeze, identifier, note_body

__all__ = [
    "Behavior",
    "BehaviorBinding",
    "BehaviorFactory",
    "BehaviorRegistry",
    "OutboundNote",
    "StepContext",
    "StepResult",
    "readings",
    "sensor",
]

_PROTECTED = {
    "uid",
    "serial_number",
    "best_id",
    "product_uid",
    "fleet_uids",
    "provisioned",
    "last_activity",
}

# TODO; Might need to make this into a module.


def readings(value: object) -> Mapping[str, Any]:
    """Freeze JSON readings while protecting fields owned by the simulation."""
    result = note_body(value)
    if reserved := _PROTECTED.intersection(result):
        raise ValueError(f"readings cannot replace {', '.join(sorted(reserved))}")
    for key in ("temperature", "voltage"):
        if key in result:
            item = result[key]
            if isinstance(item, bool) or not isinstance(item, (int, float)) or not isfinite(item):
                raise ValueError(f"readings.{key} must be a finite number")
    return result


@dataclass(frozen=True, slots=True)
class OutboundNote:
    """A device-local Note produced by a behavior; identity comes from its binding."""

    file: str
    body: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "file", identifier(self.file))
        if not self.file.endswith(".qo"):
            raise ValueError("outbound Notefile must end in .qo")
        object.__setattr__(self, "body", note_body(self.body))


@dataclass(frozen=True, slots=True)
class StepContext:
    """Detached device inputs at one explicit step; step numbers begin at one."""

    project_uid: str
    device_uid: str
    now: datetime
    step: int
    readings: Mapping[str, Any]
    environment: Mapping[str, str]
    commands: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        for name in ("readings", "environment", "commands"):
            object.__setattr__(self, name, freeze(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class StepResult:
    """One validated transition: reading updates, Notes, and consumed command IDs."""

    readings: Mapping[str, Any] = field(default_factory=dict)
    outbound: tuple[OutboundNote, ...] = ()
    consumed: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "readings", readings(self.readings))
        notes = tuple(self.outbound)
        if any(not isinstance(note, OutboundNote) for note in notes):
            raise TypeError("outbound must contain OutboundNote values")
        object.__setattr__(self, "outbound", notes)
        consumed = tuple(identifier(value) for value in self.consumed)
        if len(set(consumed)) != len(consumed):
            raise ValueError("consumed command IDs must be unique")
        object.__setattr__(self, "consumed", consumed)

    def with_readings(self, **values: Any) -> Self:
        """Add or replace reading updates without changing this result."""
        return replace(self, readings={**self.readings, **values})

    def with_note(self, notefile: str, body: object) -> Self:
        """Append a Note using the normal Note body composition adapters."""
        return replace(self, outbound=(*self.outbound, OutboundNote(notefile, note_body(body))))

    def consuming(self, *note_ids: str) -> Self:
        """Mark delivered commands as handled when this transition is applied."""
        return replace(self, consumed=(*self.consumed, *note_ids))


@dataclass(frozen=True, slots=True)
class BehaviorBinding:
    """Reusable device binding to either a named or directly supplied factory."""

    project_uid: str
    device_uid: str
    name: str | None = None
    config: Mapping[str, Any] = field(default_factory=dict)
    factory: BehaviorFactory | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for key in ("project_uid", "device_uid"):
            object.__setattr__(self, key, identifier(getattr(self, key)))
        if (self.name is None) == (self.factory is None):
            raise ValueError("behavior requires exactly one name or factory")
        if self.name is not None:
            object.__setattr__(self, "name", identifier(self.name))
        if self.factory is not None and not callable(self.factory):
            raise TypeError("behavior factory must be callable")
        object.__setattr__(self, "config", note_body(self.config))


class BehaviorRegistry:
    """An isolated factory catalog; explicit local names take precedence over plugins."""

    def __init__(
        self, factories: Mapping[str, BehaviorFactory] | None = None, *, plugins: bool = True
    ) -> None:
        self._factories: dict[str, BehaviorFactory] = {"sensor": sensor}
        self._plugins = plugins
        for name, factory in (factories or {}).items():
            self.register(name, factory)

    def register(self, name: str, factory: BehaviorFactory) -> Self:
        """Register a local factory, rejecting duplicate local names."""
        name = identifier(name)
        if name in self._factories:
            raise ValueError(f"duplicate behavior name: {name}")
        if not callable(factory):
            raise TypeError(f"behavior {name!r} factory must be callable")
        self._factories[name] = factory
        return self

    def available(self) -> tuple[str, ...]:
        """List names without importing any installed plugin code."""
        names = set(self._factories)
        if self._plugins:
            names.update(
                ep.name for ep in metadata.entry_points(group="notehub_client.simulate.behaviors")
            )
        return tuple(sorted(names))

    def resolve(self, name: str) -> BehaviorFactory:
        """Load only the selected plugin; ambiguous installed names are errors."""
        if name in self._factories:
            return self._factories[name]
        matches = (
            tuple(metadata.entry_points(group="notehub_client.simulate.behaviors", name=name))
            if self._plugins
            else ()
        )
        if not matches:
            raise ValueError(f"unknown behavior: {name}")
        if len(matches) != 1:
            raise ValueError(f"duplicate installed behavior name: {name}")
        factory = matches[0].load()
        if not callable(factory):
            raise TypeError(f"behavior {name!r} entry point must load a factory")
        return factory


def sensor(config: Mapping[str, Any], *, seed: int) -> Behavior:
    """Build a seeded drifting sensor; delivered set_temperature commands reset it.

    Options: temperature (20), voltage (3.7), drift (0.1), noise (0), and
    notefile (telemetry.qo). Commands use commands.qi with set_temperature.
    """
    unknown = set(config) - {"temperature", "voltage", "drift", "noise", "notefile"}
    if unknown:
        raise ValueError(f"unknown sensor options: {', '.join(sorted(unknown))}")
    values = {
        key: config.get(key, default)
        for key, default in (
            ("temperature", 20.0),
            ("voltage", 3.7),
            ("drift", 0.1),
            ("noise", 0.0),
        )
    }
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            raise ValueError(f"sensor {key} must be a finite number")
    if values["noise"] < 0:
        raise ValueError("sensor noise must be nonnegative")
    notefile = identifier(config.get("notefile", "telemetry.qo"))
    OutboundNote(notefile)
    # A private generator gives reproducible simulated values, not security tokens.
    rng = Random(seed)  # noqa: S311  # nosec B311
    temperature = float(values["temperature"])

    def sample(context: StepContext) -> StepResult:
        nonlocal temperature
        consumed = []
        next_temperature = temperature + values["drift"]
        for command in context.commands:
            if command["file"] == "commands.qi" and "set_temperature" in command["body"]:
                value = command["body"]["set_temperature"]
                readings({"temperature": value})
                next_temperature = float(value)
                consumed.append(command["note"])
        next_temperature += rng.uniform(-values["noise"], values["noise"])
        result = StepResult(
            readings={"temperature": next_temperature, "voltage": values["voltage"]},
            consumed=tuple(consumed),
        ).with_note(notefile, {"celsius": next_temperature, "voltage": values["voltage"]})
        temperature = next_temperature
        return result

    return sample
