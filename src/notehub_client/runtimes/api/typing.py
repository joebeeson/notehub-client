"""Typed application state for the local HTTP runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from asyncio import Event

    from ...client import NotehubClient
    from ...simulate.simulation import Simulation

__all__ = ["APIContext"]


class APIContext(TypedDict):
    """State shared by API handlers for launch credentials and sessions."""

    bootstrap_secret: str
    launch_token: str
    sessions: dict[str, "RuntimeSession"]
    simulation_catalog: dict[str, Any]


class RuntimeSession(TypedDict):
    """One browser session with separately owned live and simulation clients."""

    mode: str
    client: NotehubClient | None
    simulation_client: NotehubClient | None
    simulation: Simulation | None
    simulation_http: Any
    scenario_name: str | None
    scenario_label: str | None
    seed: int
    generation: int
    workspace_changed: Event
    lock: Any
