from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from notehub_client import NotehubClient, NotehubRateLimitError
from notehub_client.resources import NotehubResources


@pytest.mark.asyncio
@respx.mock
async def test_devices_pagination_and_bearer_auth():
    route = respx.get("https://api.notefile.net/v1/projects/app:test/devices")
    route.side_effect = [
        httpx.Response(200, json={"devices": [{"uid": "dev:1"}], "has_more": True}),
        httpx.Response(200, json={"devices": [{"uid": "dev:2"}], "has_more": False}),
    ]
    async with NotehubClient("pat") as client:
        devices = await client.get_devices("app:test")
    assert [d["uid"] for d in devices] == ["dev:1", "dev:2"]
    assert route.calls[0].request.headers["Authorization"] == "Bearer pat"


@pytest.mark.asyncio
@respx.mock
async def test_env_body_and_path_encoding():
    route = respx.put(
        "https://api.notefile.net/v1/projects/app:test/devices/dev:1/environment_variables"
    ).mock(return_value=httpx.Response(204))
    async with NotehubClient("pat") as client:
        assert await client.set_environment_variables("app:test", "dev:1", {"limit": "3"}) is None
    assert route.calls[0].request.read() == b'{"environment_variables":{"limit":"3"}}'


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit_details():
    respx.get("https://api.notefile.net/v1/projects/app:test").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "9"}, json={"message": "slow"})
    )
    async with NotehubClient("pat") as client:
        with pytest.raises(NotehubRateLimitError) as exc:
            await client.get_project("app:test")
    assert exc.value.retry_after == "9"


@pytest.mark.asyncio
async def test_external_http_client_lifecycle():
    transport = httpx.AsyncClient()
    async with NotehubClient("pat", http_client=transport):
        pass
    assert not transport.is_closed
    await transport.aclose()


@pytest.mark.asyncio
async def test_async_token_provider():
    provider = AsyncMock(return_value="oauth-token")
    transport = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"uid": "app:x"}))
    )
    async with NotehubClient(token_provider=provider, http_client=transport) as client:
        await client.get_project("app:x")
    provider.assert_awaited_once()
    await transport.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_resources_cover_other_api_areas():
    respx.get("https://api.notefile.net/v1/organizations").mock(
        return_value=httpx.Response(200, json={"organizations": []})
    )
    async with NotehubClient("pat") as client:
        assert await NotehubResources(client).list_organizations() == {"organizations": []}
