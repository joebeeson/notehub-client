"""Click-based command-line runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..helpers import runtime_imports

if TYPE_CHECKING:
    from collections.abc import Sequence

with runtime_imports("cli", "click", "rich"):
    from .commands import create_cli


def main(args: Sequence[str] | None = None) -> None:
    """Run the CLI command group with the given argument vector."""
    create_cli(configure_logging=True).main(
        args=list(args) if args is not None else None,
        prog_name="notehub",
    )


__all__ = ["create_cli", "main"]
