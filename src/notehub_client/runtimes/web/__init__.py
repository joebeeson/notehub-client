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


class _DashboardServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config, *, url: str, launch_browser: bool) -> None:
        super().__init__(config)
        self._url = url
        self._launch_browser = launch_browser

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if not self.started or self.should_exit:
            return
        print(f"Dashboard: {self._url}", flush=True)
        if self._launch_browser:
            threading.Thread(target=webbrowser.open, args=(self._url,), daemon=True).start()


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
    # Keep the selected port reserved until Uvicorn takes over the same socket.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", options.port))
        port = listener.getsockname()[1]
        fragment = urlencode(
            {"secret": app.state.bootstrap_secret, "project": options.project or ""}
        )
        url = f"http://127.0.0.1:{port}/dashboard#{fragment}"
        server = _DashboardServer(
            uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="on"),
            url=url,
            launch_browser=options.launch_browser,
        )
        server.run(sockets=[listener])
        if not server.started:
            raise SystemExit("notehub-client web: dashboard startup failed")


__all__ = ["main"]
