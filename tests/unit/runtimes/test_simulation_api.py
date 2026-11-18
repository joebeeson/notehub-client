"""Session scoped dashboard access to local deterministic simulations."""

from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from fastapi import FastAPI

from notehub_client.runtimes.api import create_app


async def open_session(client: httpx.AsyncClient, app: FastAPI) -> None:
    response = await client.post(
        "/api/session/bootstrap", headers={"X-Launch-Secret": app.state.bootstrap_secret}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_simulation_session_and_normal_read_routes() -> None:
    app = create_app(dashboard=False)
    async with app.router.lifespan_context(app):
        async with (
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as first,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as second,
        ):
            await open_session(first, app)
            await open_session(second, app)
            catalog = await first.get("/api/simulations")
            assert "sensor" in {item["name"] for item in catalog.json()["scenarios"]}
            started = await first.post("/api/simulation/start", json={"name": "sensor", "seed": 31})
            assert started.status_code == 200, started.text
            body = started.json()
            project, device = body["projects"][0]["uid"], body["devices"][0]["uid"]
            generation = body["generation"]
            session = (await first.get("/api/session")).json()
            assert session["mode"] == "simulation"
            assert session["authenticated"] is False
            listed = await first.get("/api/projects/" + project + "/devices")
            assert listed.status_code == 200, listed.text
            assert listed.json()["devices"][0]["uid"] == device
            step = await first.post(
                "/api/simulation/control",
                json={
                    "action": "step",
                    "generation": generation,
                    "project_uid": project,
                },
            )
            assert step.status_code == 200, step.text
            assert {item["project_uid"] for item in step.json()["result"]} == {project}
            control = await first.post(
                "/api/simulation/control",
                json={
                    "action": "sync",
                    "generation": generation,
                    "project_uid": project,
                },
            )
            assert control.status_code == 200, control.text
            queued = await first.post(
                "/api/simulation/control",
                json={
                    "action": "command",
                    "generation": generation,
                    "project_uid": project,
                    "device_uid": device,
                    "note": {"file": "commands.qi", "body": {"set_temperature": 22}},
                },
            )
            assert queued.status_code == 200, queued.text
            queue_state = queued.json()["snapshot"]["devices"][project][device]
            assert len(queue_state["inbound"]) == 1
            assert len(queue_state["device_inbound"]) == 1
            events = await first.get("/api/projects/" + project + "/events")
            assert events.status_code == 200, events.text
            assert len(events.json()["events"]) == 1
            cycle = await first.post(
                "/api/simulation/control",
                json={
                    "action": "cycle",
                    "generation": generation,
                    "seconds": 60,
                    "project_uid": project,
                },
            )
            assert cycle.status_code == 200, cycle.text
            assert cycle.json()["snapshot"]["now"] != body["snapshot"]["now"]
            cycled_state = cycle.json()["snapshot"]["devices"][project][device]
            assert cycled_state["inbound"] == []
            assert cycle.json()["result"]["syncs"][0]["received"] == 1
            assert len(cycled_state["device_inbound"]) == 1
            # Distinct browser cookies own isolated runs.
            second_session = (await second.get("/api/session")).json()
            assert second_session["mode"] == "live"
            assert second_session["authenticated"] is False
            stale = await first.post(
                "/api/simulation/control", json={"action": "reset", "generation": generation}
            )
            assert stale.status_code == 200
            stale_control = await first.post(
                "/api/simulation/control",
                json={
                    "action": "step",
                    "generation": generation,
                },
            )
            assert stale_control.status_code == 400


@pytest.mark.asyncio
async def test_toml_upload_label_and_switch_back_to_live() -> None:
    app = create_app(dashboard=False)
    scenario = """scenario_version = 1
[[projects]]
uid = "app:custom"
[[projects]]
uid = "app:other"
[[devices]]
project_uid = "app:custom"
uid = "dev:one"
[[devices]]
project_uid = "app:other"
uid = "dev:one"
"""
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            await open_session(client, app)
            uploaded = await client.post(
                "/api/simulation/start",
                json={
                    "toml": scenario,
                    "filename": "custom.toml",
                    "seed": 9,
                },
            )
            assert uploaded.status_code == 200, uploaded.text
            state = (await client.get("/api/simulation")).json()
            assert state["label"] == "custom.toml"
            assert {item["uid"] for item in state["projects"]} == {"app:custom", "app:other"}
            assert {(item["project_uid"], item["uid"]) for item in state["devices"]} == {
                ("app:custom", "dev:one"),
                ("app:other", "dev:one"),
            }
            assert "dev:one" in state["snapshot"]["devices"]["app:custom"]
            assert "dev:one" in state["snapshot"]["devices"]["app:other"]
            # A page reload restores the declared IDs and still uses the normal client facade.
            project = await client.get("/api/projects/app:custom")
            devices = await client.get("/api/projects/app:custom/devices")
            other_devices = await client.get("/api/projects/app:other/devices")
            assert project.status_code == 200, project.text
            assert project.json()["uid"] == "app:custom"
            assert devices.status_code == 200, devices.text
            assert devices.json()["devices"][0]["uid"] == "dev:one"
            assert other_devices.status_code == 200, other_devices.text
            assert other_devices.json()["devices"][0]["uid"] == "dev:one"
            generation = state["generation"]
            cycle = await client.post(
                "/api/simulation/control",
                json={
                    "action": "cycle",
                    "generation": generation,
                    "project_uid": "app:other",
                    "seconds": 30,
                },
            )
            assert cycle.status_code == 200, cycle.text
            assert cycle.json()["snapshot"]["now"] != state["snapshot"]["now"]
            ended = await client.delete("/api/session")
            assert ended.status_code == 200
            assert (await client.get("/api/session")).json()["mode"] == "live"


@pytest.mark.asyncio
async def test_live_client_survives_simulation_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    class LiveClient:
        def __init__(self, token: str) -> None:
            self.token = token
            self.closed = False
            self.projects = SimpleNamespace(list=self.list_projects)

        async def list_projects(self, **_: object) -> dict[str, object]:
            return {"projects": [{"uid": "app:live", "label": "Live project"}]}

        async def aclose(self) -> None:
            self.closed = True

    monkeypatch.setenv("NOTEHUB_TOKEN", "local-test-token")
    app = create_app(client_factory=cast("type", LiveClient))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            await open_session(client, app)
            session_id = client.cookies["notehub_session"]
            live_client = app.state.notehub_sessions[session_id]["client"]
            started = await client.post("/api/simulation/start", json={"name": "sensor"})
            assert started.status_code == 200, started.text
            assert app.state.notehub_sessions[session_id]["client"] is live_client
            assert (await client.get("/api/session")).json() == {
                "initialized": True,
                "authenticated": False,
                "has_live_session": True,
                "mode": "simulation",
            }
            simulated = await client.post("/api/commands", json={"command": "projects.list"})
            assert simulated.status_code == 200, simulated.text
            assert simulated.json()["projects"][0]["uid"] == "app:demo"
            stopped = await client.post("/api/simulation/stop")
            assert stopped.status_code == 200, stopped.text
            assert stopped.json() == {"mode": "live", "authenticated": True}
            live = await client.post("/api/commands", json={"command": "projects.list"})
            assert live.status_code == 200, live.text
            assert live.json()["projects"][0]["uid"] == "app:live"
            assert live_client.closed is False


@pytest.mark.asyncio
async def test_session_token_and_logout_are_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    class SessionClient:
        def __init__(self, token: str) -> None:
            self.token = token

        async def aclose(self) -> None:
            pass

    monkeypatch.delenv("NOTEHUB_TOKEN", raising=False)
    app = create_app(client_factory=cast("type", SessionClient))
    async with app.router.lifespan_context(app):
        async with (
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as first,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as second,
        ):
            await open_session(first, app)
            await open_session(second, app)
            assert (await first.get("/api/session")).json()["authenticated"] is False
            assert (await second.get("/api/session")).json()["authenticated"] is False

            connected = await first.post("/api/session/token", json={"token": "first-only"})
            assert connected.status_code == 200
            assert (await first.get("/api/session")).json()["authenticated"] is True
            assert (await second.get("/api/session")).json()["authenticated"] is False

            ended = await first.delete("/api/session")
            assert ended.status_code == 200
            assert (await first.get("/api/session")).json()["authenticated"] is False
            assert (await second.get("/api/session")).json()["initialized"] is True


@pytest.mark.asyncio
async def test_empty_project_scenario_supports_clock_without_device_actions() -> None:
    app = create_app(dashboard=False)
    scenario = 'scenario_version = 1\n[[projects]]\nuid = "app:empty"\n'
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            await open_session(client, app)
            started = await client.post(
                "/api/simulation/start",
                json={
                    "toml": scenario,
                    "filename": "empty-project.toml",
                },
            )
            assert started.status_code == 200, started.text
            body = started.json()
            assert body["projects"] == [{"uid": "app:empty", "label": ""}]
            assert body["devices"] == []

            advanced = await client.post(
                "/api/simulation/control",
                json={
                    "action": "advance",
                    "generation": body["generation"],
                    "seconds": 60,
                },
            )
            assert advanced.status_code == 200, advanced.text
            stepped = await client.post(
                "/api/simulation/control",
                json={
                    "action": "step",
                    "generation": advanced.json()["generation"],
                    "project_uid": "app:empty",
                },
            )
            assert stepped.status_code == 200, stepped.text
            assert stepped.json()["result"] == []
