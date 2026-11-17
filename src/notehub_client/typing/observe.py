"""Structural observer protocol for client and hosted-component lifecycle events."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..observe import ClientEvent

__all__ = ["Observer"]


class Observer(Protocol):
    """A structural sink for client request and iteration events."""

    def on_event(self, event: ClientEvent, /) -> None:
        """Consume an event without blocking the client operation."""
        ...
