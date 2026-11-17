"""Scenario composition, loading, and reference validation."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from ..typing.simulate import BehaviorFactory
from .behaviors import BehaviorBinding, BehaviorRegistry
from .helpers import timestamp
from .models import Device, Event, Fleet, Project, QueuedNote

if TYPE_CHECKING:
    from .simulation import Simulation

__all__ = ["Scenario"]


@dataclass(frozen=True, slots=True)
class Scenario:
    """Reusable immutable initial conditions; every start creates independent state."""

    projects: tuple[Project, ...] = ()
    fleets: tuple[Fleet, ...] = ()
    devices: tuple[Device, ...] = ()
    events: tuple[Event, ...] = ()
    outbound: tuple[QueuedNote, ...] = ()
    inbound: tuple[QueuedNote, ...] = ()
    device_inbound: tuple[QueuedNote, ...] = ()
    start_time: datetime = datetime(2025, 1, 1, tzinfo=timezone.utc)
    behaviors: tuple[BehaviorBinding, ...] = ()

    def __post_init__(self) -> None:
        # Mapping compatibility keeps Python and TOML on the same constructors.
        for name, model in (
            ("projects", Project),
            ("fleets", Fleet),
            ("devices", Device),
            ("events", Event),
            ("outbound", QueuedNote),
            ("inbound", QueuedNote),
            ("device_inbound", QueuedNote),
            ("behaviors", BehaviorBinding),
        ):
            values: list[Any] = []
            for index, value in enumerate(getattr(self, name)):
                try:
                    values.append(model(**value) if isinstance(value, Mapping) else value)
                    if not isinstance(values[-1], model):
                        raise TypeError(f"expected {model.__name__}")
                except (TypeError, ValueError) as error:
                    raise ValueError(f"{name}[{index}]: {error}") from error
            object.__setattr__(self, name, tuple(values))
        object.__setattr__(self, "start_time", timestamp(self.start_time))
        projects = {x.uid for x in self.projects}
        fleets = {(x.project_uid, x.uid) for x in self.fleets}
        devices = {(x.project_uid, x.uid) for x in self.devices}
        bound = set()
        for binding in self.behaviors:
            key = (binding.project_uid, binding.device_uid)
            if key not in devices:
                raise ValueError("behaviors: unknown device reference")
            if key in bound:
                raise ValueError("behaviors: only one behavior per device")
            bound.add(key)
        if (
            len(projects) != len(self.projects)
            or len(fleets) != len(self.fleets)
            or len(devices) != len(self.devices)
        ):
            raise ValueError("duplicate project, fleet, or device identity")
        for value in (*self.fleets, *self.devices):
            if value.project_uid not in projects:
                raise ValueError(f"unknown project reference: {value.project_uid}")
        for device in self.devices:
            if any((device.project_uid, uid) not in fleets for uid in device.fleet_uids):
                raise ValueError(f"devices[{device.uid}].fleet_uids: unknown fleet")
        for name in ("events", "outbound", "inbound", "device_inbound"):
            for index, note in enumerate(getattr(self, name)):
                if (note.project_uid, note.device_uid) not in devices:
                    raise ValueError(f"{name}[{index}]: unknown device reference")
                suffix = ".qo" if name == "outbound" else ".qi"
                if name != "events" and not note.file.endswith(suffix):
                    raise ValueError(f"{name}[{index}].file: expected {suffix}")
        ids = [x.event for x in self.events if x.event is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("events: duplicate event identifier")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Self:
        """Load a version 1 scenario mapping using the same typed constructors."""
        data = dict(value)
        if data.pop("scenario_version", None) != 1:
            raise ValueError("scenario_version must be 1")
        if isinstance(data.get("start_time"), str):
            data["start_time"] = datetime.fromisoformat(data["start_time"].replace("Z", "+00:00"))
        for name in ("events", "outbound", "inbound", "device_inbound"):
            entries = []
            for raw in data.get(name, ()):
                item = dict(raw)
                for key in ("when", "received"):
                    if key in item:
                        moment = item[key]
                        if isinstance(moment, (int, float)):
                            item[key] = datetime.fromtimestamp(moment, timezone.utc)
                        elif isinstance(moment, str):
                            item[key] = datetime.fromisoformat(moment.replace("Z", "+00:00"))
                entries.append(item)
            data[name] = entries
        try:
            return cls(**data)
        except (TypeError, ValueError) as error:
            raise ValueError(f"scenario: {error}") from error

    @classmethod
    def from_toml(cls, path: str | Path) -> Self:
        """Read a versioned TOML scenario, reporting the source for invalid data."""
        path = Path(path)
        try:
            return cls.from_mapping(tomllib.loads(path.read_text(encoding="utf-8")))
        except (TypeError, ValueError) as error:
            raise ValueError(f"{path}: {error}") from error

    def with_project(self, uid: str, **values: Any) -> Self:
        """Append a project without mutating this scenario."""
        return replace(self, projects=(*self.projects, Project(uid, **values)))

    def with_fleet(self, project_uid: str, uid: str, **values: Any) -> Self:
        """Append a fleet without mutating this scenario."""
        return replace(self, fleets=(*self.fleets, Fleet(project_uid, uid, **values)))

    def with_device(self, project_uid: str, device_uid: str, **values: Any) -> Self:
        """Append a device without mutating this scenario."""
        return replace(self, devices=(*self.devices, Device(project_uid, device_uid, **values)))

    def with_event(
        self, project_uid: str, device_uid: str, notefile: str, body: Any, **values: Any
    ) -> Self:
        """Append already received history."""
        return replace(
            self, events=(*self.events, Event(project_uid, device_uid, notefile, body, **values))
        )

    def with_outbound(
        self, project_uid: str, device_uid: str, notefile: str, body: Any, **values: Any
    ) -> Self:
        """Append a Note waiting on a Notecard for synchronization."""
        return replace(
            self,
            outbound=(
                *self.outbound,
                QueuedNote(project_uid, device_uid, notefile, body, **values),
            ),
        )

    def with_inbound(
        self,
        project_uid: str,
        device_uid: str,
        notefile: str,
        body: Any,
        *,
        delivered: bool = False,
        **values: Any,
    ) -> Self:
        """Append a cloud queue Note or one already delivered to the device."""
        name = "device_inbound" if delivered else "inbound"
        note = QueuedNote(project_uid, device_uid, notefile, body, **values)
        return replace(self, **{name: (*getattr(self, name), note)})

    def with_behavior(
        self,
        project_uid: str,
        device_uid: str,
        factory_or_name: BehaviorFactory | str,
        *,
        config: Mapping[str, Any] | None = None,
    ) -> Self:
        """Bind one named or application-owned behavior factory to a device."""
        binding = BehaviorBinding(
            project_uid,
            device_uid,
            name=factory_or_name if isinstance(factory_or_name, str) else None,
            factory=None if isinstance(factory_or_name, str) else factory_or_name,
            config={} if config is None else config,
        )
        return replace(self, behaviors=(*self.behaviors, binding))

    def start(self, *, registry: BehaviorRegistry | None = None, seed: int = 0) -> Simulation:
        """Create an independent mutable run from these definitions."""
        from .simulation import Simulation

        return Simulation(self, registry=registry, seed=seed)

    @classmethod
    def named(cls, name: str) -> Scenario:
        """Load one of the packaged offline scenarios."""
        from .presets import named

        return named(name)

    @classmethod
    def from_value(cls, value: object) -> Scenario:
        """Resolve a scenario through public converters or ScenarioSource."""
        from .converters import resolve_scenario

        return resolve_scenario(value)

    def __rich_repr__(self):
        yield "projects", len(self.projects)
        yield "devices", len(self.devices)
        yield "start_time", self.start_time
