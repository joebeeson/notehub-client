"""Callable Notehub operations exposed as FastMCP tools."""

from __future__ import annotations

from dataclasses import dataclass

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.tools import tool

from ...client import NotehubClient
from ...filters import CursorPagination, Pagination, Query
from ...typing import (
    Device,
    DevicesResponse,
    EventsResponse,
    FleetsResponse,
    LatestResponse,
    Project,
    ProjectsResponse,
    SessionResponse,
)


@dataclass(frozen=True, slots=True)
class MCPToolContext:
    """Runtime dependencies supplied to tools or explicit Python callers."""

    client: NotehubClient
    default_project_uid: str | None = None


def _current_tool_context(ctx: Context = CurrentContext()) -> MCPToolContext:
    """Resolve this server's Notehub client from its FastMCP lifespan state."""
    return ctx.lifespan_context["notehub"]


def _project_uid(value: str | None, default: str | None) -> str:
    """Choose an explicit project UID or the configured server default."""
    project_uid = value or default
    if not project_uid:
        raise ValueError("project_uid is required or set NOTEHUB_PROJECT_UID")
    return project_uid


def _page_size(value: int) -> int:
    """Validate the page size used by bounded list tools."""
    if type(value) is not int or not 1 <= value <= 100:
        raise ValueError("page_size must be between 1 and 100")
    return value


@tool(
    title="List projects",
    tags={"notehub", "read", "projects"},
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def list_projects(
    page_size: int = 50,
    page_num: int = 1,
    runtime: MCPToolContext = Depends(_current_tool_context),
) -> ProjectsResponse:
    """List one page of accessible projects (page_size 1–100, page_num is one-based)."""
    page = Pagination(page_size=_page_size(page_size), page_num=page_num)
    return await runtime.client.projects.list(pageSize=page.page_size, pageNum=page_num)


@tool(
    title="Get project",
    tags={"notehub", "read", "projects"},
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_project(
    project_uid: str | None = None,
    runtime: MCPToolContext = Depends(_current_tool_context),
) -> Project:
    """Get a project by UID, using the configured default when omitted."""
    selected_project = _project_uid(project_uid, runtime.default_project_uid)
    return await runtime.client.projects.get(selected_project)


@tool(
    title="List fleets",
    tags={"notehub", "read", "fleets"},
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def list_fleets(
    project_uid: str | None = None,
    runtime: MCPToolContext = Depends(_current_tool_context),
) -> FleetsResponse:
    """List fleets for a project, using the configured default when omitted."""
    selected_project = _project_uid(project_uid, runtime.default_project_uid)
    return await runtime.client.fleets.list(selected_project)


@tool(
    title="List devices",
    tags={"notehub", "read", "devices"},
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def list_devices(
    project_uid: str | None = None,
    page_size: int = 50,
    page_num: int = 1,
    runtime: MCPToolContext = Depends(_current_tool_context),
) -> DevicesResponse:
    """List one device page; project defaults from NOTEHUB_PROJECT_UID, page_size 1–100."""
    selected_project = _project_uid(project_uid, runtime.default_project_uid)
    page = Pagination(page_size=_page_size(page_size), page_num=page_num)
    return await runtime.client.devices.list(selected_project, pagination=page)


@tool(
    title="Get device",
    tags={"notehub", "read", "devices"},
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_device(
    device_uid: str,
    project_uid: str | None = None,
    runtime: MCPToolContext = Depends(_current_tool_context),
) -> Device:
    """Get a device by UID, using the configured project default when omitted."""
    selected_project = _project_uid(project_uid, runtime.default_project_uid)
    return await runtime.client.devices.get(selected_project, device_uid)


@tool(
    title="List device sessions",
    tags={"notehub", "read", "devices"},
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def list_device_sessions(
    device_uid: str,
    project_uid: str | None = None,
    runtime: MCPToolContext = Depends(_current_tool_context),
) -> SessionResponse:
    """List device sessions using the configured project default; this is not live connectivity proof."""
    selected_project = _project_uid(project_uid, runtime.default_project_uid)
    return await runtime.client.devices.list_sessions(selected_project, device_uid)


@tool(
    title="Get latest device events",
    tags={"notehub", "read", "devices", "events"},
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_device_latest(
    device_uid: str,
    project_uid: str | None = None,
    runtime: MCPToolContext = Depends(_current_tool_context),
) -> LatestResponse:
    """Get latest received events using the configured project default; this is not physical state proof."""
    selected_project = _project_uid(project_uid, runtime.default_project_uid)
    return await runtime.client.devices.latest(selected_project, device_uid)


@tool(
    title="List events",
    tags={"notehub", "read", "events"},
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def list_events(
    project_uid: str | None = None,
    page_size: int = 50,
    cursor: str = "0",
    event_uid: str | None = None,
    device_uid: str | None = None,
    file: str | None = None,
    runtime: MCPToolContext = Depends(_current_tool_context),
) -> EventsResponse:
    """List a project event page; pass next_cursor back unchanged to continue."""
    selected_project = _project_uid(project_uid, runtime.default_project_uid)
    selectors = Query()
    if event_uid:
        selectors = selectors.events(event_uid)
    if device_uid:
        selectors = selectors.devices(device_uid)
    if file:
        selectors = selectors.files(file)
    page = CursorPagination(cursor=cursor, page_size=_page_size(page_size))
    return await runtime.client.events.list(selected_project, pagination=page, filters=selectors)


NOTEHUB_TOOLS = (
    list_projects,
    get_project,
    list_fleets,
    list_devices,
    get_device,
    list_device_sessions,
    get_device_latest,
    list_events,
)

__all__ = [
    "NOTEHUB_TOOLS",
    "MCPToolContext",
    "get_device",
    "get_device_latest",
    "get_project",
    "list_device_sessions",
    "list_devices",
    "list_events",
    "list_fleets",
    "list_projects",
]
