"""Shared local HTTP application for the API and browser dashboard."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from ...client import NotehubClient
from ...errors import NotehubAPIError, NotehubError, NotehubRateLimitError
from ...filters import CursorPagination
from ...helpers import RequestPacer
from ...simulate import Scenario
from ...simulate import available as available_scenarios
from ...simulate import named as named_scenario
from ..helpers import create_client, runtime_imports
from .commands import execute_read
from .depends import NotehubClientDep
from .typing import RuntimeSession

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ..typing import ClientFactory
    from .typing import APIContext

with runtime_imports("api", "fastapi"):
    from fastapi import FastAPI, Request
    from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field, SecretStr


class CommandRequest(BaseModel):
    """A named, allowlisted read with JSON arguments."""

    command: str
    args: dict[str, Any] = Field(default_factory=dict)


class TokenRequest(BaseModel):
    """A Personal Access Token entered through the local dashboard."""

    token: SecretStr


def _json_value(value: Any) -> Any:
    """Project immutable simulation values into ordinary JSON containers."""
    if isinstance(value, Mapping):
        return {
            "/".join(map(str, key)) if isinstance(key, tuple) else str(key): _json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    return value


def _simulation_snapshot(run: Any) -> dict[str, Any]:
    """Serialize device state with project and device IDs as separate JSON keys."""
    snapshot = run.snapshot()
    result = {key: _json_value(value) for key, value in snapshot.items() if key != "devices"}
    devices: dict[str, dict[str, Any]] = {}
    for (project_uid, device_uid), value in snapshot["devices"].items():
        devices.setdefault(project_uid, {})[device_uid] = _json_value(value)
    result["devices"] = devices
    return result


def create_app(
    *,
    client_factory: ClientFactory = NotehubClient,
    dashboard: bool = False,
    token_file: str | None = None,
    simulation_catalog: dict[str, Scenario] | None = None,
) -> FastAPI:
    """Create one local app with session-scoped credentials and read operations."""
    context: APIContext = {
        "bootstrap_secret": secrets.token_urlsafe(32),
        "sessions": {},
        "simulation_catalog": {
            name: Scenario.from_value(value) for name, value in (simulation_catalog or {}).items()
        },
        "launch_token": (
            Path(token_file).read_text(encoding="utf-8").strip()
            if token_file
            else (os.getenv("NOTEHUB_TOKEN") or "").strip()
        ),
    }
    request_pacer = RequestPacer() if dashboard else None

    def make_client(token: str) -> NotehubClient:
        return create_client(token, client_factory=client_factory, pacer=request_pacer)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.notehub_client = None  # Retain the existing health contract.
        if context["launch_token"]:
            try:
                app.state.notehub_client = make_client(context["launch_token"])
            except ValueError:
                pass
        try:
            yield
        finally:
            for session in context["sessions"].values():
                if session["simulation"] is not None:
                    session["simulation"].close()
                if session["simulation_client"] is not None:
                    await session["simulation_client"].aclose()
                if session["simulation_http"] is not None:
                    await session["simulation_http"].aclose()
                if session["client"] is not None:
                    await session["client"].aclose()
            if app.state.notehub_client is not None:
                await app.state.notehub_client.aclose()

    app = FastAPI(title="Notehub Client API", lifespan=lifespan)
    app.state.bootstrap_secret = context["bootstrap_secret"]
    app.state.notehub_sessions = context["sessions"]

    async def paced_read(operation: Any) -> Any:
        try:
            return await operation()
        except NotehubRateLimitError:
            if request_pacer is None:
                raise
            return await operation()

    @app.middleware("http")
    async def local_boundary(request: Request, call_next: Any) -> Any:
        allowed_hosts = {"127.0.0.1", "localhost"}
        if not dashboard:
            allowed_hosts.add("testserver")  # ASGI test clients use this default host.
        if request.url.hostname not in allowed_hosts:
            return JSONResponse(
                {"error": {"code": "invalid_host", "message": "Local host required"}},
                status_code=400,
            )
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
            return JSONResponse(
                {"error": {"code": "invalid_origin", "message": "Same origin required"}},
                status_code=403,
            )
        response = await call_next(request)
        if request.url.path.startswith("/dashboard"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'"
            )
        return response

    @app.exception_handler(NotehubError)
    async def notehub_error(_request: Request, error: NotehubError) -> JSONResponse:
        status = error.status_code if isinstance(error, NotehubAPIError) else 502
        return JSONResponse(
            {"error": {"code": type(error).__name__, "message": str(error)}}, status_code=status
        )

    @app.exception_handler(ValueError)
    async def input_error(_request: Request, error: ValueError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "invalid_input", "message": str(error)}}, status_code=400
        )

    @app.exception_handler(PermissionError)
    async def session_error(_request: Request, _error: PermissionError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "session_required", "message": "Open a dashboard session"}},
            status_code=401,
        )

    @app.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]:
        """Report process liveness."""
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def ready() -> Any:
        """Report whether launch credentials were locally valid."""
        if app.state.notehub_client is None:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "reason": "notehub_token_missing_or_invalid"},
            )
        return {"status": "ready"}

    @app.post("/api/session/bootstrap")
    async def bootstrap(request: Request) -> JSONResponse:
        if not secrets.compare_digest(
            request.headers.get("x-launch-secret", ""), context["bootstrap_secret"]
        ):
            raise PermissionError("invalid bootstrap")
        previous = context["sessions"].pop(request.cookies.get("notehub_session", ""), None)
        if previous is not None:
            if previous["simulation"] is not None:
                previous["simulation"].close()
            if previous["simulation_client"] is not None:
                await previous["simulation_client"].aclose()
            if previous["simulation_http"] is not None:
                await previous["simulation_http"].aclose()
            if previous["client"] is not None:
                await previous["client"].aclose()
        session_id = secrets.token_urlsafe(32)
        client = make_client(context["launch_token"]) if app.state.notehub_client else None
        context["sessions"][session_id] = RuntimeSession(
            mode="live", client=client, simulation_client=None, simulation=None,
            simulation_http=None, scenario_name=None, scenario_label=None, seed=0, generation=0,
            lock=asyncio.Lock(),
        )
        response = JSONResponse({"authenticated": context["sessions"][session_id]["client"] is not None})
        response.set_cookie(
            "notehub_session", session_id, httponly=True, samesite="strict", path="/api"
        )
        return response

    @app.get("/api/session")
    async def session(request: Request) -> dict[str, Any]:
        """Return credential state without revealing the token."""
        session_id = request.cookies.get("notehub_session", "")
        value = context["sessions"].get(session_id)
        return {"initialized": value is not None,
                "authenticated": bool(value and value["client"] and value["mode"] == "live"),
                "has_live_session": bool(value and value["client"]),
                "mode": value["mode"] if value else None}

    @app.post("/api/session/token")
    async def set_token(request: Request, body: TokenRequest) -> dict[str, bool]:
        session_id = request.cookies.get("notehub_session", "")
        if session_id not in context["sessions"]:
            raise PermissionError("session required")
        replacement = make_client(body.token.get_secret_value())
        session = context["sessions"][session_id]
        old = session["client"]
        session["client"] = replacement
        session["mode"] = "live"
        if session["simulation"] is not None:
            session["simulation"].close()
        if session["simulation_http"] is not None:
            await session["simulation_http"].aclose()
        if session["simulation_client"] is not None:
            await session["simulation_client"].aclose()
        session["simulation_http"] = None
        session["simulation_client"] = None
        session["simulation"] = None
        session["scenario_name"] = None
        session["scenario_label"] = None
        session["generation"] += 1
        if old is not None:
            await old.aclose()
        return {"authenticated": True}

    @app.delete("/api/session")
    async def logout(request: Request) -> JSONResponse:
        session_id = request.cookies.get("notehub_session", "")
        session = context["sessions"].get(session_id)
        if session is not None:
            old = session["client"]
            session["client"] = None
            if session["simulation"] is not None:
                session["simulation"].close()
            if session["simulation_http"] is not None:
                await session["simulation_http"].aclose()
            if session["simulation_client"] is not None:
                await session["simulation_client"].aclose()
            session["simulation_http"] = None
            session["simulation_client"] = None
            session["simulation"] = None
            session["mode"] = "live"
            session["scenario_name"] = None
            session["scenario_label"] = None
            session["generation"] += 1
            if old is not None:
                await old.aclose()
        return JSONResponse({"authenticated": False})

    @app.get("/api/simulations")
    async def simulations(request: Request) -> dict[str, Any]:
        session_id = request.cookies.get("notehub_session", "")
        if session_id not in context["sessions"]:
            raise PermissionError("session required")
        catalog = {name: named_scenario(name) for name in available_scenarios()}
        catalog.update(context["simulation_catalog"])
        return {"scenarios": [{"name": name, "devices": len(value.devices),
                               "projects": len(value.projects)} for name, value in catalog.items()]}

    @app.post("/api/simulation/start")
    async def simulation_start(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        session_id = request.cookies.get("notehub_session", "")
        session = context["sessions"].get(session_id)
        if session is None:
            raise PermissionError("session required")
        if len(json.dumps(body)) > 1_048_576:
            raise ValueError("scenario input is too large")
        if "toml" in body:
            import tomllib
            source = body["toml"]
            filename = body.get("filename")
            if not isinstance(source, str):
                raise ValueError("toml must be a string")
            if filename is not None and not isinstance(filename, str):
                raise ValueError("filename must be a string")
            scenario = Scenario.from_mapping(tomllib.loads(source))
            name = None
            label = filename or "Uploaded scenario"
        else:
            name = body.get("name")
            if not isinstance(name, str):
                raise ValueError("name must be a string")
            catalog = {item: named_scenario(item) for item in available_scenarios()}
            catalog.update(context["simulation_catalog"])
            if name not in catalog:
                raise ValueError("unknown simulation scenario")
            scenario = catalog[name]
            label = name
        seed = body.get("seed", 0)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer")
        replacement = scenario.start(seed=seed)
        replacement_http = httpx.AsyncClient(transport=replacement.transport())
        replacement_client = NotehubClient(
            "simulation-token", base_url="https://simulation.invalid", http_client=replacement_http
        )
        async with session["lock"]:
            previous = session["simulation"]
            previous_http = session["simulation_http"]
            previous_client = session["simulation_client"]
            session["simulation"] = replacement
            session["simulation_http"] = replacement_http
            session["simulation_client"] = replacement_client
            session["scenario_name"] = name
            session["scenario_label"] = label
            session["seed"] = seed
            session["mode"] = "simulation"
            session["generation"] += 1
            if previous is not None:
                previous.close()
            if previous_client is not None:
                await previous_client.aclose()
            if previous_http is not None:
                await previous_http.aclose()
        return {"mode": "simulation", "scenario": name, "label": label, "seed": seed,
                "projects": [{"uid": value.uid, "label": value.label} for value in scenario.projects],
                "devices": [{"project_uid": value.project_uid, "uid": value.uid,
                             "label": value.serial_number or value.uid} for value in scenario.devices],
                "generation": session["generation"], "snapshot": _simulation_snapshot(replacement)}

    async def simulation_session(request: Request) -> RuntimeSession:
        session_id = request.cookies.get("notehub_session", "")
        session = context["sessions"].get(session_id)
        if session is None:
            raise PermissionError("session required")
        if session["mode"] != "simulation" or session["simulation"] is None:
            raise ValueError("session is not in simulation mode")
        return session

    @app.get("/api/simulation")
    async def simulation_state(request: Request) -> dict[str, Any]:
        session = await simulation_session(request)
        run = session["simulation"]
        if run is None:
            raise RuntimeError("simulation session lost its run")
        return {"scenario": session["scenario_name"], "label": session["scenario_label"],
                "projects": [{"uid": value.uid, "label": value.label}
                             for value in run.scenario.projects],
                "devices": [{"project_uid": value.project_uid, "uid": value.uid,
                             "label": value.serial_number or value.uid}
                            for value in run.scenario.devices], "seed": session["seed"],
                "generation": session["generation"], "live_session": session["client"] is not None,
                "snapshot": _simulation_snapshot(run)}

    @app.post("/api/simulation/stop")
    async def simulation_stop(request: Request) -> dict[str, Any]:
        """Return this browser session to its preserved live client, if any."""
        session = await simulation_session(request)
        async with session["lock"]:
            if session["simulation"] is not None:
                session["simulation"].close()
            if session["simulation_client"] is not None:
                await session["simulation_client"].aclose()
            if session["simulation_http"] is not None:
                await session["simulation_http"].aclose()
            session["simulation"] = None
            session["simulation_client"] = None
            session["simulation_http"] = None
            session["mode"] = "live"
            session["scenario_name"] = None
            session["scenario_label"] = None
            session["generation"] += 1
        return {"mode": "live", "authenticated": session["client"] is not None}

    @app.get("/api/simulation/events")
    async def simulation_events(request: Request) -> dict[str, Any]:
        session = await simulation_session(request)
        run = session["simulation"]
        if run is None:
            raise RuntimeError("simulation session lost its run")
        return {"events": _json_value(run.snapshot()["events"]), "generation": session["generation"]}

    @app.post("/api/simulation/control")
    async def simulation_control(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        session = await simulation_session(request)
        run = session["simulation"]
        if run is None:
            raise RuntimeError("simulation session lost its run")
        generation = body.get("generation")
        if generation != session["generation"]:
            raise ValueError("simulation session changed; refresh before controlling it")
        action = body.get("action")
        async with session["lock"]:
            if action == "advance":
                seconds = body.get("seconds", 60)
                if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 0:
                    raise ValueError("seconds must be a nonnegative number")
                from datetime import timedelta
                run.advance(timedelta(seconds=seconds))
                result: Any = {"now": run.now.isoformat()}
            elif action == "cycle":
                seconds = body.get("seconds", 60)
                project = body.get("project_uid")
                if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 0:
                    raise ValueError("seconds must be a nonnegative number")
                if not isinstance(project, str):
                    raise ValueError("project_uid is required")
                from datetime import timedelta
                run.advance(timedelta(seconds=seconds))
                stepped = {
                    (binding.project_uid, binding.device_uid): run.device(
                        binding.project_uid, binding.device_uid
                    ).step()
                    for binding in run.scenario.behaviors
                    if binding.project_uid == project
                }
                synced = [
                    run.device(project, definition.uid).sync()
                    for definition in run.scenario.devices
                    if definition.project_uid == project
                ]
                result = {"steps": [{"project_uid": p, "device_uid": d, "result": value}
                                    for (p, d), value in stepped.items()], "syncs": synced}
            elif action == "step":
                project, device = body.get("project_uid"), body.get("device_uid")
                if project is not None and not isinstance(project, str):
                    raise ValueError("project_uid must be a string")
                if device is not None and not isinstance(device, str):
                    raise ValueError("device_uid must be a string")
                result = [
                    {"project_uid": binding.project_uid, "device_uid": binding.device_uid,
                     "result": run.device(binding.project_uid, binding.device_uid).step()}
                    for binding in run.scenario.behaviors
                    if (project is None or binding.project_uid == project)
                    and (device is None or binding.device_uid == device)
                ]
            elif action == "sync":
                project, device = body.get("project_uid"), body.get("device_uid")
                if not isinstance(project, str):
                    raise ValueError("project_uid is required")
                if device is not None and not isinstance(device, str):
                    raise ValueError("device_uid must be a string")
                devices = [run.device(project, device)] if device else [
                    run.device(project, definition.uid) for definition in run.scenario.devices
                    if definition.project_uid == project
                ]
                result = tuple(item.sync() for item in devices)
            elif action == "command":
                project, device = body.get("project_uid"), body.get("device_uid")
                if not isinstance(project, str) or not isinstance(device, str):
                    raise ValueError("project_uid and device_uid are required")
                note = body.get("note")
                if not isinstance(note, dict):
                    raise ValueError("note must be an object")
                target = run.device(project, device)
                client = session["simulation_client"]
                if client is None:
                    raise RuntimeError("simulation client is unavailable")
                await client.notes.add_qi(
                    target.note(note.get("file", "commands.qi")), note.get("body", {})
                )
                result = {"queued": True}
            elif action == "fault":
                run.fail_next(body["method"], body["path"], status_code=body.get("status_code", 500),
                              retry_after=body.get("retry_after"))
                result = {"queued": True}
            elif action == "reset":
                replacement = run.scenario.start(registry=None, seed=session["seed"])
                replacement_http = httpx.AsyncClient(transport=replacement.transport())
                replacement_client = NotehubClient(
                    "simulation-token", base_url="https://simulation.invalid",
                    http_client=replacement_http,
                )
                previous_client = session["simulation_client"]
                run.close()
                if previous_client is not None:
                    await previous_client.aclose()
                if session["simulation_http"] is not None:
                    await session["simulation_http"].aclose()
                session["simulation"] = replacement
                session["simulation_http"] = replacement_http
                session["simulation_client"] = replacement_client
                session["generation"] += 1
                result = {"reset": True}
            else:
                raise ValueError("unknown simulation action")
        current = session["simulation"]
        if current is None:
            raise RuntimeError("simulation session lost its run")
        return {"generation": session["generation"], "result": _json_value(result),
                "snapshot": _simulation_snapshot(current)}

    @app.post("/api/commands")
    async def command(body: CommandRequest, client: NotehubClientDep) -> Any:
        """Execute one explicit read command; mutations have no registration."""
        if len(json.dumps(body.args)) > 8192:
            raise ValueError("command arguments are too large")
        return await paced_read(lambda: execute_read(client, body.command, body.args))

    paths = {
        "/api/projects": "projects.list",
        "/api/projects/{project_uid}": "projects.get",
        "/api/projects/{project_uid}/fleets": "fleets.list",
        "/api/projects/{project_uid}/devices": "devices.list",
        "/api/projects/{project_uid}/devices/{device_uid}": "devices.get",
        "/api/projects/{project_uid}/devices/{device_uid}/sessions": "devices.sessions",
        "/api/projects/{project_uid}/devices/{device_uid}/latest": "devices.latest",
        "/api/projects/{project_uid}/devices/{device_uid}/environment": "devices.environment",
        "/api/projects/{project_uid}/fleets/{fleet_uid}/devices": "devices.for_fleet",
        "/api/projects/{project_uid}/events": "events.list",
        "/api/projects/{project_uid}/fleets/{fleet_uid}/events": "events.for_fleet",
        "/api/projects/{project_uid}/routes": "routes.list",
        "/api/projects/{project_uid}/jobs": "jobs.list",
        "/api/projects/{project_uid}/monitors": "monitors.list",
        "/api/projects/{project_uid}/usage": "usage.get",
        "/api/organizations": "organizations.list",
        "/api/organizations/{organization_uid}": "organizations.get",
        "/api/organizations/{organization_uid}/balance-history": "organizations.balance_history",
        "/api/billing-accounts": "billing_accounts.list",
        "/api/billing-accounts/{billing_account_uid}": "billing_accounts.get",
        "/api/billing-accounts/{billing_account_uid}/balance-history": "billing_accounts.balance_history",
    }

    def read_endpoint(command_name: str) -> Any:
        async def read(request: Request, client: NotehubClientDep) -> Any:
            args: dict[str, Any] = dict(request.query_params)
            args.update(request.path_params)
            if command_name in {"events.list", "events.for_fleet"}:
                filter_keys = {
                    "files",
                    "deviceUID",
                    "sensorUID",
                    "fleetUID",
                    "serialNumber",
                    "sessionUID",
                    "eventUID",
                    "startDate",
                    "endDate",
                    "dateType",
                    "sortBy",
                    "sortOrder",
                    "systemFilesOnly",
                    "selectFields",
                    "since",
                }
                args["filters"] = {key: args.pop(key) for key in filter_keys if key in args}
            for key in ("page_size", "page_num"):
                if key in args:
                    args[key] = int(args[key])
            return await paced_read(lambda: execute_read(client, command_name, args))

        return read

    for path, command_name in paths.items():
        app.add_api_route(path, read_endpoint(command_name), methods=["GET"], name=command_name)

    @app.get("/api/projects/{project_uid}/stream/events")
    async def stream_events(
        request: Request, project_uid: str, client: NotehubClientDep
    ) -> StreamingResponse:
        """Poll Notehub cursors and relay whole pages over SSE."""
        cursor = request.headers.get("last-event-id") or str((time.time_ns() // 1000) - 60_000_000)

        async def generate() -> AsyncIterator[str]:
            nonlocal cursor
            while not await request.is_disconnected():
                try:
                    page = await paced_read(
                        lambda: client.events.list(
                            project_uid, pagination=CursorPagination(cursor=cursor, page_size=100)
                        )
                    )
                    next_cursor = page.get("next_cursor")
                    if not next_cursor:
                        yield 'event: error\ndata: {"code":"cursor_missing"}\n\n'
                    else:
                        cursor = next_cursor
                        if page["events"]:
                            payload = json.dumps(
                                {"events": page["events"], "checked_at": time.time()}
                            )
                            yield f"id: {cursor}\nevent: batch\ndata: {payload}\n\n"
                        else:
                            yield f'event: heartbeat\ndata: {{"checked_at":{time.time()}}}\n\n'
                        if page["has_more"]:
                            continue
                except NotehubError as error:
                    yield f'event: error\ndata: {{"code":"{type(error).__name__}"}}\n\n'
                except RuntimeError as error:
                    if "client has been closed" in str(error).casefold():
                        return
                    raise
                await asyncio.sleep(60)

        return StreamingResponse(
            generate(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
        )

    if dashboard:
        static = Path(__file__).resolve().parent.parent / "web" / "static"
        if not (static / "index.html").is_file():
            raise RuntimeError("Web assets missing; rebuild the package with Node available")
        app.mount(
            "/dashboard/assets", StaticFiles(directory=static / "assets"), name="dashboard-assets"
        )

        @app.get("/")
        async def root() -> RedirectResponse:
            """Open the local dashboard."""
            return RedirectResponse("/dashboard")

        @app.get("/dashboard/favicon.svg")
        async def dashboard_icon() -> FileResponse:
            """Serve the dashboard's browser icon."""
            return FileResponse(static / "favicon.svg", media_type="image/svg+xml")

        @app.get("/dashboard/{path:path}")
        async def dashboard_page(path: str) -> FileResponse:
            """Serve the SPA shell for client-side navigation."""
            return FileResponse(static / "index.html")

        @app.get("/dashboard")
        async def dashboard_root() -> FileResponse:
            """Serve the SPA shell."""
            return FileResponse(static / "index.html")

    return app


__all__ = ["create_app"]
