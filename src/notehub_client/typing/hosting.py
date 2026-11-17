"""Structural contracts for hosted application components."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..hosting.models import ComponentEmission
    from ..hosting.runtime import ComponentContext

__all__ = ["Component", "EventSink"]


class Component(Protocol):
    """An application-owned async callable managed for one hosted run."""

    async def __call__(self, context: ComponentContext, /) -> None:
        """Run the component until it completes or is cancelled."""
        ...


class EventSink(Protocol):
    """An async sink for application events emitted by a component."""

    async def __call__(self, _emission: ComponentEmission, /) -> None:
        """Accept one application event and provide backpressure to its caller."""
        ...
