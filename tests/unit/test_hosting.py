"""Hosted component inputs, emissions, and managed async lifetimes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import cast

import pytest

from notehub_client import NotehubClient, hosting, observe
from notehub_client.errors import NotehubError
from notehub_client.typing import Event


@dataclass(frozen=True)
class Reading:
    value: float


class Failure(NotehubError):
    pass


def scope() -> hosting.ComponentScope:
    return hosting.ComponentScope(project_uid="app:test", fleet_uid="fleet:one")


async def event_source(*events: Event) -> AsyncIterator[Event]:
    """Yield exactly the supplied events, including an empty event sequence."""
    for event in events:
        yield event


@pytest.mark.asyncio
async def test_component_receives_identity_preserving_events_and_awaited_emission() -> None:
    client = NotehubClient("token")
    first = {"body": {"value": 1}}
    second = {"body": {"value": 2}}
    consumed = []
    received = []
    gate = asyncio.Event()
    sink_started = asyncio.Event()

    async def events() -> AsyncIterator[Event]:
        consumed.append("started")
        yield cast(Event, first)
        yield cast(Event, second)

    async def emit(item: hosting.ComponentEmission) -> None:
        sink_started.set()
        await gate.wait()
        received.append(item)

    async def component(context: hosting.ComponentContext) -> None:
        assert context.client is client
        assert context.payloads is client.payloads
        assert context.scope == scope()
        assert [item async for item in context.events] == [first, second]
        emission_task = asyncio.create_task(context.emit("alarm"))
        await sink_started.wait()
        assert not emission_task.done()
        gate.set()
        await emission_task

    try:
        await hosting.ComponentHost(client).run(
            component, name="water-monitor", scope=scope(), events=events(), emit=emit
        )
        assert consumed == ["started"]
        assert len(received) == 1
        assert received[0].payload == "alarm"
        assert received[0].scope == scope()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_configured_callable_run_ids_and_lifecycle_observer() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.contexts = []

        async def __call__(self, context: hosting.ComponentContext) -> None:
            self.contexts.append(context)
            await barrier.wait()

    class Collector:
        def __init__(self) -> None:
            self.events = []

        def on_event(self, event: observe.ClientEvent) -> None:
            self.events.append(event)

    client = NotehubClient("token")
    observer = Collector()
    component = Recorder()
    host = hosting.ComponentHost(client, observer=observer)
    barrier = asyncio.Barrier(2)

    async def sink(_: hosting.ComponentEmission) -> None:
        pass

    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(
                host.run(
                    component, name="recorder", scope=scope(), events=event_source(), emit=sink
                )
            )
            group.create_task(
                host.run(
                    component, name="recorder", scope=scope(), events=event_source(), emit=sink
                )
            )
    finally:
        await client.aclose()

    assert component.contexts[0].run_id != component.contexts[1].run_id
    assert [type(event) for event in observer.events].count(observe.ComponentStarted) == 2
    assert [type(event) for event in observer.events].count(observe.ComponentFinished) == 2
    assert component.contexts[0] is not component.contexts[1]
    assert {item.run_id for item in component.contexts} == {
        event.run_id for event in observer.events
    }


@pytest.mark.asyncio
async def test_child_tasks_are_cancelled_and_iterator_is_closed_on_return() -> None:
    client = NotehubClient("token")
    ready = asyncio.Event()
    finalized = asyncio.Event()
    closed = asyncio.Event()
    emitted = []

    async def events() -> AsyncIterator[Event]:
        try:
            yield cast(Event, {"body": {}})
            await asyncio.Event().wait()
        finally:
            closed.set()

    async def sink(item: hosting.ComponentEmission) -> None:
        emitted.append(item)

    async def child(context: hosting.ComponentContext) -> None:
        ready.set()
        try:
            await asyncio.Event().wait()
        finally:
            finalized.set()
            await context.emit("child-stopped")

    async def component(context: hosting.ComponentContext) -> None:
        context.spawn(child(context), name="managed-child")
        async for _ in context.events:
            break
        await ready.wait()

    try:
        await hosting.ComponentHost(client).run(
            component, name="worker", scope=scope(), events=events(), emit=sink
        )
        assert finalized.is_set()
        assert closed.is_set()
        assert [item.payload for item in emitted] == ["child-stopped"]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_child_failure_propagates_and_cancels_component() -> None:
    client = NotehubClient("token")
    child_finalized = asyncio.Event()
    component_finalized = asyncio.Event()

    async def sink(_: hosting.ComponentEmission) -> None:
        pass

    async def bad_child() -> None:
        raise Failure("child")

    async def component(context: hosting.ComponentContext) -> None:
        async def child() -> None:
            try:
                await bad_child()
            finally:
                child_finalized.set()

        context.spawn(child())
        try:
            await asyncio.Event().wait()
        finally:
            component_finalized.set()

    try:
        with pytest.raises(ExceptionGroup) as caught:
            await hosting.ComponentHost(client).run(
                component, name="failing-worker", scope=scope(), events=event_source(), emit=sink
            )
        assert any(isinstance(error, Failure) for error in caught.value.exceptions)
        assert child_finalized.is_set()
        assert component_finalized.is_set()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_caller_cancellation_closes_iterator_and_runs_child_finalizer() -> None:
    client = NotehubClient("token")
    started = asyncio.Event()
    child_finalized = asyncio.Event()
    source_closed = asyncio.Event()

    async def source() -> AsyncIterator[Event]:
        try:
            yield cast(Event, {"body": {}})
            await asyncio.Event().wait()
        finally:
            source_closed.set()

    async def sink(_: hosting.ComponentEmission) -> None:
        pass

    async def component(context: hosting.ComponentContext) -> None:
        async def child() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                child_finalized.set()

        context.spawn(child())
        await anext(context.events)
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        hosting.ComponentHost(client).run(
            component, name="cancel-me", scope=scope(), events=source(), emit=sink
        )
    )
    try:
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert child_finalized.is_set()
        assert source_closed.is_set()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_source_component_and_sink_errors_reach_caller() -> None:
    client = NotehubClient("token")

    async def source() -> AsyncIterator[Event]:
        yield cast(Event, {})
        raise Failure("source")

    async def source_component(context: hosting.ComponentContext) -> None:
        async for _ in context.events:
            pass

    async def failing_sink(_: hosting.ComponentEmission) -> None:
        raise Failure("sink")

    async def emitting(context: hosting.ComponentContext) -> None:
        await context.emit({"private": "payload"})

    try:
        with pytest.raises(ExceptionGroup) as source_error:
            await hosting.ComponentHost(client).run(
                source_component, name="source", scope=scope(), events=source(), emit=failing_sink
            )
        assert isinstance(source_error.value.exceptions[0], Failure)
        with pytest.raises(ExceptionGroup) as sink_error:
            await hosting.ComponentHost(client).run(
                emitting, name="sink", scope=scope(), events=event_source(), emit=failing_sink
            )
        assert isinstance(sink_error.value.exceptions[0], Failure)

        async def fail(_: hosting.ComponentContext) -> None:
            raise Failure("component")

        with pytest.raises(ExceptionGroup) as component_error:
            await hosting.ComponentHost(client).run(
                fail, name="failure", scope=scope(), events=event_source(), emit=failing_sink
            )
        assert isinstance(component_error.value.exceptions[0], Failure)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_operation_label_is_set_for_component_and_restored() -> None:
    client = NotehubClient("token")
    seen = []

    async def sink(_: hosting.ComponentEmission) -> None:
        pass

    async def component(_: hosting.ComponentContext) -> None:
        seen.append(observe.active_operation() or "")

    assert observe.active_operation() is None
    try:
        await hosting.ComponentHost(client).run(
            component, name="irrigation", scope=scope(), events=event_source(), emit=sink
        )
        assert observe.active_operation() is None
    finally:
        await client.aclose()
    assert seen[0].startswith("component:irrigation#")


@pytest.mark.asyncio
async def test_emit_is_rejected_after_run_and_scope_validation() -> None:
    client = NotehubClient("token")
    saved = []

    async def sink(_: hosting.ComponentEmission) -> None:
        pass

    async def component(context: hosting.ComponentContext) -> None:
        saved.append(context)

    try:
        await hosting.ComponentHost(client).run(
            component, name="done", scope=scope(), events=event_source(), emit=sink
        )
        with pytest.raises(RuntimeError, match="closed"):
            await saved[0].emit("late")
        with pytest.raises(RuntimeError, match="not accepting child tasks"):
            child_coroutine = asyncio.sleep(0)
            saved[0].spawn(child_coroutine)
        with pytest.raises(AttributeError):
            setattr(saved[0], "name", "changed")
        assert getattr(child_coroutine, "cr_frame") is None
    finally:
        await client.aclose()
    with pytest.raises(ValueError):
        hosting.ComponentScope(project_uid="")


@pytest.mark.asyncio
async def test_observer_failure_isolation_and_iterator_close_failure(caplog) -> None:
    client = NotehubClient("token")
    completed = []

    class BrokenObserver:
        def on_event(self, _: observe.ClientEvent) -> None:
            raise Failure("diagnostics only")

    class BrokenIterator:
        def __init__(self) -> None:
            self.close_calls = 0

        def __aiter__(self) -> BrokenIterator:
            return self

        async def __anext__(self) -> Event:
            raise StopAsyncIteration

        async def aclose(self) -> None:
            self.close_calls += 1
            raise Failure("private-cleanup-detail")

    async def sink(_: hosting.ComponentEmission) -> None:
        pass

    async def component(_: hosting.ComponentContext) -> None:
        completed.append(True)

    try:
        broken_iterator = BrokenIterator()
        with pytest.raises(Failure) as caught:
            await hosting.ComponentHost(client, observer=BrokenObserver()).run(
                component,
                name="cleanup-failure",
                scope=scope(),
                events=broken_iterator,  # type: ignore[arg-type]
                emit=sink,
            )
        assert str(caught.value) == "private-cleanup-detail"
        assert broken_iterator.close_calls == 1
        assert completed == [True]

        async def failing_component(_: hosting.ComponentContext) -> None:
            raise Failure("component detail")

        primary_iterator = BrokenIterator()
        with pytest.raises(ExceptionGroup) as primary:
            await hosting.ComponentHost(client).run(
                failing_component,
                name="primary-and-cleanup-failure",
                scope=scope(),
                events=primary_iterator,  # type: ignore[arg-type]
                emit=sink,
            )
        assert any(str(error) == "component detail" for error in primary.value.exceptions)
        assert primary_iterator.close_calls == 1
        assert "Component event iterator cleanup failed" in caplog.text
        assert "error_type='Failure'" in caplog.text
        assert "private-cleanup-detail" not in caplog.text

        await hosting.ComponentHost(client, observer=BrokenObserver()).run(
            component,
            name="observer-failure",
            scope=scope(),
            events=event_source(),
            emit=sink,
        )
        assert completed == [True, True]
    finally:
        await client.aclose()


def test_rich_progress_observer_tracks_and_clears_component_runs() -> None:
    from notehub_client.runtimes.helpers import RichProgressObserver

    observer = RichProgressObserver()
    observer.on_event(observe.ComponentStarted(1001, "irrigation"))
    assert 1001 in observer._component_tasks
    observer.on_event(observe.ComponentFinished(1001, "irrigation"))
    assert 1001 not in observer._component_tasks


@pytest.mark.asyncio
async def test_iterator_cleanup_cancellation_is_reported_as_run_cancellation() -> None:
    class CancelledIterator:
        def __aiter__(self) -> CancelledIterator:
            return self

        async def __anext__(self) -> Event:
            raise StopAsyncIteration

        async def aclose(self) -> None:
            raise asyncio.CancelledError

    class Collector:
        def __init__(self) -> None:
            self.events = []

        def on_event(self, event: observe.ClientEvent) -> None:
            self.events.append(event)

    client = NotehubClient("token")
    observer = Collector()

    async def component(_: hosting.ComponentContext) -> None:
        pass

    async def sink(_: hosting.ComponentEmission) -> None:
        pass

    try:
        with pytest.raises(asyncio.CancelledError):
            await hosting.ComponentHost(client, observer=observer).run(
                component,
                name="cancelled-cleanup",
                scope=scope(),
                events=CancelledIterator(),  # type: ignore[arg-type]
                emit=sink,
            )
    finally:
        await client.aclose()
    assert [type(item) for item in observer.events] == [
        observe.ComponentStarted,
        observe.ComponentCancelled,
    ]
