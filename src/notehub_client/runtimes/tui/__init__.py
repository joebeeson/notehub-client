"""Textual terminal UI runtime scaffold."""

from __future__ import annotations

from collections.abc import Sequence


def main(args: Sequence[str] | None = None) -> None:
    """Start the future Textual UI runtime."""
    import textual  # noqa: F401

    del args
    raise SystemExit("The Textual runtime is scaffolded but has no interface yet.")


__all__ = ["main"]
