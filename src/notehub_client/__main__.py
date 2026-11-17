"""Package runtime dispatcher and console-script entry points."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from .errors import NotehubDependencyError
from .runtimes import run_runtime, runtime_names

if TYPE_CHECKING:
    from collections.abc import Sequence


def _run(runtime: str, args: Sequence[str] | None, *, prog: str) -> None:
    try:
        run_runtime(runtime, args)
    except NotehubDependencyError as error:
        raise SystemExit(f"{prog}: {error}") from None


def main(argv: Sequence[str] | None = None) -> None:
    """Dispatch ``notehub-client <runtime> [runtime args...]``."""
    args = list(sys.argv[1:] if argv is None else argv)
    names = runtime_names()

    if args and args[0] in names:
        _run(args[0], args[1:], prog="notehub-client")
        return

    parser = argparse.ArgumentParser(
        prog="notehub-client",
        description="Start a Notehub client runtime.",
    )
    parser.add_argument("runtime", choices=names, help="runtime to start")
    parser.parse_args(args)


def cli_main() -> None:
    """Run the CLI through the legacy ``notehub`` console script."""
    _run("cli", None, prog="notehub")


def tui_main() -> None:
    """Run the TUI through the dedicated ``notehub-client-tui`` script."""
    _run("tui", None, prog="notehub-client-tui")


def api_main() -> None:
    """Run the API through the dedicated ``notehub-client-api`` script."""
    _run("api", None, prog="notehub-client-api")


def web_main() -> None:
    """Run the browser dashboard through its dedicated console script."""
    _run("web", None, prog="notehub-client-web")


def mcp_main() -> None:
    """Run the read-only MCP server through its dedicated console script."""
    _run("mcp", None, prog="notehub-client-mcp")


if __name__ == "__main__":
    main()
