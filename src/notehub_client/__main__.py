"""Package runtime dispatcher and console-script entry points."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .errors import NotehubDependencyError
from .runtimes import run_runtime, runtime_names


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


if __name__ == "__main__":
    main()
