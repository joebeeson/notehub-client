"""FastAPI dependencies for the local HTTP runtime."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ...client import NotehubClient


def get_session_client(request: Request) -> NotehubClient:
    """Resolve the client owned by the request's authenticated session."""
    session_id = request.cookies.get("notehub_session", "")
    session = request.app.state.notehub_sessions.get(session_id)
    if session is None:
        raise PermissionError("session required")
    client = session["simulation_client"] if session["mode"] == "simulation" else session["client"]
    if client is None:
        raise PermissionError("session required")
    return client


NotehubClientDep = Annotated[NotehubClient, Depends(get_session_client)]


__all__ = ["NotehubClientDep", "get_session_client"]
