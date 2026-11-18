"""Framework-neutral request, component, and async-iteration observation hooks."""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from itertools import count
from typing import TYPE_CHECKING, TypeAlias, TypeVar

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator, Iterator

    from .typing.observe import Observer

LOGGER = logging.getLogger(__name__)
_ACTIVE_OPERATION: ContextVar[str | None] = ContextVar("notehub_active_operation", default=None)
_ITERATION_IDS = count(1)
ItemT = TypeVar("ItemT")


@dataclass(frozen=True, slots=True)
class RequestStarted:
    """A Notehub request attempt began, including pacing and authentication."""

    request_id: int
    method: str
    path: str
    operation: str | None = None


@dataclass(frozen=True, slots=True)
class RequestFinished:
    """A Notehub HTTP response was received."""

    request_id: int
    method: str
    path: str
    status_code: int
    duration_ms: float
    successful: bool
    operation: str | None = None


@dataclass(frozen=True, slots=True)
class RequestFailed:
    """A Notehub HTTP request failed before a response was received."""

    request_id: int
    method: str
    path: str
    error_type: str
    duration_ms: float
    operation: str | None = None


@dataclass(frozen=True, slots=True)
class RequestCancelled:
    """A Notehub request was cancelled before a response was received."""

    request_id: int
    method: str
    path: str
    duration_ms: float
    operation: str | None = None


@dataclass(frozen=True, slots=True)
class IterationStarted:
    """An observed async iterable started producing items."""

    iteration_id: int
    description: str
    total: int | None


@dataclass(frozen=True, slots=True)
class IterationAdvanced:
    """An observed async iterable produced another item."""

    iteration_id: int
    description: str
    item_count: int
    total: int | None


@dataclass(frozen=True, slots=True)
class IterationFinished:
    """An observed async iterable finished normally."""

    iteration_id: int
    description: str
    item_count: int
    total: int | None


@dataclass(frozen=True, slots=True)
class IterationFailed:
    """An observed async iterable raised an exception."""

    iteration_id: int
    description: str
    item_count: int
    error_type: str


@dataclass(frozen=True, slots=True)
class IterationCancelled:
    """An observed async iterable was cancelled or closed early."""

    iteration_id: int
    description: str
    item_count: int


@dataclass(frozen=True, slots=True)
class ComponentStarted:
    """A hosted application component began running."""

    run_id: int
    name: str


@dataclass(frozen=True, slots=True)
class ComponentFinished:
    """A hosted application component returned successfully."""

    run_id: int
    name: str


@dataclass(frozen=True, slots=True)
class ComponentFailed:
    """A hosted application component or managed task failed."""

    run_id: int
    name: str
    error_type: str


@dataclass(frozen=True, slots=True)
class ComponentCancelled:
    """A hosted application component was cancelled."""

    run_id: int
    name: str


ClientEvent: TypeAlias = (
    RequestStarted
    | RequestFinished
    | RequestFailed
    | RequestCancelled
    | IterationStarted
    | IterationAdvanced
    | IterationFinished
    | IterationFailed
    | IterationCancelled
    | ComponentStarted
    | ComponentFinished
    | ComponentFailed
    | ComponentCancelled
)


def notify(observer: Observer | None, event: ClientEvent) -> None:
    """Send an event best-effort so diagnostics cannot change request results."""
    if observer is None:
        return
    try:
        observer.on_event(event)
    except Exception as error:
        LOGGER.warning("Notehub observer failed: error_type=%r", type(error).__name__)


async def observe_async_iterable(
    iterable: AsyncIterable[ItemT],
    *,
    observer: Observer | None,
    description: str,
    total: int | None = None,
) -> AsyncGenerator[ItemT, None]:
    """Yield an async iterable while emitting framework-neutral lifecycle events.

    The ``description`` is also made available to Notehub requests performed
    while fetching the next item, allowing observers to relate requests to an
    iteration without exposing query parameters, headers, or payloads.

    Use ``contextlib.aclosing`` when the consumer may stop early. Closing this
    generator calls the source iterator's ``aclose`` method when available.
    Terminal events follow source cleanup. Cleanup exceptions are logged by
    type, while cancellation during cleanup propagates as cancellation.
    """
    if not description:
        raise ValueError("description must be nonempty")
    if total is not None and (type(total) is not int or total < 0):
        raise ValueError("total must be a nonnegative integer or None")

    iteration_id = next(_ITERATION_IDS)
    item_count = 0
    iterator: AsyncIterator[ItemT] | None = None
    notify(observer, IterationStarted(iteration_id, description, total))
    try:
        try:
            iterator = aiter(iterable)
            while True:
                operation_token = _ACTIVE_OPERATION.set(description)
                try:
                    item = await iterator.__anext__()
                except StopAsyncIteration:
                    break
                finally:
                    _ACTIVE_OPERATION.reset(operation_token)
                item_count += 1
                notify(observer, IterationAdvanced(iteration_id, description, item_count, total))
                yield item
        finally:
            await _close_observed_iterator(iterator)
    except (asyncio.CancelledError, GeneratorExit):
        notify(observer, IterationCancelled(iteration_id, description, item_count))
        raise
    except Exception as error:
        notify(
            observer,
            IterationFailed(iteration_id, description, item_count, type(error).__name__),
        )
        raise
    else:
        notify(observer, IterationFinished(iteration_id, description, item_count, total))


async def _close_observed_iterator(iterator: AsyncIterator[ItemT] | None) -> None:
    try:
        close = getattr(iterator, "aclose", None)
        if close is not None:
            await close()
    except Exception as error:
        LOGGER.warning(
            "Observed async iterable cleanup failed: error_type=%r",
            type(error).__name__,
        )


def active_operation() -> str | None:
    """Return the current observed iteration label for request event correlation."""
    return _ACTIVE_OPERATION.get()


@contextmanager
def operation_context(description: str) -> Iterator[None]:
    """Set a request operation label for work performed in this context.

    Child asyncio tasks inherit the label. Nested contexts restore their parent
    label on exit, including when the enclosed operation fails.
    """
    if not description:
        raise ValueError("description must be nonempty")
    token = _ACTIVE_OPERATION.set(description)
    try:
        yield
    finally:
        _ACTIVE_OPERATION.reset(token)


__all__ = [
    "ClientEvent",
    "ComponentCancelled",
    "ComponentFailed",
    "ComponentFinished",
    "ComponentStarted",
    "IterationAdvanced",
    "IterationCancelled",
    "IterationFailed",
    "IterationFinished",
    "IterationStarted",
    "RequestCancelled",
    "RequestFailed",
    "RequestFinished",
    "RequestStarted",
    "active_operation",
    "notify",
    "observe_async_iterable",
    "operation_context",
]
