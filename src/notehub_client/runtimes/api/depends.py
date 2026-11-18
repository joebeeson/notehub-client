"""FastAPI dependencies for the local HTTP runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, cast

from fastapi import Depends, Request

from ...client import NotehubClient

if TYPE_CHECKING:
    from .typing import RuntimeSession


def get_runtime_session(request: Request) -> RuntimeSession:
    """Resolve the browser session that owns the request."""
    session_id = request.cookies.get("notehub_session", "")
    session = request.app.state.notehub_sessions.get(session_id)
    if session is None:
        raise PermissionError("session required")
    return cast("RuntimeSession", session)


def active_session_client(session: RuntimeSession) -> NotehubClient:
    """Resolve the selected client in the browser session."""
    client = session["simulation_client"] if session["mode"] == "simulation" else session["client"]
    if client is None:
        raise PermissionError("session required")
    return client


def get_session_client(request: Request) -> NotehubClient:
    """Resolve the client owned by the request's authenticated session."""
    return active_session_client(get_runtime_session(request))


NotehubClientDep = Annotated[NotehubClient, Depends(get_session_client)]


__all__ = ["NotehubClientDep", "get_session_client"]
