from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from notehub_client import NotehubClient
from notehub_client.errors import (
    NotehubAPIError,
    NotehubAuthenticationError,
    NotehubPermissionError,
    NotehubRateLimitError,
    NotehubResponseError,
    NotehubTransportError,
)
from notehub_client.filters import CursorPagination
from notehub_client.typing.query import QueryValue


class CursorFilter:
    def to_query_params(self) -> dict[str, QueryValue]:
        return {"cursor": "saved"}


class OrganizationFilter:
    def to_query_params(self) -> dict[str, QueryValue]:
        return {"organizationUID": "org:one"}


@pytest.mark.asyncio
@respx.mock
async def test_devices_pagination_and_bearer_auth() -> None:
    route = respx.get("https://api.notefile.net/v1/projects/app:test/devices")
    route.side_effect = [
        httpx.Response(200, json={"devices": [{"uid": "dev:1"}], "has_more": True}),
        httpx.Response(200, json={"devices": [{"uid": "dev:2"}], "has_more": False}),
    ]
    async with NotehubClient("pat") as client:
        devices = await client.devices.collect("app:test")
    assert [d["uid"] for d in devices] == ["dev:1", "dev:2"]
    assert route.calls[0].request.headers["Authorization"] == "Bearer pat"


@pytest.mark.asyncio
@respx.mock
async def test_project_listing_accepts_protocol_filters() -> None:
    route = respx.get("https://api.notefile.net/v1/projects").mock(
        return_value=httpx.Response(200, json={"projects": []})
    )
    async with NotehubClient("pat") as client:
        assert await client.projects.list(filters=OrganizationFilter()) == {"projects": []}
    assert route.calls[0].request.url.params["organizationUID"] == "org:one"


@pytest.mark.asyncio
@respx.mock
async def test_env_body_and_path_encoding() -> None:
    route = respx.put(
        "https://api.notefile.net/v1/projects/app:test/devices/dev:1/environment_variables"
    ).mock(return_value=httpx.Response(204))
    async with NotehubClient("pat") as client:
        assert await client.devices.set_environment("app:test", "dev:1", {"limit": "3"}) is None
    assert route.calls[0].request.read() == b'{"environment_variables":{"limit":"3"}}'


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit_details() -> None:
    respx.get("https://api.notefile.net/v1/projects/app:test").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "9"}, json={"message": "slow"})
    )
    async with NotehubClient("pat") as client:
        with pytest.raises(NotehubRateLimitError) as exc:
            await client.projects.get("app:test")
    assert exc.value.retry_after == "9"


@pytest.mark.asyncio
async def test_external_http_client_lifecycle() -> None:
    transport = httpx.AsyncClient()
    async with NotehubClient("pat", http_client=transport):
        pass
    assert not transport.is_closed
    await transport.aclose()


@pytest.mark.asyncio
async def test_async_token_provider() -> None:
    provider = AsyncMock(return_value="oauth-token")
    transport = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"uid": "app:x"}))
    )
    async with NotehubClient(token_provider=provider, http_client=transport) as client:
        await client.projects.get("app:x")
    provider.assert_awaited_once()
    await transport.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_resources_cover_other_api_areas() -> None:
    respx.get("https://api.notefile.net/v1/organizations").mock(
        return_value=httpx.Response(200, json={"organizations": []})
    )
    async with NotehubClient("pat") as client:
        assert await client.organizations.list() == {"organizations": []}


@pytest.mark.asyncio
@respx.mock
async def test_authentication_and_permission_errors_do_not_echo_response_body() -> None:
    respx.get("https://api.notefile.net/v1/projects/app:unauthorized").mock(
        return_value=httpx.Response(401, json={"message": "do not echo this token"})
    )
    respx.get("https://api.notefile.net/v1/projects/app:forbidden").mock(
        return_value=httpx.Response(403, json={"message": "private response details"})
    )
    async with NotehubClient("pat") as client:
        with pytest.raises(NotehubAuthenticationError) as authentication:
            await client.projects.get("app:unauthorized")
        with pytest.raises(NotehubPermissionError) as permission:
            await client.projects.get("app:forbidden")

    assert "do not echo" not in str(authentication.value)
    assert "private response" not in str(permission.value)


@pytest.mark.asyncio
@respx.mock
async def test_api_errors_expose_status_without_claiming_payload_details() -> None:
    respx.get("https://api.notefile.net/v1/projects/app:missing").mock(
        return_value=httpx.Response(404, json={"message": "missing"})
    )
    async with NotehubClient("pat") as client:
        with pytest.raises(NotehubAPIError) as exc:
            await client.projects.get("app:missing")
    assert exc.value.status_code == 404
    assert not hasattr(exc.value, "payload")


@pytest.mark.asyncio
@respx.mock
async def test_malformed_json_and_paginated_envelopes_raise_response_errors() -> None:
    project = respx.get("https://api.notefile.net/v1/projects/app:bad-json").mock(
        return_value=httpx.Response(200, content=b"not-json")
    )
    devices = respx.get("https://api.notefile.net/v1/projects/app:bad-page/devices").mock(
        return_value=httpx.Response(200, json={"devices": [], "has_more": "yes"})
    )
    async with NotehubClient("pat") as client:
        with pytest.raises(NotehubResponseError, match="invalid JSON"):
            await client.projects.get("app:bad-json")
        with pytest.raises(NotehubResponseError, match="has_more"):
            await client.devices.list("app:bad-page")
    assert project.called and devices.called


def test_client_rejects_invalid_base_url() -> None:
    with pytest.raises(ValueError, match="base_url"):
        NotehubClient("pat", base_url="https://example.com/prefix")


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("", id="empty"),
        pytest.param("../outside", id="parent-traversal"),
        pytest.param("%2e%2e/outside", id="encoded-parent-traversal"),
        pytest.param("/absolute", id="absolute"),
        pytest.param("https://elsewhere", id="absolute-url"),
    ],
)
@pytest.mark.asyncio
async def test_client_rejects_invalid_generic_paths(path: str) -> None:
    async with NotehubClient("pat") as client:
        with pytest.raises(ValueError, match="relative to /v1"):
            await client.request("GET", path)


def test_client_rejects_invalid_tokens_and_timeouts() -> None:
    with pytest.raises(ValueError, match="invalid characters"):
        NotehubClient("token\nwith-control")
    with pytest.raises(ValueError, match="timeout"):
        NotehubClient("pat", timeout=float("nan"))


def test_client_requires_exactly_one_authentication_source() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        NotehubClient()
    with pytest.raises(ValueError, match="exactly one"):
        NotehubClient("pat", token_provider=AsyncMock(return_value="oauth-token"))


def test_client_rejects_a_non_callable_token_provider() -> None:
    with pytest.raises(ValueError, match="async callable"):
        NotehubClient(token_provider=42)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_closed_client_rejects_context_reentry_and_requests() -> None:
    client = NotehubClient("pat")
    await client.aclose()

    with pytest.raises(RuntimeError, match="closed"):
        async with client:
            pass
    with pytest.raises(RuntimeError, match="closed"):
        await client.request("GET", "projects")


@pytest.mark.asyncio
async def test_request_rejects_conflicting_body_and_authentication_options() -> None:
    async with NotehubClient("pat") as client:
        with pytest.raises(ValueError, match="mutually exclusive"):
            await client.request("POST", "projects", json={}, data=b"body")
        with pytest.raises(ValueError, match="controlled by token"):
            await client.request("GET", "projects", headers={"Authorization": "Bearer other"})


@pytest.mark.asyncio
@respx.mock
async def test_note_path_identifiers_are_encoded_and_body_is_preserved() -> None:
    route = respx.post(
        "https://api.notefile.net/v1/projects/app:test/devices/dev:1/notes/sensors%23daily.qi"
    ).mock(return_value=httpx.Response(204))
    async with NotehubClient("pat") as client:
        result = await client.notes.add_qi(
            "app:test", "dev:1", "sensors#daily.qi", {"reading": 4.2, "ok": True}
        )
    assert result is None
    assert route.called
    assert route.calls[0].request.content == b'{"body":{"reading":4.2,"ok":true}}'


@pytest.mark.asyncio
@respx.mock
async def test_database_note_and_environment_delete_operations_use_expected_verbs() -> None:
    add = respx.post(
        "https://api.notefile.net/v1/projects/app:test/devices/dev:one/notes/settings.db/one"
    ).mock(return_value=httpx.Response(200, json={"note": "one"}))
    update = respx.put(
        "https://api.notefile.net/v1/projects/app:test/devices/dev:one/notes/settings.db/one"
    ).mock(return_value=httpx.Response(200, json={"note": "one"}))
    delete = respx.delete(
        "https://api.notefile.net/v1/projects/app:test/devices/dev:one/notes/settings.db/one"
    ).mock(return_value=httpx.Response(204))
    delete_env = respx.delete(
        "https://api.notefile.net/v1/projects/app:test/devices/dev:one/environment_variables/limit"
    ).mock(return_value=httpx.Response(204))

    async with NotehubClient("pat") as client:
        assert await client.notes.add_db(
            "app:test", "dev:one", "settings.db", "one", {"enabled": True}
        ) == {"note": "one"}
        assert await client.notes.update_db(
            "app:test", "dev:one", "settings.db", "one", {"enabled": False}
        ) == {"note": "one"}
        assert await client.notes.delete("app:test", "dev:one", "settings.db", "one") is None
        assert (
            await client.devices.delete_environment_variable("app:test", "dev:one", "limit") is None
        )

    assert all(route.called for route in (add, update, delete, delete_env))
    assert add.calls[0].request.content == b'{"body":{"enabled":true}}'
    assert update.calls[0].request.content == b'{"body":{"enabled":false}}'


@pytest.mark.asyncio
async def test_transport_errors_are_wrapped_without_transport_details() -> None:
    async def fail(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sensitive hostname", request=_request)

    transport = httpx.AsyncClient(transport=httpx.MockTransport(fail))
    try:
        async with NotehubClient("pat", http_client=transport) as client:
            with pytest.raises(NotehubTransportError) as exc:
                await client.projects.get("app:test")
    finally:
        await transport.aclose()
    assert "sensitive hostname" not in str(exc.value)


@pytest.mark.asyncio
@respx.mock
async def test_event_cursor_can_be_resumed_and_moves_forward_page_by_page() -> None:
    route = respx.get("https://api.notefile.net/v1/projects/app:test/events").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "events": [{"event": "first", "when": 1}],
                    "has_more": True,
                    "next_cursor": "cursor-1",
                },
            ),
            httpx.Response(
                200,
                json={
                    "events": [{"event": "second", "when": 2}],
                    "has_more": False,
                    "next_cursor": "cursor-2",
                },
            ),
        ]
    )
    async with NotehubClient("pat") as client:
        events = [
            event
            async for event in client.events.iter(
                "app:test", pagination=CursorPagination(cursor="0")
            )
        ]

    assert [event["event"] for event in events] == ["first", "second"]
    assert [event["when"] for event in events] == [1, 2]
    assert route.calls[0].request.url.params["cursor"] == "0"
    assert route.calls[1].request.url.params["cursor"] == "cursor-1"


@pytest.mark.asyncio
@respx.mock
async def test_event_cursor_must_advance_when_more_events_remain() -> None:
    route = respx.get("https://api.notefile.net/v1/projects/app:test/events").mock(
        side_effect=[
            httpx.Response(
                200,
                json={"events": [{"event": "first"}], "has_more": True, "next_cursor": "next"},
            ),
            httpx.Response(
                200,
                json={"events": [{"event": "second"}], "has_more": True, "next_cursor": "next"},
            ),
        ]
    )
    async with NotehubClient("pat") as client:
        with pytest.raises(NotehubResponseError, match="missing or repeated"):
            _ = [
                event
                async for event in client.events.iter(
                    "app:test", pagination=CursorPagination(cursor="0")
                )
            ]
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_event_cursor_cannot_be_combined_with_page_or_sort_parameters() -> None:
    async with NotehubClient("pat") as client:
        with pytest.raises(ValueError, match="cannot be combined"):
            await client.events.list("app:test", pagination=CursorPagination(cursor="0"), pageNum=1)
        with pytest.raises(ValueError, match="cannot be combined"):
            await client.events.list(
                "app:test", pagination=CursorPagination(cursor="0"), sortOrder="desc"
            )
        with pytest.raises(ValueError, match="specified twice"):
            await client.events.list(
                "app:test", pagination=CursorPagination(cursor="0"), filters=CursorFilter()
            )
