"""Request pacing shared by independent Notehub clients."""

from __future__ import annotations

from time import perf_counter

import httpx
import pytest

from notehub_client import NotehubClient
from notehub_client.helpers import RequestPacer


@pytest.mark.asyncio
async def test_clients_share_an_opt_in_request_budget() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        pacer = RequestPacer(limit=1, period=0.04)
        async with NotehubClient("test", http_client=http_client, pacer=pacer) as first:
            async with NotehubClient("test", http_client=http_client, pacer=pacer) as second:
                started = perf_counter()
                await first.request("GET", "projects")
                await second.request("GET", "projects")
                elapsed = perf_counter() - started

    assert len(requests) == 2
    assert elapsed >= 0.035
