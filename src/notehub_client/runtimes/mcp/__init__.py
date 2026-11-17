"""Composable read-only MCP runtime for Notehub and Blues Expert."""

from __future__ import annotations

import argparse
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from ...client import NotehubClient
from ...helpers import RequestPacer
from ..helpers import create_client, runtime_imports

with runtime_imports("mcp", "fastmcp"):
    from fastmcp import FastMCP

from .diagnostics import MCPDiagnosticsMiddleware, configure_mcp_logging
from .resources import register_notehub_resources
from .tools import NOTEHUB_TOOLS, MCPToolContext
from .workflows import register_workflows

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence

    from ..typing import ClientFactory


def create_server(
    token: str,
    *,
    client_factory: ClientFactory = NotehubClient,
    pacer: RequestPacer | None = None,
    default_project_uid: str | None = None,
    include_blues_expert: bool = False,
) -> FastMCP:
    """Compose Notehub reads, workflow prompts, and optional Blues docs tools."""
    if default_project_uid is None:
        default_project_uid = (os.getenv("NOTEHUB_PROJECT_UID") or "").strip() or None
    request_pacer = pacer if pacer is not None else RequestPacer()

    @asynccontextmanager
    async def lifespan(
        _server: FastMCP,
    ) -> AsyncGenerator[dict[str, MCPToolContext], None]:
        async with create_client(
            token, client_factory=client_factory, pacer=request_pacer
        ) as client:
            yield {
                "notehub": MCPToolContext(
                    client=client,
                    default_project_uid=default_project_uid,
                )
            }

    project_guidance = (
        f"Use {default_project_uid} as the default project when a project_uid argument is omitted. "
        "Callers may still provide another project UID."
        if default_project_uid
        else "Ask for a project UID before project-scoped reads when one was not provided."
    )
    server = FastMCP(
        "notehub-client",
        tools=NOTEHUB_TOOLS,
        middleware=[MCPDiagnosticsMiddleware()],
        lifespan=lifespan,
        instructions=(
            "Provides bounded, read-only Notehub project, fleet, device, session, and event reads. "
            f"{project_guidance} Do not infer current physical device state from received events. "
            "The hosted Blues Expert service is documentation only; never send it the Notehub "
            "PAT or raw project data without the user's approval."
        ),
    )
    register_notehub_resources(server)
    register_workflows(server, default_project_uid)

    if include_blues_expert:
        from fastmcp.server import create_proxy

        server.mount(create_proxy("https://mcp.blues.io/expert/mcp"), namespace="blues_expert")

    return server


def main(args: Sequence[str] | None = None) -> None:
    """Run the MCP server over stdio with a PAT from the environment."""
    parser = argparse.ArgumentParser(prog="notehub-client mcp")
    parser.add_argument(
        "--project",
        default=(os.getenv("NOTEHUB_PROJECT_UID") or "").strip() or None,
        help="Default project UID (defaults to NOTEHUB_PROJECT_UID).",
    )
    parser.add_argument(
        "--with-blues-expert",
        action="store_true",
        help="Mount hosted Blues Expert tools under the blues_expert_ namespace.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default="WARNING",
        help="Log MCP call timings and diagnostics to stderr (default: WARNING).",
    )
    options = parser.parse_args(args)
    configure_mcp_logging(options.log_level)
    token = (os.getenv("NOTEHUB_TOKEN") or "").strip()
    if not token:
        raise SystemExit("notehub-client mcp: set NOTEHUB_TOKEN")
    create_server(
        token,
        pacer=RequestPacer(),
        default_project_uid=options.project,
        include_blues_expert=options.with_blues_expert,
    ).run(transport="stdio")


__all__ = ["create_server", "main"]
