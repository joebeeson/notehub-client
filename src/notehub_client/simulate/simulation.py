"""Mutable local simulation runs and typed Notecard workflow handles."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import AsyncIterator, Iterable, Iterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Self

import httpx

from ..client import NotehubClient
from ..compose import DeviceTarget, NoteTarget, resolve_note_body
from ..helpers import RequestPacer
from ..typing.observe import Observer
from .behaviors import Behavior, BehaviorRegistry, StepContext, StepResult
from .helpers import freeze, identifier
from .models import Device, Event, Fault, QueuedNote, SyncResult

if TYPE_CHECKING:
    from ..compose import Composer
    from ..payloads import PayloadDecoder
    from .transport import SimulationTransport

__all__ = ["SimulatedDevice", "Simulation"]


@dataclass
class _DeviceState:
    definition: Device
    environment: dict[str, str]
    outbound: list[dict[str, Any]] = field(default_factory=list)
    inbound: list[dict[str, Any]] = field(default_factory=list)
    delivered: list[dict[str, Any]] = field(default_factory=list)
    synced_environment: dict[str, str] = field(default_factory=dict)
    sessions: list[dict[str, Any]] = field(default_factory=list)
    last_activity: str | None = None
    readings: dict[str, Any] = field(default_factory=dict)
    behavior: Behavior | None = None
    steps: int = 0


class Simulation:
    """One isolated run; clients and handles share state until the run is closed.

    Use one event loop/thread per run. Device operations are synchronous and
    atomic within that loop. No device activity or synchronization runs in the
    background.
    """

    def __init__(
        self, scenario: object, *, registry: BehaviorRegistry | None = None, seed: int = 0
    ) -> None:
        from .converters import resolve_scenario

        scenario = resolve_scenario(scenario)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("simulation seed must be an integer")
        self.scenario = scenario
        self._now = scenario.start_time
        self._closed = False
        self._sequence = 0
        self._used_ids = {
            value
            for item in (
                *scenario.events,
                *scenario.outbound,
                *scenario.inbound,
                *scenario.device_inbound,
            )
            for value in (item.note, getattr(item, "event", None), getattr(item, "session", None))
            if value is not None
        }
        self._projects = {p.uid: p for p in scenario.projects}
        self._fleets = {(f.project_uid, f.uid): f for f in scenario.fleets}
        self._project_env = {p.uid: dict(p.environment) for p in scenario.projects}
        self._fleet_env = {(f.project_uid, f.uid): dict(f.environment) for f in scenario.fleets}
        self._states = {
            (d.project_uid, d.uid): _DeviceState(d, dict(d.environment), readings=dict(d.readings))
            for d in scenario.devices
        }
        self._events: list[dict[str, Any]] = []
        self._faults: list[Fault] = []
        # Cursor state belongs to the run, not an individual transport/client.
        self._cursors: OrderedDict[str, tuple[tuple[Any, ...], int]] = OrderedDict()
        for event in scenario.events:
            self._events.append(self._event(event, event.received or self.now))
        for name, destination in (
            ("outbound", "outbound"),
            ("inbound", "inbound"),
            ("device_inbound", "delivered"),
        ):
            for note in getattr(scenario, name):
                state = self._state(note.project_uid, note.device_uid)
                getattr(state, destination).append(self._note(note))
        registry = registry if registry is not None else BehaviorRegistry()
        for binding in scenario.behaviors:
            factory = (
                binding.factory
                if binding.factory is not None
                else registry.resolve(binding.name or "")
            )
            # Length-independent separators avoid ambiguous identities; Python hash is salted.
            material = repr((seed, binding.project_uid, binding.device_uid)).encode("utf-8")
            device_seed = int.from_bytes(sha256(material).digest(), "big")
            behavior = factory(binding.config, seed=device_seed)
            if not callable(behavior):
                raise TypeError("behavior factory must return a callable")
            self._state(binding.project_uid, binding.device_uid).behavior = behavior

    @property
    def now(self) -> datetime:
        """Current explicit UTC simulation clock."""
        return self._now

    @property
    def closed(self) -> bool:
        """Whether this run has been closed."""
        return self._closed

    def _id(self, kind: str) -> str:
        while True:
            self._sequence += 1
            value = f"sim-{kind}-{self._sequence:08d}"
            if value not in self._used_ids:
                self._used_ids.add(value)
                return value

    def _note(self, note: QueuedNote) -> dict[str, Any]:
        return {
            "project_uid": note.project_uid,
            "device_uid": note.device_uid,
            "file": note.file,
            "body": resolve_note_body(note.body),
            "when": int((note.when or self.now).timestamp()),
            "note": note.note or self._id("note"),
        }

    def _event(self, event: Event, received: datetime) -> dict[str, Any]:
        result = self._note(event)
        result.update(
            app=event.project_uid,
            device=event.device_uid,
            event=event.event or self._id("event"),
            received=received.timestamp(),
        )
        definition = self._state(event.project_uid, event.device_uid).definition
        result.update(
            sn=definition.serial_number,
            best_id=definition.serial_number or definition.uid,
            product=definition.product_uid,
        )
        for key in ("sensor", "session"):
            value = getattr(event, key)
            if value is not None:
                result[key] = value
        return result

    def _state(self, project_uid: str, device_uid: str) -> _DeviceState:
        self._ensure_open()
        return self._states[(project_uid, device_uid)]

    def _ensure_open(self) -> None:
        if self.closed:
            raise RuntimeError("Simulation is closed")

    def advance(self, delta: timedelta) -> None:
        """Move time forward without implicitly synchronizing any device."""
        self._ensure_open()
        if delta < timedelta(0):
            raise ValueError("delta must be nonnegative")
        self._now += delta

    def device(self, project_uid: str, device_uid: str) -> SimulatedDevice:
        """Resolve a handle, requiring both project and device identity."""
        self._state(project_uid, device_uid)
        return SimulatedDevice(self, project_uid, device_uid)

    def step(self) -> Mapping[tuple[str, str], StepResult]:
        """Step bound devices in scenario order, without advancing time or syncing.

        Each device transition is atomic. If a later device fails, earlier
        successful transitions remain applied.
        """
        self._ensure_open()
        return freeze(
            {
                key: self.device(*key).step()
                for key, state in self._states.items()
                if state.behavior is not None
            }
        )

    @asynccontextmanager
    async def client(
        self,
        *,
        observer: Observer | None = None,
        pacer: RequestPacer | None = None,
        composer: Composer | None = None,
        payloads: PayloadDecoder | None = None,
    ) -> AsyncIterator[NotehubClient]:
        """Own a normal client and its HTTP transport for the duration of a context."""
        self._ensure_open()
        async with httpx.AsyncClient(transport=self.transport()) as http:
            async with NotehubClient(
                "simulation-token",
                base_url="https://simulation.invalid",
                http_client=http,
                observer=observer,
                pacer=pacer,
                composer=composer,
                payloads=payloads,
            ) as client:
                yield client

    def transport(self) -> SimulationTransport:
        """Return a public local-only transport for advanced client injection."""
        self._ensure_open()
        from .transport import SimulationTransport

        return SimulationTransport(self)

    def fail_next(
        self,
        method: str,
        path: str,
        *,
        status_code: int | None = 500,
        retry_after: str | None = None,
    ) -> None:
        """Queue one failure for the next matching method and relative /v1/ path."""
        self._ensure_open()
        self._faults.append(Fault(method, path, status_code, retry_after))

    def _effective_environment(self, project: str, uid: str) -> dict[str, str]:
        state = self._state(project, uid)
        values = dict(state.definition.defaults)
        values.update(self._project_env[project])
        fleets = [self._fleets[(project, f)] for f in state.definition.fleet_uids]
        for fleet in sorted(fleets, key=lambda f: (f.label.casefold(), f.uid), reverse=True):
            values.update(self._fleet_env[(project, fleet.uid)])
        values.update(state.environment)
        return values

    def snapshot(self) -> Mapping[str, Any]:
        """Return a recursively immutable, detached snapshot for assertions/inspection."""
        self._ensure_open()
        return freeze(
            {
                "now": self.now,
                "projects": {uid: dict(values) for uid, values in self._project_env.items()},
                "fleets": dict(self._fleet_env),
                "events": self._events,
                "devices": {
                    key: {
                        "environment": state.environment,
                        "synced_environment": state.synced_environment,
                        "outbound": state.outbound,
                        "inbound": state.inbound,
                        "device_inbound": state.delivered,
                        "sessions": state.sessions,
                        "readings": state.readings,
                        "steps": state.steps,
                    }
                    for key, state in self._states.items()
                },
            }
        )

    def close(self) -> None:
        """Invalidate this run and all of its handles and transports."""
        self._closed = True
        self._cursors.clear()

    def __enter__(self) -> Self:
        self._ensure_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __rich_repr__(self) -> Iterator[object]:
        yield "now", self.now
        yield "devices", len(self._states)
        yield "closed", self.closed


@dataclass(frozen=True, slots=True)
class SimulatedDevice:
    """A live Notecard handle for explicit local queue and sync workflows."""

    simulation: Simulation = field(repr=False)
    project_uid: str
    uid: str

    def __post_init__(self) -> None:
        self.simulation._state(self.project_uid, self.uid)

    def to_notehub_target(self) -> DeviceTarget:
        """Address this device through the normal client composition protocol."""
        return DeviceTarget(self.project_uid, self.uid)

    def to_notehub_identifier(self) -> str:
        """Return the device identifier."""
        return self.uid

    def note(self, notefile: str) -> NoteTarget:
        """Address an inbound queue Note through the normal client."""
        return NoteTarget(self.project_uid, self.uid, identifier(notefile))

    def queue(self, notefile: str, body: object) -> None:
        """Queue one outbound .qo Note, using normal body composition adapters."""
        state = self._outbound_state(notefile)
        note = QueuedNote(self.project_uid, self.uid, notefile, resolve_note_body(body))
        state.outbound.append(self.simulation._note(note))

    def queue_many(self, notefile: str, bodies: Iterable[object]) -> None:
        """Validate the destination, then consume bodies lazily.

        If a later body or the iterable fails, earlier accepted Notes remain
        queued. Each append still requires an open simulation.
        """
        self._outbound_state(notefile)
        for body in bodies:
            self.queue(notefile, body)

    def _outbound_state(self, notefile: str) -> _DeviceState:
        state = self.simulation._state(self.project_uid, self.uid)
        if not notefile.endswith(".qo"):
            raise ValueError("outbound Notefile must end in .qo")
        return state

    @property
    def readings(self) -> Mapping[str, Any]:
        """Return detached current readings, also visible through client device reads."""
        return freeze(self.simulation._state(self.project_uid, self.uid).readings)

    def step(self) -> StepResult:
        """Invoke this device's behavior and apply its validated result atomically.

        A failed step leaves library-owned state unchanged. Behavior objects own
        their private state and must manage recovery from their own exceptions.
        """
        run = self.simulation
        state = run._state(self.project_uid, self.uid)
        if state.behavior is None:
            raise ValueError(f"no behavior bound to device: {self.uid}")
        context = StepContext(
            self.project_uid,
            self.uid,
            run.now,
            state.steps + 1,
            state.readings,
            self.environment,
            tuple(state.delivered),
        )
        result = state.behavior(context)
        if not isinstance(result, StepResult):
            raise TypeError("behavior must return StepResult")
        available = {note["note"] for note in state.delivered}
        if unknown := set(result.consumed) - available:
            raise ValueError(f"consumed unknown command IDs: {', '.join(sorted(unknown))}")
        # Normalize all bodies before allocating IDs or touching queues.
        notes = [
            QueuedNote(self.project_uid, self.uid, note.file, note.body) for note in result.outbound
        ]
        queued = [run._note(note) for note in notes]
        state.readings.update(result.readings)
        state.outbound.extend(queued)
        state.delivered[:] = [n for n in state.delivered if n["note"] not in result.consumed]
        state.steps += 1
        return result

    def sync(self) -> SyncResult:
        """Transfer queues and refresh environment; does not execute host commands."""
        run = self.simulation
        state = run._state(self.project_uid, self.uid)
        session = run._id("session")
        sent, received = len(state.outbound), len(state.inbound)
        for note in state.outbound:
            run._events.append(
                {
                    **note,
                    "body": resolve_note_body(note["body"]),
                    "app": self.project_uid,
                    "device": self.uid,
                    "event": run._id("event"),
                    "session": session,
                    "received": run.now.timestamp(),
                    "sn": state.definition.serial_number,
                    "best_id": state.definition.serial_number or self.uid,
                    "product": state.definition.product_uid,
                }
            )
        state.outbound.clear()
        state.delivered.extend(state.inbound)
        state.inbound.clear()
        state.synced_environment = run._effective_environment(self.project_uid, self.uid)
        state.last_activity = run.now.isoformat()
        state.sessions.append(
            {
                "session": session,
                "session_began": int(run.now.timestamp()),
                "device": self.uid,
                "transport": "simulation",
            }
        )
        return SyncResult(session, sent, received)

    @property
    def environment(self) -> Mapping[str, str]:
        """Device defaults until the first sync, then the last synchronized values."""
        state = self.simulation._state(self.project_uid, self.uid)
        return freeze(state.synced_environment if state.sessions else state.definition.defaults)

    def receive(self, notefile: str, *, delete: bool = True) -> Mapping[str, Any] | None:
        """Read the first delivered .qi Note; consume it unless explicitly peeking."""
        state = self.simulation._state(self.project_uid, self.uid)
        if not notefile.endswith(".qi"):
            raise ValueError("inbound Notefile must end in .qi")
        for index, note in enumerate(state.delivered):
            if note["file"] == notefile:
                result = freeze(note)
                if delete:
                    del state.delivered[index]
                return result
        return None

    def __rich_repr__(self) -> Iterator[object]:
        yield "project_uid", self.project_uid
        yield "uid", self.uid
