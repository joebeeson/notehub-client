"""Session, command, and resource-route contracts for the local HTTP app."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.routing import APIRoute

from notehub_client.runtimes import api
from notehub_client.runtimes.api import create_app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI, Request

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


async def _session_stream(app: FastAPI, session_id: str, last_event_id: str) -> AsyncGenerator[str]:
    route = next(
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/api/projects/{project_uid}/stream/events"
    )
    request = SimpleNamespace(
        app=app,
        cookies={"notehub_session": session_id},
        headers={"last-event-id": last_event_id},
        is_disconnected=AsyncMock(return_value=False),
    )
    response = await route.endpoint(cast("Request", request), "app:test", mode="live")
    return response.body_iterator


async def _stream_body(client: FakeClient, last_event_id: str) -> AsyncGenerator[str]:
    app = create_app()
    app.state.notehub_sessions["stream"] = {
        "mode": "live",
        "client": client,
        "workspace_changed": asyncio.Event(),
    }
    return await _session_stream(app, "stream", last_event_id)


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
async def test_event_stream_emits_cursor_batch() -> None:
    body = await _stream_body(FakeClient("launch-token"), "cursor-previous")
    batch = await anext(body)
    assert "id: cursor-next\nevent: batch" in batch
    assert '"evt:test"' in batch
    await body.aclose()


@pytest.mark.asyncio
async def test_event_stream_resumes_from_empty_page_checkpoint() -> None:
    client = FakeClient("launch-token")
    fetch = AsyncMock(
        side_effect=[
            {"events": [], "has_more": False, "next_cursor": "empty"},
            {"events": [{"event": "after-empty"}], "has_more": False, "next_cursor": "next"},
        ]
    )
    client.events.list = fetch
    body = await _stream_body(client, "start")
    heartbeat = await anext(body)
    assert heartbeat.startswith("id: empty\nevent: heartbeat\n")
    await body.aclose()

    checkpoint = heartbeat.splitlines()[0].removeprefix("id: ")
    resumed = await _stream_body(client, checkpoint)
    batch = await anext(resumed)
    assert batch.startswith("id: next\nevent: batch\n")
    assert '"after-empty"' in batch
    assert [call.kwargs["pagination"].cursor for call in fetch.await_args_list] == [
        "start",
        "empty",
    ]
    await resumed.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bad_cursor", "code"),
    [
        pytest.param("", "cursor_missing", id="missing"),
        pytest.param("step", "cursor_repeated", id="same-cursor"),
        pytest.param("start", "cursor_repeated", id="earlier-cursor"),
        pytest.param("cursor\n", "cursor_invalid", id="line-break"),
        pytest.param("cursor\0", "cursor_invalid", id="null"),
    ],
)
async def test_event_stream_retries_bad_checkpoint_after_poll_interval(
    monkeypatch: pytest.MonkeyPatch, bad_cursor: str, code: str
) -> None:
    real_wait = asyncio.wait
    timeouts: list[float] = []

    async def wait(tasks, *, timeout=None, **kwargs):
        if timeout is not None:
            timeouts.append(timeout)
            return await real_wait(tasks, timeout=0, **kwargs)
        return await real_wait(tasks, **kwargs)

    monkeypatch.setattr(api, "asyncio", SimpleNamespace(**(vars(asyncio) | {"wait": wait})))
    client = FakeClient("launch-token")
    fetch = AsyncMock(
        side_effect=[
            {"events": [], "has_more": True, "next_cursor": "step"},
            {"events": [], "has_more": True, "next_cursor": bad_cursor},
            {"events": [], "has_more": False, "next_cursor": "step"},
        ]
    )
    client.events.list = fetch
    body = await _stream_body(client, "start")
    assert (await anext(body)).startswith("id: step\nevent: heartbeat\n")
    assert await anext(body) == f'event: error\ndata: {{"code":"{code}"}}\n\n'
    assert timeouts == []
    assert (await anext(body)).startswith("id: step\nevent: heartbeat\n")
    assert timeouts == [60]
    assert [call.kwargs["pagination"].cursor for call in fetch.await_args_list] == [
        "start",
        "step",
        "step",
    ]
    await body.aclose()


@pytest.mark.asyncio
async def test_event_stream_quiets_when_session_client_closes() -> None:
    client = FakeClient("launch-token")
    client.events.list = AsyncMock(
        side_effect=RuntimeError("Cannot send a request, as the client has been closed.")
    )
    body = await _stream_body(client, "cursor-previous")
    with pytest.raises(StopAsyncIteration):
        await anext(body)


@pytest.mark.asyncio
async def test_simulation_switch_interrupts_idle_and_pending_live_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTEHUB_TOKEN", "launch-token")
    app = create_app(client_factory=cast("type[NotehubClient]", FakeClient))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as browser,
    ):
        boot = await browser.post(
            "/api/session/bootstrap", headers={"X-Launch-Secret": app.state.bootstrap_secret}
        )
        assert boot.status_code == 200
        session_id = browser.cookies["notehub_session"]
        live = app.state.notehub_sessions[session_id]["client"]
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        original_list = live.events.list

        async def wait_for_request(*args, **kwargs):
            if kwargs["pagination"].cursor != "pending":
                return await original_list(*args, **kwargs)
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        live.events.list = AsyncMock(side_effect=wait_for_request)
        idle = await _session_stream(app, session_id, "idle")
        pending = await _session_stream(app, session_id, "pending")
        assert (await anext(idle)).startswith("id: cursor-next\n")
        async with asyncio.timeout(2), asyncio.TaskGroup() as group:
            idle_frame = group.create_task(anext(idle))
            pending_frame = group.create_task(anext(pending))
            await entered.wait()
            started = await browser.post("/api/simulation/start", json={"name": "sensor"})
            assert started.status_code == 200

        assert idle_frame.result().startswith("event: workspace_changed\n")
        assert pending_frame.result().startswith("event: workspace_changed\n")
        assert cancelled.is_set()
        await idle.aclose()
        await pending.aclose()
        retry = await browser.get("/api/projects/app:test/stream/events?mode=live")
        assert retry.status_code == 204
        assert live.events.list.await_count == 2
        assert not live.closed

        stopped = await browser.post("/api/simulation/stop")
        assert stopped.json() == {"mode": "live", "authenticated": True}
        resumed = await _session_stream(app, session_id, "fresh")
        assert (await anext(resumed)).startswith("id: cursor-next\n")
        await resumed.aclose()
        assert app.state.notehub_sessions[session_id]["client"] is live
        assert live.events.list.await_count == 3
