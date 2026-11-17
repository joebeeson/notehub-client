"""Optional local browser dashboard runtime."""

from __future__ import annotations

import argparse
import socket
import threading
import webbrowser
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from ..helpers import runtime_imports

if TYPE_CHECKING:
    from collections.abc import Sequence

with runtime_imports("web", "uvicorn"):
    import uvicorn


def main(args: Sequence[str] | None = None) -> None:
    """Start the loopback dashboard and print a one-time bootstrap URL."""
    parser = argparse.ArgumentParser(prog="notehub-client web")
    parser.add_argument("--port", type=int, default=0, help="local port (default: ephemeral)")
    launch = parser.add_mutually_exclusive_group()
    launch.add_argument(
        "--no-launch",
        dest="launch_browser",
        action="store_false",
        help="print the URL without opening a browser",
    )
    launch.add_argument(
        "--open", dest="launch_browser", action="store_true", help=argparse.SUPPRESS
    )
    parser.set_defaults(launch_browser=True)
    parser.add_argument("--project", help="initial project UID")
    parser.add_argument("--token-file", help="read a PAT from a local file")
    options = parser.parse_args(args)
    if options.port < 0 or options.port > 65535:
        parser.error("port must be between 0 and 65535")
    from ..api import create_app

    app = create_app(dashboard=True, token_file=options.token_file)
    port = options.port
    if port == 0:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
    fragment = urlencode({"secret": app.state.bootstrap_secret, "project": options.project or ""})
    url = f"http://127.0.0.1:{port}/dashboard#{fragment}"
    print(f"Dashboard: {url}", flush=True)
    if options.launch_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=port)


__all__ = ["main"]
