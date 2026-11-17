"""Shared runtime utilities and Rich presentation for observation events.

Install ``notehub-client[cli]`` to use :class:`RichProgressObserver`::

    from notehub_client.runtimes.helpers import RichProgressObserver

    with RichProgressObserver() as progress:
        async with NotehubClient(token, observer=progress) as client:
            async for event in progress.track(
                client.events.iter(project_uid), description="Project events"
            ):
                ...

The core client and its observation protocols do not import Rich.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, TypeVar

from ..client import NotehubClient
from ..errors import NotehubDependencyError
from ..helpers import RequestPacer
from ..observe import (
    ComponentCancelled,
    ComponentFailed,
    ComponentFinished,
    ComponentStarted,
    IterationAdvanced,
    IterationCancelled,
    IterationFailed,
    IterationFinished,
    IterationStarted,
    RequestCancelled,
    RequestFailed,
    RequestFinished,
    RequestStarted,
    observe_async_iterable,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Iterator

    from rich.progress import TaskID

    from ..observe import ClientEvent
    from .typing import ClientFactory

ItemT = TypeVar("ItemT")
ResultT = TypeVar("ResultT")
DecoratorT = TypeVar("DecoratorT", bound=Callable[..., Any])


def click_options(
    *options: Callable[[DecoratorT], DecoratorT],
) -> Callable[[DecoratorT], DecoratorT]:
    """Compose Click option decorators in declaration order.

    The first option passed is applied outermost, which keeps reusable option
    bundles readable at command definitions without importing Click here.
    """

    def decorate(function: DecoratorT) -> DecoratorT:
        for option in reversed(options):
            function = option(function)
        return function

    return decorate


def run_async(awaitable: Awaitable[ResultT]) -> ResultT:
    """Run one async operation from a synchronous runtime entry point."""
    return asyncio.run(awaitable)


def create_client(
    token: str,
    *,
    client_factory: ClientFactory = NotehubClient,
    pacer: RequestPacer | None = None,
) -> NotehubClient:
    """Create a runtime client, sharing a pacer with the standard client.

    Custom factories keep their one-token calling convention, which is useful
    for tests and embedding runtimes without requiring a pacer parameter.
    """
    if client_factory is NotehubClient:
        return NotehubClient(token, pacer=pacer)
    return client_factory(token)


def configure_rich_logging(level: int | str = logging.WARNING) -> None:
    """Install Rich's colored log handler when a runtime owns process output.

    Existing logging handlers are respected. Rich is imported only when this
    process-level helper is called.
    """
    with runtime_imports("cli", "rich"):
        from rich.logging import RichHandler

    if isinstance(level, str):
        log_level = logging.getLevelNamesMapping().get(level.upper())
        if not isinstance(log_level, int):
            raise ValueError("level must be a recognized logging level")
    else:
        log_level = level
    root = logging.getLogger()
    if not root.handlers:
        handler = RichHandler(
            show_time=True,
            show_level=True,
            show_path=True,
            enable_link_path=True,
            rich_tracebacks=True,
            tracebacks_show_locals=False,
            markup=False,
        )
        logging.basicConfig(level=log_level, format="%(message)s", handlers=[handler])
    else:
        root.setLevel(log_level)


@contextmanager
def runtime_imports(runtime: str, *optional_modules: str) -> Iterator[None]:
    """Translate missing declared runtime imports into an install hint."""
    try:
        yield
    except ModuleNotFoundError as error:
        missing_root = (error.name or "").partition(".")[0]
        if missing_root not in optional_modules:
            raise
        raise NotehubDependencyError(f"{runtime} runtime", runtime, missing_root) from error


class RichProgressObserver:
    """Render requests, iterations, and hosted component lifetimes in Rich progress."""

    def __init__(self) -> None:
        with runtime_imports("cli", "rich"):
            from rich.progress import (
                BarColumn,
                Progress,
                SpinnerColumn,
                TaskProgressColumn,
                TextColumn,
                TimeElapsedColumn,
            )

        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
        )
        self._request_tasks: dict[int, TaskID] = {}
        self._iteration_tasks: dict[int, TaskID] = {}
        self._component_tasks: dict[int, TaskID] = {}
        self._request_summary_task: TaskID | None = None
        self._request_count = 0
        self._request_failures = 0
        self._request_cancelled = 0

    def __enter__(self) -> RichProgressObserver:
        self.progress.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.progress.stop()

    def on_event(self, event: ClientEvent, /) -> None:
        """Update Rich tasks for request and iteration lifecycle events."""
        if isinstance(event, RequestStarted):
            operation = f"{event.operation} :: " if event.operation else ""
            task_id = self.progress.add_task(f"{operation}{event.method} {event.path}", total=None)
            self._request_tasks[event.request_id] = task_id
        elif isinstance(event, (RequestFinished, RequestFailed, RequestCancelled)):
            task_id = self._request_tasks.pop(event.request_id, None)
            if task_id is not None:
                self.progress.remove_task(task_id)
            self._request_count += 1
            if isinstance(event, RequestFailed) or (
                isinstance(event, RequestFinished) and not event.successful
            ):
                self._request_failures += 1
            if isinstance(event, RequestCancelled):
                self._request_cancelled += 1
            self._update_request_summary()
        elif isinstance(event, IterationStarted):
            task_id = self.progress.add_task(f"{event.description} :: 0 items", total=event.total)
            self._iteration_tasks[event.iteration_id] = task_id
        elif isinstance(event, ComponentStarted):
            task_id = self.progress.add_task(f"Component :: {event.name}", total=None)
            self._component_tasks[event.run_id] = task_id
        elif isinstance(event, IterationAdvanced):
            task_id = self._iteration_tasks.get(event.iteration_id)
            if task_id is not None:
                self.progress.update(
                    task_id,
                    completed=event.item_count,
                    description=f"{event.description} :: {event.item_count} items",
                )
        elif isinstance(event, (IterationFinished, IterationFailed, IterationCancelled)):
            task_id = self._iteration_tasks.pop(event.iteration_id, None)
            if task_id is not None:
                self.progress.remove_task(task_id)
        elif isinstance(event, (ComponentFinished, ComponentFailed, ComponentCancelled)):
            task_id = self._component_tasks.pop(event.run_id, None)
            if task_id is not None:
                self.progress.remove_task(task_id)

    async def track(
        self,
        iterable: AsyncIterable[ItemT],
        *,
        description: str,
        total: int | None = None,
    ) -> AsyncIterator[ItemT]:
        """Wrap an async iterable and show its item count while it is consumed."""
        async for item in observe_async_iterable(
            iterable,
            observer=self,
            description=description,
            total=total,
        ):
            yield item

    def _update_request_summary(self) -> None:
        description = f"Requests: {self._request_count} complete"
        if self._request_failures:
            description += f", {self._request_failures} failed"
        if self._request_cancelled:
            description += f", {self._request_cancelled} cancelled"
        if self._request_summary_task is None:
            self._request_summary_task = self.progress.add_task(
                description,
                total=max(self._request_count, 1),
                completed=self._request_count,
            )
        else:
            self.progress.update(
                self._request_summary_task,
                description=description,
                total=max(self._request_count, 1),
                completed=self._request_count,
            )


__all__ = [
    "RichProgressObserver",
    "click_options",
    "configure_rich_logging",
    "create_client",
    "run_async",
    "runtime_imports",
]
