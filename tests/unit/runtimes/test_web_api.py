"""Session, command, and resource-route contracts for the local HTTP app."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import httpx
import pytest
from fastapi.routing import APIRoute

from notehub_client.runtimes.api import create_app

if TYPE_CHECKING:
    from fastapi import Request

    from notehub_client.client import NotehubClient


class FakeClient:
    def __init__(self, token: str) -> None:
        self.token = token
        self.closed = False
        self.projects = SimpleNamespace(list=self.list_projects, get=self.get_project)
        self.devices = SimpleNamespace(list=self.list_devices)
        self.events = SimpleNamespace(list=self.list_events)
        self.event_calls: list[tuple[str, dict[str, object]]] = []

    async def list_projects(self, **params: object) -> dict[str, object]:
        return {"projects": [{"uid": "app:test", "label": "Test project"}], "page": params}

    async def get_project(self, uid: str) -> dict[str, str]:
        return {"uid": uid, "label": "Test project"}

    async def list_devices(self, uid: str, *, pagination: object) -> dict[str, object]:
        return {"devices": [{"uid": "dev:test"}], "project": uid}

    async def list_events(self, uid: str, **params: object) -> dict[str, object]:
        self.event_calls.append((uid, params))
        return {
            "events": [{"event": "evt:test", "device": "dev:test"}],
            "has_more": False,
            "next_cursor": "cursor-next",
        }

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_bootstrap_read_commands_and_logout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTEHUB_TOKEN", "launch-token")
    app = create_app(client_factory=cast("type[NotehubClient]", FakeClient))
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            assert (await client.get("/api/projects")).status_code == 401
            boot = await client.post(
                "/api/session/bootstrap",
                headers={"X-Launch-Secret": app.state.bootstrap_secret},
            )
            assert boot.status_code == 200
            assert boot.json() == {"authenticated": True}
            assert "HttpOnly" in boot.headers["set-cookie"]
            assert "launch-token" not in boot.text
            read = await client.post(
                "/api/commands", json={"command": "projects.list", "args": {"page_size": 20}}
            )
            assert read.status_code == 200
            assert read.json()["projects"][0]["uid"] == "app:test"
            assert (await client.get("/api/projects/app:test")).json()["uid"] == "app:test"
            filtered = await client.get(
                "/api/projects/app:test/events", params={"deviceUID": "dev:test", "page_size": 12}
            )
            assert filtered.status_code == 200
            assert filtered.json()["events"][0]["event"] == "evt:test"
            assert (
                await client.post("/api/commands", json={"command": "notes.add_db", "args": {}})
            ).status_code == 400
            assert (await client.delete("/api/session")).json() == {"authenticated": False}
            assert (await client.get("/api/projects")).status_code == 401
            assert (
                await client.post("/api/session/token", json={"token": "new-pat"})
            ).status_code == 200
            assert (await client.get("/api/projects")).status_code == 200


@pytest.mark.asyncio
async def test_local_origin_and_argument_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTEHUB_TOKEN", "launch-token")
    app = create_app(client_factory=cast("type[NotehubClient]", FakeClient))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            denied = await client.post(
                "/api/session/bootstrap",
                headers={
                    "Origin": "https://other.example",
                    "X-Launch-Secret": app.state.bootstrap_secret,
                },
            )
            assert denied.status_code == 403
            await client.post(
                "/api/session/bootstrap", headers={"X-Launch-Secret": app.state.bootstrap_secret}
            )
            oversized = await client.post(
                "/api/commands", json={"command": "projects.list", "args": {"page_size": 1000}}
            )
            assert oversized.status_code == 400
            assert (
                await client.get("/api/projects", params={"page_size": 1000})
            ).status_code == 400


@pytest.mark.asyncio
async def test_event_stream_emits_cursor_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTEHUB_TOKEN", "launch-token")
    app = create_app(client_factory=cast("type[NotehubClient]", FakeClient))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            await client.post(
                "/api/session/bootstrap", headers={"X-Launch-Secret": app.state.bootstrap_secret}
            )

            class StreamRequest:
                cookies = {"notehub_session": client.cookies["notehub_session"]}
                headers = {"last-event-id": "cursor-previous"}

                async def is_disconnected(self) -> bool:
                    return False

            route = next(
                route
                for route in app.routes
                if isinstance(route, APIRoute)
                and route.path == "/api/projects/{project_uid}/stream/events"
            )
            response = await route.endpoint(
                cast("Request", StreamRequest()), "app:test", FakeClient("launch-token")
            )
            batch = await anext(response.body_iterator)
            assert "id: cursor-next\nevent: batch" in batch
            assert '"evt:test"' in batch
            await response.body_iterator.aclose()


@pytest.mark.asyncio
async def test_event_stream_quiets_when_session_client_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTEHUB_TOKEN", "launch-token")
    app = create_app(client_factory=cast("type[NotehubClient]", FakeClient))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as browser:
            await browser.post(
                "/api/session/bootstrap", headers={"X-Launch-Secret": app.state.bootstrap_secret}
            )

            class StreamRequest:
                cookies = {"notehub_session": browser.cookies["notehub_session"]}
                headers = {"last-event-id": "cursor-previous"}

                async def is_disconnected(self) -> bool:
                    return False

            async def closed_list(*_args: object, **_kwargs: object) -> object:
                raise RuntimeError("Cannot send a request, as the client has been closed.")

            client = FakeClient("launch-token")
            client.events.list = closed_list
            route = next(
                route
                for route in app.routes
                if isinstance(route, APIRoute)
                and route.path == "/api/projects/{project_uid}/stream/events"
            )
            response = await route.endpoint(cast("Request", StreamRequest()), "app:test", client)
            with pytest.raises(StopAsyncIteration):
                await anext(response.body_iterator)
