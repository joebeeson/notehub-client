"""Register reusable MCP prompts and capability guidance."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

_EVIDENCE_GUIDANCE = (
    "Separate returned facts from hypotheses and recommendations, and name fields that "
    "support each fact. Notehub events and sessions are evidence of Notehub activity, "
    "not proof of current physical device state."
)
_BLUES_DATA_BOUNDARY = (
    "Do not send raw event bodies, device environment values, or project data to Blues "
    "Expert. Ask before sending a sanitized product question."
)


def register_workflows(server: FastMCP, default_project_uid: str | None = None) -> None:
    """Attach the capability resource and task prompts to a FastMCP server."""

    @server.resource(
        "notehub://capabilities",
        name="Notehub client capabilities",
        description="Identifiers, read scopes, page limits, and data semantics for this server.",
        mime_type="text/markdown",
        tags={"notehub", "capabilities"},
        annotations={"audience": ["assistant"], "priority": 0.7},
    )
    def capabilities() -> str:
        """Describe the local Notehub read catalog and its boundaries."""
        project = (
            f"Configured default project: {default_project_uid}."
            if default_project_uid
            else "No project default is configured; provide project_uid to project-scoped tools."
        )
        return (
            "# Notehub client capabilities\n\n"
            "This server reads live Notehub data through the notehub-client library. "
            "It exposes no write tools and no generic HTTP request tool.\n\n"
            f"{project}\n\n"
            "Use Notehub identifiers as returned by the API (for example, app:… and dev:…). "
            "Lists return one page at a time; page_size is 1–100. Event pages use an opaque "
            "cursor that should be passed back unchanged as next_cursor.\n\n"
            "URI resources: notehub://projects/{project_uid} and "
            "notehub://projects/{project_uid}/devices/{device_uid}.\n\n"
            "Available reads: projects (list_projects, get_project), fleets (list_fleets), "
            "devices (list_devices, get_device, list_device_sessions, get_device_latest), "
            "and events (list_events, filterable by event UID, device UID, or Notefile).\n\n"
            f"{_EVIDENCE_GUIDANCE}\n\n"
            "Blues Expert may be configured separately or mounted under blues_expert_. "
            f"{_BLUES_DATA_BOUNDARY} The Notehub PAT is never sent to Blues Expert."
        )

    @server.prompt(
        name="investigate_notehub_event",
        title="Investigate a Notehub event",
        description="Gather local event evidence, then explain facts and safe next steps.",
        tags={"notehub", "investigation", "events"},
    )
    def investigate_event(
        event_uid: str, project_uid: str | None = None, device_uid: str = ""
    ) -> str:
        """Guide a read-only investigation of one Notehub event."""
        project = project_uid or default_project_uid
        scope = f"project {project}" if project else "the project the user specifies"
        device = (
            f" Also inspect device {device_uid} with get_device and list_device_sessions if useful."
            if device_uid
            else " Identify its device from the event and inspect it only if useful."
        )
        ask_for_project = (
            " Ask for a project UID before calling project-scoped tools." if not project else ""
        )
        return (
            f"Investigate event {event_uid} in {scope}. Call list_events with event_uid="
            f"{event_uid} to retrieve it.{device}{ask_for_project} {_EVIDENCE_GUIDANCE} "
            f"{_BLUES_DATA_BOUNDARY} This workflow is read-only."
        )

    @server.prompt(
        name="inspect_notehub_device",
        title="Inspect a Notehub device",
        description="Review a device's recent Notehub activity using bounded reads.",
        tags={"notehub", "inspection", "devices"},
    )
    def inspect_device(device_uid: str, project_uid: str | None = None) -> str:
        """Guide a read-only inspection of a device's Notehub activity."""
        project = project_uid or default_project_uid
        scope = f"project {project}" if project else "the project the user specifies"
        ask_for_project = (
            " Ask for a project UID before calling project-scoped tools." if not project else ""
        )
        return (
            f"Inspect device {device_uid} in {scope}. Use get_device, list_device_sessions, "
            "and get_device_latest. Use list_events with device_uid only when you need more "
            f"history, following next_cursor unchanged.{ask_for_project} {_EVIDENCE_GUIDANCE} "
            f"{_BLUES_DATA_BOUNDARY} This workflow is read-only."
        )

    @server.prompt(
        name="plan_notehub_integration",
        title="Plan a Notehub integration",
        description="Use Blues documentation and local project reads to plan an integration.",
        tags={"notehub", "planning", "integration"},
    )
    def plan_integration(goal: str, project_uid: str | None = None) -> str:
        """Guide planning for an integration with Notehub."""
        project = project_uid or default_project_uid
        project_step = (
            f" First inspect project {project} with get_project and relevant list tools."
            if project
            else " Ask for a project UID before inspecting project-specific state."
        )
        return (
            f"Plan a Notehub integration for this goal: {goal}.{project_step} Prefer public "
            "notehub-client facades and typed models; identify API gaps instead of using "
            "generic requests. Check current Blues product and API documentation. Share only "
            "the user's goal and public product terminology with Blues Expert; ask before "
            "including project-derived details. Distinguish reads from proposed writes, and "
            "report Notehub API acceptance separately from device application."
        )


__all__ = ["register_workflows"]
