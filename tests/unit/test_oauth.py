import asyncio
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from notehub_client.errors import NotehubDependencyError, NotehubOAuthError
from notehub_client.oauth import TOKEN_URL, NotehubOAuthTokenProvider


def test_oauth_reports_missing_optional_dependency_at_feature_boundary() -> None:
    with patch.dict("sys.modules", {"authlib.integrations.httpx_client": None}):
        with pytest.raises(NotehubDependencyError) as captured:
            NotehubOAuthTokenProvider("client-id", "client-secret")

    assert captured.value.feature == "OAuth client credentials"
    assert captured.value.extra == "oauth"
    assert captured.value.missing_module == "authlib"


@pytest.mark.asyncio
@respx.mock
async def test_oauth_uses_form_encoded_client_credentials_and_caches_token() -> None:
    token = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "oauth-token", "token_type": "Bearer", "expires_in": 1800},
        )
    )
    provider = NotehubOAuthTokenProvider("client-id", "client-secret")
    try:
        assert await provider() == "oauth-token"
        assert await provider() == "oauth-token"
    finally:
        await provider.aclose()

    assert token.call_count == 1
    form = parse_qs(token.calls[0].request.content.decode())
    assert form == {
        "client_id": ["client-id"],
        "client_secret": ["client-secret"],
        "grant_type": ["client_credentials"],
    }


@pytest.mark.asyncio
@respx.mock
async def test_oauth_concurrent_initial_requests_share_one_token_exchange() -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "oauth-token", "token_type": "Bearer", "expires_in": 1800},
        )
    )
    provider = NotehubOAuthTokenProvider("client-id", "client-secret")
    try:
        tokens = await asyncio.gather(*(provider() for _ in range(8)))
    finally:
        await provider.aclose()

    assert tokens == ["oauth-token"] * 8
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_oauth_renews_expired_token_before_returning_it() -> None:
    route = respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(
                200,
                json={"access_token": "first-token", "token_type": "Bearer", "expires_in": 1800},
            ),
            httpx.Response(
                200,
                json={"access_token": "renewed-token", "token_type": "Bearer", "expires_in": 1800},
            ),
        ]
    )
    provider = NotehubOAuthTokenProvider("client-id", "client-secret")
    try:
        assert await provider() == "first-token"
        provider._client.token = {
            "access_token": "expired-token",
            "token_type": "Bearer",
            "expires_at": 0,
        }
        assert await provider() == "renewed-token"
    finally:
        await provider.aclose()

    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_oauth_failure_does_not_disclose_credentials_or_server_body() -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            401,
            json={"error": "invalid_client", "description": "client-secret"},
        )
    )
    provider = NotehubOAuthTokenProvider("client-id", "client-secret")
    try:
        with pytest.raises(NotehubOAuthError) as exc:
            await provider()
    finally:
        await provider.aclose()

    assert "client-secret" not in str(exc.value)


@pytest.mark.parametrize(
    ("response_body", "message"),
    [
        pytest.param(
            {"token_type": "Bearer", "expires_in": 1800},
            "did not contain an access token",
            id="missing-token",
        ),
        pytest.param(
            {"access_token": "", "token_type": "Bearer", "expires_in": 1800},
            "did not contain an access token",
            id="empty-token",
        ),
        pytest.param(
            {"access_token": "token\\nwith-control", "token_type": "Bearer", "expires_in": 1800},
            "invalid access token",
            id="invalid-token",
        ),
    ],
)
@pytest.mark.asyncio
@respx.mock
async def test_oauth_rejects_missing_empty_and_invalid_access_tokens(
    response_body: dict[str, object], message: str
) -> None:
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=response_body))
    provider = NotehubOAuthTokenProvider("client-id", "client-secret")
    try:
        with pytest.raises(NotehubOAuthError, match=message):
            await provider()
    finally:
        await provider.aclose()


def test_oauth_provider_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="nonempty"):
        NotehubOAuthTokenProvider("", "secret")
    with pytest.raises(ValueError, match="leeway"):
        NotehubOAuthTokenProvider("id", "secret", leeway=-1)


@pytest.mark.asyncio
async def test_oauth_context_manager_closes_provider() -> None:
    provider = NotehubOAuthTokenProvider("client-id", "client-secret")
    async with provider:
        assert not provider._client.is_closed
    assert provider._client.is_closed is True
    with pytest.raises(RuntimeError, match="closed"):
        await provider()


@pytest.mark.asyncio
async def test_oauth_context_manager_rejects_reentry_after_close() -> None:
    provider = NotehubOAuthTokenProvider("client-id", "client-secret")
    await provider.aclose()

    with pytest.raises(RuntimeError, match="closed"):
        async with provider:
            pass
