"""Optional Textual terminal workbench runtime."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import TYPE_CHECKING

from ..helpers import runtime_imports

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ...client import NotehubClient
    from .app import NotehubApp
    from .state import TUIOptions

with runtime_imports("tui", "textual", "rich"):
    import rich  # noqa: F401
    import textual  # noqa: F401


def create_app(
    *, client: NotehubClient | None = None, options: TUIOptions | None = None
) -> NotehubApp:
    """Create an embeddable workbench, borrowing an injected client."""
    from .app import create_app as factory

    return factory(client=client, options=options)


def main(args: Sequence[str] | None = None) -> None:
    """Start the terminal workbench with optional scope and credentials."""
    from .state import TUIOptions

    parser = argparse.ArgumentParser(
        prog="notehub-client tui", description="Explore Notehub in a terminal workbench."
    )
    parser.add_argument("--project", default=os.getenv("NOTEHUB_PROJECT_UID"))
    parser.add_argument("--token-file", type=Path, help="UTF-8 bearer token file (not stdin)")
    parser.add_argument("--demo", action="store_true", help="use synthetic local data; no network")
    values = parser.parse_args(args)
    if values.token_file == Path("-"):
        parser.error("--token-file requires a path; stdin belongs to the terminal interface")
    create_app(
        options=TUIOptions(
            project_uid=values.project, token_file=values.token_file, demo=values.demo
        )
    ).run()


__all__ = ["create_app", "main"]
