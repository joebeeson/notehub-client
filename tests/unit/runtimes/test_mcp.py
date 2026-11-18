"""MCP read tool behavior without remote Notehub access."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
import respx
from fastmcp import Client
from mcp.types import TextResourceContents

from notehub_client.runtimes.mcp import create_server


class FakeClient:
    calls: list[tuple[str, object]] = []

    def __init__(self, token: str) -> None:
        assert token == "test-pat"  # noqa: S105
        self.projects = SimpleNamespace(list=self.list_projects)
        self.devices = SimpleNamespace(list=self.list_devices)
        self.events = SimpleNamespace(list=self.list_events)

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        pass

    async def list_projects(self, **params: object) -> dict[str, object]:
        self.calls.append(("projects", params))
        return {
            "projects": [{"created": "2025-01-01T00:00:00Z", "label": "Demo", "uid": "app:demo"}]
        }

    async def list_devices(self, project_uid: str, *, pagination: object) -> dict[str, object]:
        self.calls.append(("devices", (project_uid, pagination)))
        return {
            "devices": [
                {
                    "fleet_uids": [],
                    "product_uid": "product:demo",
                    "provisioned": "true",
                    "uid": "dev:demo",
                }
            ],
            "has_more": False,
        }

    async def list_events(self, project_uid: str, **params: object) -> dict[str, object]:
        self.calls.append(("events", (project_uid, params)))
        return {"events": [{"event": "evt:demo"}], "has_more": False, "next_cursor": "1"}


@pytest.mark.asyncio
async def test_mcp_exposes_bounded_reads_through_existing_facades() -> None:
    FakeClient.calls = []
    server = create_server("test-pat", client_factory=FakeClient)  # type: ignore[arg-type]
    async with Client(server) as client:
        tool_specs = {tool.name: tool for tool in await client.list_tools()}
        names = set(tool_specs)
        assert names == {
            "list_projects",
            "get_project",
            "list_fleets",
            "list_devices",
            "get_device",
            "list_device_sessions",
            "get_device_latest",
            "list_events",
        }
        device_schema = tool_specs["list_devices"].output_schema
        assert device_schema is not None
        assert device_schema["required"] == ["devices", "has_more"]
        projects = await client.call_tool("list_projects", {"page_size": 12})
        devices = await client.call_tool(
            "list_devices", {"project_uid": "app:demo", "page_size": 10}
        )
        events = await client.call_tool(
            "list_events",
            {"project_uid": "app:demo", "cursor": "123", "device_uid": "dev:demo"},
        )

    project_content = projects.structured_content
    device_content = devices.structured_content
    event_content = events.structured_content
    assert project_content is not None
    assert device_content is not None
    assert event_content is not None
    assert project_content["projects"][0]["uid"] == "app:demo"
    assert device_content["devices"][0]["uid"] == "dev:demo"
    assert event_content["events"][0]["event"] == "evt:demo"
    assert FakeClient.calls[0] == ("projects", {"pageSize": 12, "pageNum": 1})
    assert FakeClient.calls[1][0] == "devices"
    assert FakeClient.calls[2][0] == "events"
    event_params = FakeClient.calls[2][1][1]  # type: ignore[index]
    assert event_params["filters"].to_query_params()["deviceUID"] == ("dev:demo",)
    assert event_params["pagination"].cursor == "123"


@pytest.mark.asyncio
async def test_mcp_rejects_unbounded_page_size_without_calling_notehub() -> None:
    FakeClient.calls = []
    server = create_server("test-pat", client_factory=FakeClient)  # type: ignore[arg-type]
    async with Client(server) as client:
        result = await client.call_tool(
            "list_events", {"project_uid": "app:demo", "page_size": 101}, raise_on_error=False
        )
    assert result.is_error
    assert FakeClient.calls == []


@pytest.mark.asyncio
@respx.mock
async def test_mcp_project_and_device_resources_match_the_read_tools() -> None:
    project = {"uid": "app:demo", "created": "2025-01-01T00:00:00Z", "label": "Demo"}
    device = {
        "uid": "dev:demo",
        "product_uid": "product:demo",
        "fleet_uids": [],
        "provisioned": "true",
    }
    base = "https://api.notefile.net/v1/projects/app:demo"
    project_route = respx.get(base).mock(return_value=httpx.Response(200, json=project))
    device_route = respx.get(f"{base}/devices/dev:demo").mock(
        return_value=httpx.Response(200, json=device)
    )
    server = create_server("test-pat", default_project_uid="app:demo")
    async with Client(server) as client:
        templates = {t.uri_template: t.mime_type for t in await client.list_resource_templates()}
        assert templates == {
            "notehub://projects/{project_uid}": "application/json",
            "notehub://projects/{project_uid}/devices/{device_uid}": "application/json",
        }
        for uri, tool, args, expected in (
            ("notehub://projects/app:demo", "get_project", {}, project),
            (
                "notehub://projects/app:demo/devices/dev:demo",
                "get_device",
                {"device_uid": "dev:demo"},
                device,
            ),
        ):
            (resource,) = await client.read_resource(uri)
            assert isinstance(resource, TextResourceContents)
            assert resource.mime_type == "application/json"
            tool_result = await client.call_tool(tool, args)
            assert json.loads(resource.text) == tool_result.structured_content == expected
    assert project_route.call_count == device_route.call_count == 2
