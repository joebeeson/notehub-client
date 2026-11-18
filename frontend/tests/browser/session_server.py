"""Loopback-only browser fixture: real session routes and a synthetic upstream."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from typing import cast

import uvicorn

from notehub_client.client import NotehubClient
from notehub_client.runtimes.api import create_app


class SyntheticClient:
    """Serve synthetic reads and count active upstream requests."""

    calls = 0
    active = 0
    created = 0

    def __init__(self, token: str) -> None:
        type(self).created += 1
        self.projects = SimpleNamespace(list=self.projects_list, get=self.project_get)
        self.devices = SimpleNamespace(list=self.devices_list)
        self.events = SimpleNamespace(list=self.events_list)
        self.fleets = self.routes = self.monitors = self.jobs = SimpleNamespace(list=self.empty)

    async def projects_list(self, **kwargs: object) -> dict[str, object]:
        """Expose one synthetic project."""
        return {"projects": [{"uid": "app:browser", "label": "Synthetic live project"}]}

    async def project_get(self, uid: str) -> dict[str, object]:
        """Supply the overview's project record."""
        return {"uid": uid, "label": "Synthetic live project"}

    async def devices_list(self, *args: object, **kwargs: object) -> dict[str, object]:
        """Expose one synthetic device."""
        return {"devices": [{"uid": "dev:browser"}], "has_more": False}

    async def empty(self, *args: object, **kwargs: object) -> dict[str, object]:
        """Return no records for unrelated overview reads."""
        return {}

    async def events_list(self, *args: object, **kwargs: object) -> dict[str, object]:
        """Keep cursor catch-up active until the stream cancels its read."""
        type(self).calls += 1
        type(self).active += 1
        cursor = str(type(self).calls)
        try:
            # Keep a catch-up read in flight so mode changes exercise cancellation.
            await asyncio.sleep(0.1)
            return {"events": [], "has_more": True, "next_cursor": cursor}
        finally:
            type(self).active -= 1

    async def aclose(self) -> None:
        """Match the client lifecycle without external resources."""
        pass


# Never inherit a real launch credential in this test process.
os.environ["NOTEHUB_TOKEN"] = "synthetic-browser-token"  # noqa: S105 -- test-only credential
app = create_app(client_factory=cast("type[NotehubClient]", SyntheticClient), dashboard=True)


@app.get("/smoke/state")
async def smoke_state() -> dict[str, object]:
    """Expose test-only counters and bootstrap material, never real credentials."""
    return {
        "secret": app.state.bootstrap_secret,
        "calls": SyntheticClient.calls,
        "active": SyntheticClient.active,
        "created": SyntheticClient.created,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=4174, log_level="warning")
