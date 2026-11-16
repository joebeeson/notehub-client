import logging

import httpx
import pytest
import respx

from notehub_client import NotehubClient
from notehub_client.errors import NotehubAPIError, NotehubOAuthError, NotehubTransportError
from notehub_client.oauth import TOKEN_URL, NotehubOAuthTokenProvider


@pytest.mark.asyncio
@respx.mock
async def test_successful_request_is_debug_logged_without_query_values(caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="notehub_client.client")
    respx.get("https://api.notefile.net/v1/projects/app:test").mock(
        return_value=httpx.Response(200, json={"uid": "app:test"})
    )

    async with NotehubClient("pat") as client:
        await client.request("GET", "projects/app:test", params={"private": "query-secret"})

    assert "Notehub API response" in caplog.text
    assert "method='GET'" in caplog.text
    assert "status_code=200" in caplog.text
    assert "duration_ms=" in caplog.text
    assert "query-secret" not in caplog.text
    assert "Bearer pat" not in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_transient_api_failure_is_warn_logged_without_response_body(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="notehub_client.client")
    respx.get("https://api.notefile.net/v1/projects/app:test").mock(
        return_value=httpx.Response(
            503,
            headers={"Retry-After": "7"},
            json={"message": "private response detail"},
        )
    )

    async with NotehubClient("pat") as client:
        with pytest.raises(NotehubAPIError):
            await client.request("GET", "projects/app:test")

    assert "Notehub API response failed" in caplog.text
    assert "status_code=503" in caplog.text
    assert "retry_after='7'" in caplog.text
    assert "private response detail" not in caplog.text


@pytest.mark.asyncio
async def test_transport_failure_logs_type_without_transport_message(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="notehub_client.client")

    async def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private-hostname", request=request)

    transport = httpx.AsyncClient(transport=httpx.MockTransport(fail))
    try:
        async with NotehubClient("pat", http_client=transport) as client:
            with pytest.raises(NotehubTransportError):
                await client.request("GET", "projects/app:test")
    finally:
        await transport.aclose()

    assert "Notehub transport failed" in caplog.text
    assert "error_type='ConnectError'" in caplog.text
    assert "private-hostname" not in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_oauth_refresh_is_info_logged_once_without_credentials_or_token(caplog) -> None:
    caplog.set_level(logging.INFO, logger="notehub_client.oauth")
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "private-token", "token_type": "Bearer", "expires_in": 1800},
        )
    )
    provider = NotehubOAuthTokenProvider("private-client-id", "private-client-secret")
    try:
        assert await provider() == "private-token"
        assert await provider() == "private-token"
    finally:
        await provider.aclose()

    refresh_logs = [record for record in caplog.records if "token refreshed" in record.message]
    assert len(refresh_logs) == 1
    assert "leeway_seconds=60" in refresh_logs[0].message
    assert "private-token" not in caplog.text
    assert "private-client-id" not in caplog.text
    assert "private-client-secret" not in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_oauth_failure_logs_safe_error_type_without_server_details(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="notehub_client.oauth")
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            401,
            json={"error": "invalid_client", "description": "private server detail"},
        )
    )
    provider = NotehubOAuthTokenProvider("client-id", "client-secret")
    try:
        with pytest.raises(NotehubOAuthError):
            await provider()
    finally:
        await provider.aclose()

    assert "Notehub OAuth token exchange failed" in caplog.text
    assert "error_type='OAuthError'" in caplog.text
    assert "private server detail" not in caplog.text
    assert "client-secret" not in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_successful_mutations_are_info_logged_without_payloads(caplog) -> None:
    caplog.set_level(logging.INFO, logger="notehub_client.resources.devices")
    caplog.set_level(logging.INFO, logger="notehub_client.resources.notes")
    base = "https://api.notefile.net/v1/projects/app:test/devices/dev:one"
    respx.put(f"{base}/environment_variables").mock(return_value=httpx.Response(204))
    respx.delete(f"{base}/environment_variables/password").mock(return_value=httpx.Response(204))
    respx.post(f"{base}/notes/settings.qi").mock(return_value=httpx.Response(204))
    respx.post(f"{base}/notes/settings.db/note:one").mock(return_value=httpx.Response(204))
    respx.put(f"{base}/notes/settings.db/note:one").mock(return_value=httpx.Response(204))
    respx.delete(f"{base}/notes/settings.db/note:one").mock(return_value=httpx.Response(204))

    async with NotehubClient("pat") as client:
        await client.devices.set_environment(
            "app:test", "dev:one", {"password": "private-env-value"}
        )
        await client.devices.delete_environment_variable("app:test", "dev:one", "password")
        await client.notes.add_qi(
            "app:test", "dev:one", "settings.qi", {"secret": "private-note-body"}
        )
        await client.notes.add_db(
            "app:test", "dev:one", "settings.db", "note:one", {"secret": "private-note-body"}
        )
        await client.notes.update_db(
            "app:test", "dev:one", "settings.db", "note:one", {"secret": "private-note-body"}
        )
        await client.notes.delete("app:test", "dev:one", "settings.db", "note:one")

    assert "Device environment updated" in caplog.text
    assert "value_count=1" in caplog.text
    assert "Device environment variable removed" in caplog.text
    assert "Notehub queue note added" in caplog.text
    assert "Notehub database note added" in caplog.text
    assert "Notehub database note updated" in caplog.text
    assert "Notehub database note deleted" in caplog.text
    assert "private-env-value" not in caplog.text
    assert "private-note-body" not in caplog.text
