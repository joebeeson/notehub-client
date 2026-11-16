"""Click-based command-line runtime."""

from __future__ import annotations

from collections.abc import Sequence


def _create_cli():
    """Build the Click command lazily so missing extras reach the dispatcher."""
    import click

    @click.group()
    @click.version_option(package_name="notehub-client")
    def cli() -> None:
        """Work with Blues Notehub from the command line."""

    return cli


def main(args: Sequence[str] | None = None) -> None:
    """Run the CLI command group with the given argument vector."""
    _create_cli().main(args=list(args) if args is not None else None, prog_name="notehub")


__all__ = ["main"]
