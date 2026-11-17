"""Structural typing contracts shared by optional runtimes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..client import NotehubClient

__all__ = ["ClientFactory", "RuntimeModule"]


class ClientFactory(Protocol):
    """Create a client for one bearer token."""

    def __call__(self, token: str, /) -> NotehubClient:
        """Return a client configured with the supplied bearer token."""
        ...


class RuntimeModule(Protocol):
    """Entry point exposed by a lazily loaded runtime module."""

    def main(self, args: Sequence[str] | None = None) -> None:
        """Run this runtime with optional command-line arguments."""
        ...
