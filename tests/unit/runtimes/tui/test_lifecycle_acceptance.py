"""Pilot acceptance coverage for TUI scope and session lifetimes."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from textual.css.query import NoMatches
from textual.widgets import DataTable, Select, Static

from notehub_client.errors import NotehubAPIError, NotehubAuthenticationError
from notehub_client.runtimes.tui.app import NotehubApp
from notehub_client.runtimes.tui.demo import DEMO_PROJECT_UID, DemoReadService
from notehub_client.runtimes.tui.screens.overview import OverviewPanel
from notehub_client.runtimes.tui.state import PageResult, TUIOptions, ViewId


class _DelayedProjectService:
    def __init__(self, delegate: Any, old_project: str, new_project: str) -> None:
        self.delegate = delegate
        self.old_project = old_project
        self.new_project = new_project
        self.old_read_started = asyncio.Event()
        self.old_read_cancelled = asyncio.Event()
        self.new_scope_loaded = asyncio.Event()
        self.release_old_read = asyncio.Event()

    async def read(self, operation: str, **kwargs: Any) -> PageResult:
        project_uid = kwargs.get("project_uid")
        if operation == "events" and project_uid == self.old_project:
            self.old_read_started.set()
            try:
                await self.release_old_read.wait()
            except asyncio.CancelledError:
                self.old_read_cancelled.set()
                raise
            return PageResult(
                rows=({"event": "old-project-event"},),
                row_keys=("old-project-event",),
                has_more=False,
            )
        result = await self.delegate.read(operation, **kwargs)
        if operation == "events" and project_uid == self.new_project:
            self.new_scope_loaded.set()
        return result


class _PendingReadService:
    def __init__(self) -> None:
        self.armed = False
        self.read_started = asyncio.Event()
        self.read_cancelled = asyncio.Event()
        self.release_read = asyncio.Event()

    async def read(self, operation: str, **kwargs: Any) -> PageResult:
        if operation == "projects":
            return PageResult(
                rows=({"uid": "app:acceptance", "label": "Acceptance"},),
                row_keys=("app:acceptance",),
            )
        if operation == "events" and self.armed:
            self.read_started.set()
            try:
                await self.release_read.wait()
            except asyncio.CancelledError:
                self.read_cancelled.set()
                raise
        if operation == "project":
            return PageResult(
                rows=({"uid": "app:acceptance", "label": "Acceptance"},),
                row_keys=("app:acceptance",),
            )
        return PageResult()


class _RetainingFailureService:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.refresh_started = asyncio.Event()
        self.release_refresh = asyncio.Event()

    async def read(self, operation: str, **kwargs: Any) -> PageResult:
        if operation == "events":
            self.refresh_started.set()
            await self.release_refresh.wait()
            raise NotehubAPIError(503, "private response body")
        return await self.delegate.read(operation, **kwargs)


class _OwnershipService:
    async def read(self, operation: str, **kwargs: Any) -> PageResult:
        if operation == "projects":
            return PageResult(
                rows=({"uid": "app:acceptance", "label": "Acceptance"},),
                row_keys=("app:acceptance",),
            )
        if operation == "project":
            return PageResult(
                rows=({"uid": "app:acceptance", "label": "Acceptance"},),
                row_keys=("app:acceptance",),
            )
        return PageResult()


@pytest.mark.asyncio
async def test_delayed_old_project_result_cannot_repaint_new_project() -> None:
    old_project, new_project = DEMO_PROJECT_UID, "app:demo-empty"
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=old_project))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        assert isinstance(app.service, DemoReadService)
        delayed = _DelayedProjectService(app.service, old_project, new_project)
        app.service = delayed  # type: ignore[assignment]
        app.query_one(OverviewPanel).service = delayed

        app.action_navigate("events")
        await asyncio.wait_for(delayed.old_read_started.wait(), timeout=1)

        app.query_one("#project", Select).value = new_project
        await asyncio.wait_for(delayed.new_scope_loaded.wait(), timeout=1)
        assert app.project_uid == new_project
        assert app.view is ViewId.OVERVIEW
        assert app.result.rows == ()
        await pilot.pause(0.1)
        cancelled_on_switch = delayed.old_read_cancelled.is_set()

        delayed.release_old_read.set()
        await pilot.pause(0.1)

        assert app.project_uid == new_project
        assert app.view is ViewId.OVERVIEW
        assert app.result.rows == ()
        assert app.query_one("#records", DataTable).row_count == 0
        assert app.query_one(OverviewPanel).events == ()
        assert cancelled_on_switch


@pytest.mark.asyncio
@pytest.mark.parametrize("termination", ["disconnect", "exit"], ids=["disconnect", "exit"])
async def test_pending_read_is_cancelled_on_disconnect_or_exit(termination: str) -> None:
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        service = _PendingReadService()
        app.service = service  # type: ignore[assignment]
        service.armed = True

        app.action_navigate("events")
        await asyncio.wait_for(service.read_started.wait(), timeout=1)

        if termination == "disconnect":
            await pilot.click("#disconnect")
            await asyncio.wait_for(service.read_cancelled.wait(), timeout=1)
            assert app.query_one("#login").display is True
        else:
            await pilot.press("q")
            await asyncio.wait_for(service.read_cancelled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_authentication_failure_disconnects_from_inside_fetch_worker() -> None:
    class RejectedService:
        async def read(self, operation: str, **kwargs: Any) -> PageResult:
            raise NotehubAuthenticationError(401, "rejected")

    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        app.service = RejectedService()  # type: ignore[assignment]
        app.action_navigate("events")
        await pilot.pause(0.1)

        assert app.service is None
        assert app.query_one("#login").display is True
        assert "Authentication rejected" in app.query_one("#status", Static).render().plain


@pytest.mark.asyncio
@pytest.mark.parametrize("owned", [False, True], ids=["borrowed", "owned"])
@pytest.mark.parametrize("termination", ["disconnect", "exit"], ids=["disconnect", "exit"])
async def test_app_closes_only_owned_client_once(
    owned: bool, termination: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = Mock()
    client.aclose = AsyncMock()
    service = _OwnershipService()
    options = TUIOptions(project_uid="app:acceptance")
    app = NotehubApp(options=options) if owned else NotehubApp(client=client, options=options)

    if owned:
        monkeypatch.setenv("NOTEHUB_TOKEN", "test-token")

    with (
        patch("notehub_client.runtimes.tui.app.TUIReadService", return_value=service),
        patch("notehub_client.runtimes.tui.session.NotehubClient", return_value=client),
    ):
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.1)
            if termination == "disconnect":
                await pilot.click("#disconnect")
                await pilot.pause()
            else:
                await pilot.press("q")

    if owned:
        client.aclose.assert_awaited_once()
    else:
        client.aclose.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_keeps_last_good_rows_visible_while_pending_and_after_failure() -> None:
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        app.action_navigate("events")
        await pilot.pause(0.1)
        previous_rows = app.result.rows
        assert previous_rows

        service = _RetainingFailureService(app.service)
        app.service = service  # type: ignore[assignment]
        app.action_refresh()
        await asyncio.wait_for(service.refresh_started.wait(), timeout=1)

        assert app.result.rows == previous_rows
        assert app.query_one("#records", DataTable).row_count == len(previous_rows)

        service.release_refresh.set()
        await pilot.pause(0.1)

        assert app.result.rows == previous_rows
        assert app.query_one("#records", DataTable).row_count == len(previous_rows)
        status = app.query_one("#status", Static).render().plain
        assert "Notehub service unavailable" in status
        assert "private response body" not in status


@pytest.mark.asyncio
async def test_reconnect_rebuilds_panels_with_the_new_service() -> None:
    app = NotehubApp(options=TUIOptions())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        first = _OwnershipService()
        app.service = first  # type: ignore[assignment]
        await app._install_panels()
        assert app.query_one(OverviewPanel).service is first
        app.activity.durations.append(12.3)
        app.signals_visible = True
        app._update_signals()

        await app.disconnect()
        assert not app.activity.durations
        assert app.signals_visible is False
        assert app.query_one("#signals-strip").display is False
        with pytest.raises(NoMatches):
            app.query_one(OverviewPanel)

        second = _OwnershipService()
        with (
            patch.object(app.session, "connect", return_value=object()),
            patch("notehub_client.runtimes.tui.app.TUIReadService", return_value=second),
        ):
            app.query_one("#connect").press()
            await pilot.pause(0.2)

        assert app.query_one(OverviewPanel).service is second
