"""Command-line entry point for the local HTTP API runtime."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from ..helpers import runtime_imports

if TYPE_CHECKING:
    from collections.abc import Sequence

with runtime_imports("api", "uvicorn"):
    import uvicorn


def main(args: Sequence[str] | None = None) -> None:
    """Start the API server, bound to loopback unless explicitly configured."""
    parser = argparse.ArgumentParser(prog="notehub-client api")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="bind port (default: 8000)")
    options = parser.parse_args(args)

    from . import create_app

    uvicorn.run(create_app(), host=options.host, port=options.port)


__all__ = ["main"]
