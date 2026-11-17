"""Local-only HTTPX adapter for ordinary NotehubClient resource facades."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote

import httpx

from ..compose import resolve_environment, resolve_note_body
from .models import QueuedNote
from .queries import device_rows, event_page, page
from .simulation import Simulation

__all__ = ["SimulationTransport"]


class SimulationTransport(httpx.AsyncBaseTransport):
    """Translate the supported Notehub HTTP subset into one simulation's state.

    Every request is resolved locally. Closing a transport does not close its run.
    Unsupported endpoints/query capabilities return HTTP 501.
    """

    def __init__(self, simulation: Simulation) -> None:
        self.simulation = simulation
        self._closed = False

    async def aclose(self) -> None:
        """Close only this transport; other clients retain shared run access."""
        self._closed = True

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Execute a request locally and return an ordinary HTTPX response."""
        run = self.simulation
        if self._closed or run.closed:
            raise httpx.ConnectError("simulation or transport closed", request=request)
        # Split encoded path before decoding so identifiers containing / round-trip.
        raw_path = request.url.raw_path.split(b"?")[0].decode("ascii")
        if not raw_path.startswith("/v1/"):
            return httpx.Response(501, json={"err": "unsupported simulation path"})
        path = raw_path.removeprefix("/v1/")
        for fault in tuple(run._faults):
            if fault.method == request.method and fault.path == path:
                run._faults.remove(fault)
                if fault.status_code is None:
                    raise httpx.ConnectError("simulated connection failure", request=request)
                headers = (
                    {"Retry-After": fault.retry_after} if fault.retry_after is not None else {}
                )
                return httpx.Response(
                    fault.status_code, headers=headers, json={"err": "simulated failure"}
                )
        try:
            result = self._dispatch(request, path)
            return httpx.Response(200, json=result)
        except NotImplementedError as error:
            return httpx.Response(501, json={"err": str(error)})
        except KeyError:
            return httpx.Response(404, json={"err": "unknown simulation resource"})
        except (ValueError, TypeError) as error:
            return httpx.Response(400, json={"err": str(error)})

    def _dispatch(self, request: httpx.Request, path: str) -> Any:
        run = self.simulation
        parts = [unquote(p) for p in path.split("/")]
        method = request.method
        query = request.url.params
        if parts == ["projects"] and method == "GET":
            return page(
                [{"uid": p.uid, "label": p.label} for p in run._projects.values()],
                query,
                "projects",
            )
        if len(parts) < 2 or parts[0] != "projects":
            raise NotImplementedError("unsupported simulation route")
        project = parts[1]
        description = run._projects[project]
        if len(parts) == 2 and method == "GET":
            if query:
                raise NotImplementedError("project query options unsupported")
            return {"uid": project, "label": description.label}
        tail = parts[2:]
        if tail and tail[0] == "environment_variables":
            return self._environment(request, tail[1:], run._project_env[project])
        if tail == ["fleets"] and method == "GET":
            if query:
                raise NotImplementedError("fleet query options unsupported")
            return {
                "fleets": [
                    {"uid": f.uid, "label": f.label}
                    for (pid, _), f in run._fleets.items()
                    if pid == project
                ]
            }
        fleet = None
        if tail and tail[0] == "fleets" and len(tail) >= 2:
            fleet = tail[1]
            run._fleets[(project, fleet)]
            tail = tail[2:]
            if tail and tail[0] == "environment_variables":
                return self._environment(request, tail[1:], run._fleet_env[(project, fleet)])
        if tail == ["events"] and method == "GET":
            return event_page(run, path, project, query, fleet)
        if tail == ["devices"] and method == "GET":
            return device_rows(run, project, query, fleet)
        if fleet is not None or len(tail) < 2 or tail[0] != "devices":
            raise NotImplementedError("unsupported simulation route")
        uid = tail[1]
        state = run._state(project, uid)
        rest = tail[2:]
        if not rest and method == "GET":
            if query:
                raise NotImplementedError("device detail query options unsupported")
            return next(
                d
                for d in device_rows(run, project, httpx.QueryParams({"deviceUID": uid}))["devices"]
            )
        if rest == ["sessions"] and method == "GET":
            return page(state.sessions, query, "sessions")
        if rest == ["latest"] and method == "GET":
            if query:
                raise NotImplementedError("latest query options unsupported")
            latest = {}
            for event in run._events:
                if event["app"] == project and event["device"] == uid:
                    latest[event["file"]] = event
            return {"latest_events": list(latest.values())}
        if rest and rest[0] == "environment_variables":
            result = self._environment(request, rest[1:], state.environment)
            if method == "GET":
                result.update(
                    environment_variables_effective=run._effective_environment(project, uid),
                    environment_variables_env_default=dict(state.definition.defaults),
                )
            return result
        if len(rest) == 2 and rest[0] == "notes" and method == "POST":
            if query:
                raise NotImplementedError("Note query options unsupported")
            if not rest[1].endswith(".qi"):
                raise NotImplementedError("simulation only supports inbound .qi Note writes")
            data = resolve_note_body(json.loads(request.content))
            note = QueuedNote(project, uid, rest[1], resolve_note_body(data.get("body")))
            state.inbound.append(run._note(note))
            return {}
        raise NotImplementedError("unsupported simulation route")

    @staticmethod
    def _environment(
        request: httpx.Request, rest: list[str], values: dict[str, str]
    ) -> dict[str, Any]:
        if request.url.params:
            raise NotImplementedError("environment query options unsupported")
        if not rest and request.method == "GET":
            return {"environment_variables": dict(values)}
        if not rest and request.method == "PUT":
            data = resolve_note_body(json.loads(request.content))
            values.update(resolve_environment(data.get("environment_variables")))
            return {}
        if len(rest) == 1 and request.method == "DELETE":
            values.pop(rest[0], None)
            return {}
        raise NotImplementedError("unsupported environment operation")
