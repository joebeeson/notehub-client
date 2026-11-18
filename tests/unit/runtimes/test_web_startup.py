"""Dashboard startup advertises only a ready listener."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from secrets import token_urlsafe
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import FastAPI

from notehub_client.runtimes import api, web


@pytest.mark.parametrize("launch", [True, False], ids=["auto-launch", "no-launch"])
def test_dashboard_announces_ready_listener(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], launch: bool
) -> None:
    thread_factory = Mock()
    monkeypatch.setattr(web, "threading", SimpleNamespace(Thread=thread_factory))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        assert "Dashboard:" not in capsys.readouterr().out
        thread_factory.assert_not_called()
        yield

    app = FastAPI(lifespan=lifespan)
    app.state.bootstrap_secret = token_urlsafe()
    app.get("/dashboard")(lambda: {"ready": True})
    monkeypatch.setattr(api, "create_app", lambda **_: app)

    async def probe(server: web._DashboardServer) -> None:
        url = capsys.readouterr().out.strip().removeprefix("Dashboard: ")
        parsed = urlsplit(url)
        listeners = server.servers[0].sockets
        assert listeners is not None
        assert listeners[0].getsockname() == ("127.0.0.1", parsed.port)
        async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
            response = await client.get(url)
        assert response.json() == {"ready": True}
        if launch:
            thread_factory.assert_called_once_with(
                target=web.webbrowser.open, args=(url,), daemon=True
            )
            thread_factory.return_value.start.assert_called_once_with()
        else:
            thread_factory.assert_not_called()

    monkeypatch.setattr(web._DashboardServer, "main_loop", probe)
    web.main([] if launch else ["--no-launch"])


def test_failed_lifespan_does_not_launch_or_advertise_dashboard(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    thread_factory = Mock()
    monkeypatch.setattr(web, "threading", SimpleNamespace(Thread=thread_factory))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        await _fail_startup()
        yield

    async def _fail_startup() -> None:
        raise RuntimeError("test startup failure")

    app = FastAPI(lifespan=lifespan)
    app.state.bootstrap_secret = token_urlsafe()
    monkeypatch.setattr(api, "create_app", lambda **_: app)
    with pytest.raises(SystemExit) as failure:
        web.main([])
    assert failure.value.code not in (None, 0)
    assert "Dashboard:" not in capsys.readouterr().out
    thread_factory.assert_not_called()
