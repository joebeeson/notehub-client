"""Request pacing shared by independent Notehub clients."""

from __future__ import annotations

from time import perf_counter

import httpx
import pytest

from notehub_client import NotehubClient
from notehub_client.errors import NotehubRateLimitError
from notehub_client.helpers import RequestPacer, pacing
from notehub_client.observe import ClientEvent, RequestFailed, RequestFinished, RequestStarted


@pytest.mark.asyncio
async def test_token_resolution_follows_pacing_and_failed_exchange_consumes_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1000.0
    resolved_at: list[float] = []
    sent_at: list[float] = []
    exchange_error = httpx.ConnectError("provider unavailable")
    events: list[ClientEvent] = []

    class Observer:
        def on_event(self, event: ClientEvent) -> None:
            events.append(event)

    async def sleep(delay: float) -> None:
        nonlocal now
        now += delay

    async def token() -> str:
        resolved_at.append(now)
        if len(resolved_at) == 1:
            raise exchange_error
        return "synthetic-pat"

    def respond(request: httpx.Request) -> httpx.Response:
        sent_at.append(now)
        assert request.headers["Authorization"] == "Bearer synthetic-pat"
        return httpx.Response(200, json={})

    monkeypatch.setattr(pacing.time, "monotonic", lambda: now)
    monkeypatch.setattr(pacing.asyncio, "sleep", sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
        async with NotehubClient(
            token_provider=token,
            http_client=transport,
            pacer=RequestPacer(limit=1, period=60),
            observer=Observer(),
        ) as client:
            with pytest.raises(httpx.ConnectError) as failure:
                await client.request("GET", "projects")
            assert failure.value is exchange_error
            assert not sent_at
            await client.request("GET", "projects")

    assert resolved_at == [1000.0, 1060.0]
    assert sent_at == [1060.0]
    assert [type(event) for event in events] == [
        RequestStarted,
        RequestFailed,
        RequestStarted,
        RequestFinished,
    ]


@pytest.mark.parametrize(
    ("header", "expected_delay"),
    [
        pytest.param("120", 120.0, id="seconds"),
        pytest.param("2.5", 2.5, id="fractional-seconds"),
        pytest.param("Thu, 01 Jan 1970 00:02:00 GMT", 120.0, id="http-date"),
        pytest.param("Thursday, 01-Jan-70 00:02:00 GMT", 120.0, id="obsolete-rfc850"),
        pytest.param("Thu Jan  1 00:02:00 1970", 120.0, id="obsolete-asctime"),
        pytest.param("Wed, 31 Dec 1969 23:59:00 GMT", 1.0, id="past-date"),
        pytest.param("0", 1.0, id="zero"),
        pytest.param("-5", 1.0, id="negative"),
        pytest.param(None, 60.0, id="missing"),
        pytest.param("", 60.0, id="empty"),
        pytest.param("invalid", 60.0, id="malformed"),
        pytest.param("Thu, 99 Jan 1970 00:02:00 GMT", 60.0, id="invalid-date"),
        pytest.param("nan", 60.0, id="nan"),
        pytest.param("inf", 60.0, id="infinity"),
    ],
)
@pytest.mark.asyncio
async def test_retry_after_cooldown(
    monkeypatch: pytest.MonkeyPatch, header: str | None, expected_delay: float
) -> None:
    now = 1000.0
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        nonlocal now
        delays.append(delay)
        now += delay

    monkeypatch.setattr(pacing.time, "monotonic", lambda: now)
    monkeypatch.setattr(pacing.time, "time", lambda: 0.0)
    monkeypatch.setattr(pacing.asyncio, "sleep", sleep)
    pacer = RequestPacer()
    await pacer.defer(header)
    # Only conversion uses wall time; waiting must use the monotonic deadline.
    monkeypatch.setattr(pacing.time, "time", lambda: 999999.0)
    await pacer.acquire()
    assert delays == [expected_delay]


@pytest.mark.asyncio
async def test_deferrals_never_shorten_the_shared_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1000.0
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        nonlocal now
        delays.append(delay)
        now += delay

    monkeypatch.setattr(pacing.time, "monotonic", lambda: now)
    monkeypatch.setattr(pacing.asyncio, "sleep", sleep)
    pacer = RequestPacer()
    await pacer.defer("120")
    now += 10
    await pacer.defer("5")
    await pacer.acquire()
    assert delays == [110.0]


@pytest.mark.asyncio
async def test_rate_limit_date_defers_other_clients_without_retrying_failed_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1000.0
    request_times: list[float] = []
    header = "Thu, 01 Jan 1970 00:02:00 GMT"

    async def sleep(delay: float) -> None:
        nonlocal now
        now += delay

    def respond(_: httpx.Request) -> httpx.Response:
        request_times.append(now)
        if len(request_times) == 1:
            return httpx.Response(429, headers={"Retry-After": header})
        return httpx.Response(200, json={})

    monkeypatch.setattr(pacing.time, "monotonic", lambda: now)
    monkeypatch.setattr(pacing.time, "time", lambda: 0.0)
    monkeypatch.setattr(pacing.asyncio, "sleep", sleep)
    pacer = RequestPacer()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        async with (
            NotehubClient("test", http_client=http_client, pacer=pacer) as first,
            NotehubClient("test", http_client=http_client, pacer=pacer) as second,
        ):
            with pytest.raises(NotehubRateLimitError) as caught:
                await first.request("GET", "projects")
            assert caught.value.retry_after == header
            assert request_times == [1000.0]
            await second.request("GET", "projects")
    assert request_times == [1000.0, 1120.0]


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
