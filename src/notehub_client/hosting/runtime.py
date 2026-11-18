"""Managed execution of configured application-owned async components."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable, AsyncIterator, Coroutine
from itertools import count
from typing import Any, Self, TypeVar

from ..client import NotehubClient
from ..observe import (
    ClientEvent,
    ComponentCancelled,
    ComponentFailed,
    ComponentFinished,
    ComponentStarted,
    notify,
    operation_context,
)
from ..payloads import PayloadDecoder
from ..typing import Event, Observer
from ..typing.hosting import Component, EventSink
from .models import ComponentEmission, ComponentScope

__all__ = ["ComponentContext", "ComponentHost"]

LOGGER = logging.getLogger(__name__)
TaskT = TypeVar("TaskT")
_RUN_IDS = count(1)


class _ComponentEvents:
    """Expose one pull-based iterator for the lifetime of its component."""

    def __init__(self, iterator: AsyncIterator[Event]) -> None:
        self._iterator: AsyncIterator[Event] | None = iterator

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Event:
        iterator = self._iterator
        if iterator is None:
            raise RuntimeError("component context is closed")
        event = await anext(iterator)
        if self._iterator is None:
            raise RuntimeError("component context is closed")
        return event

    def invalidate(self) -> None:
        self._iterator = None


class ComponentContext:
    """Communication facilities and lifetime-bound tasks for one component."""

    def __init__(
        self,
        *,
        run_id: int,
        name: str,
        scope: ComponentScope,
        client: NotehubClient,
        events: AsyncIterator[Event],
        sink: EventSink,
    ) -> None:
        self._run_id = run_id
        self._name = name
        self._scope = scope
        self._client = client
        self._events = _ComponentEvents(events)
        self._sink = sink
        self._task_group: asyncio.TaskGroup | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._accepting_tasks = False
        self._open = True

    @property
    def run_id(self) -> int:
        """Unique process-local identifier for this run."""
        return self._run_id

    @property
    def name(self) -> str:
        """Human-readable name supplied when the component was hosted."""
        return self._name

    @property
    def scope(self) -> ComponentScope:
        """Project and optional fleet/device context for this run."""
        return self._scope

    @property
    def client(self) -> NotehubClient:
        """The borrowed Notehub client supplied to the host."""
        return self._client

    @property
    def payloads(self) -> PayloadDecoder:
        """The decoder configured on the supplied Notehub client."""
        return self._client.payloads

    @property
    def events(self) -> AsyncIterator[Event]:
        """The run's pull-based event iterator, available until source cleanup."""
        return self._events

    async def emit(self, payload: object) -> None:
        """Await delivery of one application event to the supplied sink."""
        if not self._open:
            raise RuntimeError("component context is closed")
        await self._sink(ComponentEmission(self.run_id, self.name, self.scope, payload))

    def spawn(
        self, coroutine: Coroutine[Any, Any, TaskT], *, name: str | None = None
    ) -> asyncio.Task[TaskT]:
        """Start a managed child, closing its coroutine if scheduling is rejected."""
        group = self._task_group
        if not self._open or not self._accepting_tasks or group is None:
            coroutine.close()
            raise RuntimeError("component is not accepting child tasks")
        try:
            task = group.create_task(coroutine, name=name)
        except BaseException:
            # TaskGroup can begin aborting before the host stops accepting tasks.
            # Python 3.11/3.12 do not close coroutines rejected in that state.
            coroutine.close()
            raise
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _begin(self, group: asyncio.TaskGroup) -> None:
        self._task_group = group
        self._accepting_tasks = True

    def _stop_spawning(self) -> None:
        self._accepting_tasks = False

    def _cancel_children(self) -> None:
        for task in tuple(self._tasks):
            if not task.cancelling():
                task.cancel()

    def _close(self) -> None:
        self._accepting_tasks = False
        self._open = False
        self._task_group = None
        self._events.invalidate()


class ComponentHost:
    """Run user components with supplied inputs and managed async lifetimes."""

    def __init__(self, client: NotehubClient, *, observer: Observer | None = None) -> None:
        self._client = client
        self._observer = observer

    async def run(
        self,
        component: Component,
        *,
        name: str,
        scope: ComponentScope,
        events: AsyncIterable[Event],
        emit: EventSink,
    ) -> None:
        """Run one component to completion, closing its iterator and child tasks."""
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a nonempty string")
        if not isinstance(scope, ComponentScope):
            raise TypeError("scope must be a ComponentScope")
        if not callable(component) or not callable(emit):
            raise TypeError("component and emit must be callable")

        run_id = next(_RUN_IDS)
        label = f"component:{name}#{run_id}"
        notify(self._observer, ComponentStarted(run_id, name))
        iterator: AsyncIterator[Event] | None = None
        context: ComponentContext | None = None
        primary: BaseException | None = None
        terminal: ClientEvent
        try:
            with operation_context(label):
                iterator = aiter(events)
                context = ComponentContext(
                    run_id=run_id,
                    name=name,
                    scope=scope,
                    client=self._client,
                    events=iterator,
                    sink=emit,
                )
                # TODO(hosting-shutdown): Design an opt-in diagnostic for a slow
                # child join or iterator close. Exercise both phases and retain
                # primary-error precedence and ownership of all pending work.
                async with asyncio.TaskGroup() as tasks:
                    context._begin(tasks)
                    component_task = tasks.create_task(component(context), name=label)
                    try:
                        await component_task
                    finally:
                        context._stop_spawning()
                    # TaskGroup handles cancellation on exceptional exits.
                    context._cancel_children()
        except BaseException as error:
            primary = error
            terminal = (
                ComponentCancelled(run_id, name)
                if isinstance(error, asyncio.CancelledError)
                else ComponentFailed(run_id, name, type(error).__name__)
            )
        else:
            terminal = ComponentFinished(run_id, name)
        finally:
            if context is not None:
                context._close()
            cleanup_error: BaseException | None = None
            if iterator is not None:
                try:
                    close = getattr(iterator, "aclose", None)
                    if close is not None:
                        with operation_context(label):
                            await close()
                except BaseException as error:
                    cleanup_error = error
            if cleanup_error is not None:
                if primary is None:
                    primary = cleanup_error
                    terminal = (
                        ComponentCancelled(run_id, name)
                        if isinstance(cleanup_error, asyncio.CancelledError)
                        else ComponentFailed(run_id, name, type(cleanup_error).__name__)
                    )
                else:
                    LOGGER.warning(
                        "Component event iterator cleanup failed: error_type=%r",
                        type(cleanup_error).__name__,
                    )
        notify(self._observer, terminal)
        if primary is not None:
            raise primary
