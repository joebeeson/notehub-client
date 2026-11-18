import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing

import pytest

from notehub_client.observe import (
    ClientEvent,
    IterationAdvanced,
    IterationCancelled,
    IterationFailed,
    IterationFinished,
    IterationStarted,
    observe_async_iterable,
)
from notehub_client.runtimes.helpers import RichProgressObserver


class Collector:
    def __init__(self) -> None:
        self.events: list[ClientEvent] = []

    def on_event(self, event: ClientEvent) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_iterator_creation_failure_emits_a_terminal_event() -> None:
    class BrokenSource:
        def __aiter__(self) -> AsyncIterator[int]:
            raise RuntimeError("source unavailable")

    observer = Collector()
    tracked = observe_async_iterable(BrokenSource(), observer=observer, description="source")
    with pytest.raises(RuntimeError, match="source unavailable"):
        await anext(tracked)

    started, failed = observer.events
    assert isinstance(started, IterationStarted)
    assert failed == IterationFailed(started.iteration_id, "source", 0, "RuntimeError")


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["exhausted", "failed", "closed"])
async def test_cleanup_failure_preserves_iteration_outcome(
    ending: str, caplog: pytest.LogCaptureFixture
) -> None:
    observer = Collector()

    class Source:
        def __aiter__(self):
            return self

        async def __anext__(self) -> int:
            if len(observer.events) == 1:
                return 1
            if ending == "failed":
                raise ValueError("read failed")
            raise StopAsyncIteration

        async def aclose(self) -> None:
            assert len(observer.events) == 2
            raise RuntimeError("synthetic sensitive detail")

    tracked = observe_async_iterable(Source(), observer=observer, description="source", total=1)
    assert await anext(tracked) == 1
    started, advanced = observer.events
    assert isinstance(started, IterationStarted)
    assert advanced == IterationAdvanced(started.iteration_id, "source", 1, 1)

    if ending == "closed":
        await tracked.aclose()
        terminal = IterationCancelled(started.iteration_id, "source", 1)
    elif ending == "failed":
        with pytest.raises(ValueError, match="read failed"):
            await anext(tracked)
        terminal = IterationFailed(started.iteration_id, "source", 1, "ValueError")
    else:
        with pytest.raises(StopAsyncIteration):
            await anext(tracked)
        terminal = IterationFinished(started.iteration_id, "source", 1, 1)

    assert observer.events == [started, advanced, terminal]
    assert "cleanup failed: error_type='RuntimeError'" in caplog.text
    assert "synthetic sensitive detail" not in caplog.text


@pytest.mark.asyncio
async def test_cancellation_during_cleanup_emits_cancelled_instead_of_finished() -> None:
    close_started = asyncio.Event()

    class Source:
        def __aiter__(self):
            return self

        async def __anext__(self) -> int:
            raise StopAsyncIteration

        async def aclose(self) -> None:
            close_started.set()
            await asyncio.Event().wait()

    observer = Collector()
    tracked = observe_async_iterable(Source(), observer=observer, description="source")
    pull = asyncio.ensure_future(anext(tracked))
    try:
        await asyncio.wait_for(close_started.wait(), timeout=2)
        (started,) = observer.events
        assert isinstance(started, IterationStarted)
    finally:
        pull.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pull
    assert observer.events == [started, IterationCancelled(started.iteration_id, "source", 0)]


@pytest.mark.asyncio
async def test_closing_rich_track_releases_source_and_progress_immediately() -> None:
    closed = False

    async def source() -> AsyncGenerator[int, None]:
        nonlocal closed
        try:
            yield 1
            yield 2
        finally:
            closed = True

    observer = RichProgressObserver()
    async with aclosing(observer.track(source(), description="source")) as tracked:
        assert await anext(tracked) == 1
        assert observer.progress.tasks

    assert closed
    assert not observer.progress.tasks
