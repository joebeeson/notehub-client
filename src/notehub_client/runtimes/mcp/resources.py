"""URI-addressable Notehub project and device reads for FastMCP."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from fastmcp import Context

from .tools import MCPToolContext, get_device, get_project

if TYPE_CHECKING:
    from fastmcp import FastMCP


def _notehub_context(ctx: Context) -> MCPToolContext:
    """Return this server's shared Notehub client and project defaults."""
    return ctx.lifespan_context["notehub"]


def _json_resource(value: Any) -> str:
    """Serialize one typed wire response as an MCP JSON resource."""
    return json.dumps(value, ensure_ascii=False, indent=2)


def register_notehub_resources(server: FastMCP) -> None:
    """Attach project and device URI templates backed by the public tool calls."""

    @server.resource(
        "notehub://projects/{project_uid}",
        name="Notehub project",
        title="Notehub project",
        description="The current Notehub project record for a project UID.",
        mime_type="application/json",
        tags={"notehub", "read", "projects"},
        annotations={"audience": ["assistant"], "priority": 0.7},
    )
    async def project(project_uid: str, ctx: Context) -> str:
        """Read a project selected by its UID in the resource URI."""
        result = await get_project(
            project_uid=project_uid,
            runtime=_notehub_context(ctx),
        )
        return _json_resource(result)

    @server.resource(
        "notehub://projects/{project_uid}/devices/{device_uid}",
        name="Notehub device",
        title="Notehub device",
        description="The current Notehub device record within a project.",
        mime_type="application/json",
        tags={"notehub", "read", "devices"},
        annotations={"audience": ["assistant"], "priority": 0.7},
    )
    async def device(project_uid: str, device_uid: str, ctx: Context) -> str:
        """Read a device selected by its project and device UIDs."""
        result = await get_device(
            project_uid=project_uid,
            device_uid=device_uid,
            runtime=_notehub_context(ctx),
        )
        return _json_resource(result)


__all__ = ["register_notehub_resources"]
