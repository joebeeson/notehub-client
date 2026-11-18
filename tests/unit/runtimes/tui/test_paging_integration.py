"""Integrated cursor-paging behavior through the Textual workspace."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from rich.text import Text
from textual.content import Content
from textual.widgets import Button, DataTable, Static, TabbedContent

from notehub_client.filters import Query
from notehub_client.runtimes.tui.app import NotehubApp
from notehub_client.runtimes.tui.demo import DEMO_PROJECT_UID, DemoReadService
from notehub_client.runtimes.tui.screens.fleets import FleetDetailView, FleetListView
from notehub_client.runtimes.tui.state import PageResult, TUIOptions, ViewId


@pytest.mark.asyncio
async def test_fleet_event_history_retains_empty_pages_and_rejects_bad_refresh() -> None:
    class FleetEvents(DemoReadService):
        def __init__(self) -> None:
            super().__init__()
            self.requests: list[tuple[str | None, str, Query | None]] = []
            self.bad_refresh = False
            self.hold_next = False
            self.pending = asyncio.Event()
            self.returned_after_cancel = False

        async def read(
            self,
            operation: str,
            *,
            project_uid: str | None = None,
            uid: str | None = None,
            query: Query | None = None,
            cursor: str = "0",
            page_num: int = 1,
        ) -> PageResult:
            if operation == "fleets":
                return PageResult(
                    rows=({"uid": "fleet:a"}, {"uid": "fleet:b"}),
                    row_keys=("fleet:a", "fleet:b"),
                    has_more=False,
                )
            if operation != "fleet_events":
                return await super().read(
                    operation,
                    project_uid=project_uid,
                    uid=uid,
                    query=query,
                    cursor=cursor,
                    page_num=page_num,
                )
            self.requests.append((uid, cursor, query))
            if cursor == "0":
                key = f"{uid}-first"
                return PageResult(
                    rows=({"event": key},),
                    row_keys=(key,),
                    has_more=True,
                    next_cursor="0" if self.bad_refresh else "empty",
                )
            if cursor == "empty":
                if self.hold_next:
                    self.pending.set()
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        self.returned_after_cancel = True
                return PageResult(has_more=True, next_cursor="last")
            return PageResult(rows=({"event": "last"},), row_keys=("last",), has_more=False)

    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.35)
        service = FleetEvents()
        app.service = service
        app.action_navigate("fleets")
        await pilot.pause(0.35)
        detail = app.query_one(FleetDetailView)

        async def open_fleet(row: int) -> None:
            table = app.query_one(FleetListView).query_one(DataTable)
            table.move_cursor(row=row)
            table.focus()
            await pilot.press("enter")
            await pilot.pause(0.35)
            detail.query_one(TabbedContent).active = "fleet-events"
            await pilot.pause(0.35)

        await open_fleet(0)
        previous = detail.query_one("#fleet-events-previous", Button)
        following = detail.query_one("#fleet-events-next", Button)
        assert previous.disabled and not following.disabled
        assert await pilot.click(following)
        await pilot.pause(0.35)
        assert detail.events is not None and not detail.events.rows
        assert not previous.disabled and not following.disabled
        assert await pilot.click(following)
        await pilot.pause(0.35)
        assert detail.events is not None and detail.events.row_keys == ("last",)
        assert following.disabled
        assert await pilot.click(previous)
        await pilot.pause(0.35)
        assert detail.events is not None and not detail.events.rows
        assert await pilot.click(following)
        await pilot.pause(0.35)
        assert len(service.requests) == 3

        service.bad_refresh = True
        app.action_refresh()
        await pilot.pause(0.35)
        assert detail.events is not None and detail.events.row_keys == ("last",)
        assert not previous.disabled and following.disabled
        service.bad_refresh = False
        await pilot.press("escape")
        await pilot.pause(0.35)
        await open_fleet(1)
        assert detail.events is not None and detail.events.row_keys == ("fleet:b-first",)
        assert previous.disabled
        await pilot.press("escape")
        await pilot.pause(0.35)
        await open_fleet(0)
        assert detail.events is not None and detail.events.row_keys == ("last",)
        assert len(service.requests) == 5

        query = Query().files("health.qo")
        app.states[app._key()] = replace(app.current_state, query=query)
        app._discard_other_cursor_queries()
        app.action_refresh()
        await pilot.pause(0.35)
        assert service.requests[-1] == ("fleet:a", "0", query)
        assert previous.disabled and not following.disabled

        service.hold_next = True
        following.press()
        await asyncio.wait_for(service.pending.wait(), timeout=2)
        await pilot.press("escape")
        await pilot.pause(0.35)
        await open_fleet(1)
        assert service.returned_after_cancel
        assert detail.events is not None and detail.events.row_keys == ("fleet:b-first",)
        await pilot.press("escape")
        await pilot.pause(0.35)
        await open_fleet(0)
        assert detail.events is not None and detail.events.row_keys == ("fleet:a-first",)
        assert previous.disabled


@pytest.mark.asyncio
async def test_next_and_previous_use_bounded_page_snapshots() -> None:
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        app.action_navigate("events")
        await pilot.pause(0.1)

        first_page = app.result
        service = app.service
        assert isinstance(service, DemoReadService)
        first_reads = service.reads.count("events")
        assert app._cursor_history().current_cursor == "0"
        assert app.query_one("#previous", Button).disabled

        await pilot.click("#next")
        await pilot.pause(0.1)
        second_page = app.result
        assert second_page.rows != first_page.rows
        assert app.current_state.cursor == "50"
        assert app.query_one("#previous", Button).disabled is False
        assert service.reads.count("events") == first_reads + 1

        await pilot.click("#previous")
        await pilot.pause()
        assert app.result.rows == first_page.rows
        assert app.current_state.cursor == "0"
        assert app.query_one("#previous", Button).disabled
        assert service.reads.count("events") == first_reads + 1

        await pilot.click("#next")
        await pilot.pause()
        assert app.result.rows == second_page.rows
        assert app.current_state.cursor == "50"
        assert service.reads.count("events") == first_reads + 1


@pytest.mark.asyncio
async def test_applying_a_filter_starts_a_new_cursor_history() -> None:
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        app.action_navigate("events")
        await pilot.pause(0.1)
        app._page(True)
        await pilot.pause(0.1)
        old_history_key = app._cursor_history_key()
        old_history = app._cursor_history()
        assert old_history.current_cursor == "50"

        new_query = Query().files("health.qo")
        app.states[app._key()] = replace(app.current_state, query=new_query)
        app._discard_other_cursor_queries()
        await pilot.click("#refresh")
        await pilot.pause(0.1)

        assert all(row.get("file") == "health.qo" for row in app.result.rows)
        assert app.current_state.cursor == "0"
        assert app._cursor_history_key() != old_history_key
        assert app._cursor_history() is not old_history
        assert app._cursor_history().current_cursor == "0"
        assert app._cursor_history().can_previous is False


@pytest.mark.asyncio
async def test_repeated_cursor_keeps_last_good_page_and_refresh_restarts() -> None:
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        original = app.service
        assert isinstance(original, DemoReadService)

        class RepeatingService:
            cursors: list[str] = []
            next_by_cursor = {"0": "a", "a": "b", "b": "a"}

            async def read(
                self,
                operation: str,
                *,
                project_uid: str | None = None,
                uid: str | None = None,
                query: Query | None = None,
                cursor: str = "0",
                page_num: int = 1,
            ) -> PageResult:
                if operation != "events":
                    return await original.read(
                        operation,
                        project_uid=project_uid,
                        uid=uid,
                        query=query,
                        cursor=cursor,
                        page_num=page_num,
                    )
                self.cursors.append(cursor)
                return PageResult(
                    rows=({"event": f"ev:{cursor}", "device": "dev:demo-west"},),
                    row_keys=(f"ev:{cursor}",),
                    has_more=True,
                    next_cursor=self.next_by_cursor[cursor],
                )

        service = RepeatingService()
        app.service = service
        app.action_navigate("events")
        await pilot.pause(0.1)
        assert service.cursors == ["0"]

        await pilot.click("#next")
        await pilot.pause(0.1)
        last_good_page = app.result
        assert service.cursors == ["0", "a"]

        await pilot.click("#next")
        await pilot.pause(0.1)
        assert service.cursors == ["0", "a", "b"]
        assert app.result.rows == last_good_page.rows
        assert app.current_state.cursor == "a"
        status = app.query_one("#status", Static).render()
        assert isinstance(status, (Text, Content))
        assert "repeated" in status.plain.casefold()

        service.next_by_cursor["0"] = "0"
        await pilot.click("#refresh")
        await pilot.pause(0.35)
        assert app.result is last_good_page
        assert app._cursor_history().current is last_good_page
        assert app._cursor_history().can_previous
        service.next_by_cursor["0"] = "a"

        await pilot.click("#refresh")
        await pilot.pause(0.1)
        assert service.cursors == ["0", "a", "b", "0", "0"]
        assert app.current_state.cursor == "0"
        assert app.result.rows[0]["event"] == "ev:0"
        assert app.query_one("#previous", Button).disabled


@pytest.mark.asyncio
async def test_device_back_restores_paged_event_context_and_cached_previous() -> None:
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        app.action_navigate("events")
        await pilot.pause(0.1)
        await pilot.click("#next")
        await pilot.pause(0.1)
        page_two_keys = app.result.row_keys
        service = app.service
        assert isinstance(service, DemoReadService)
        events_reads = service.reads.count("events")

        table = app.query_one("#records", DataTable)
        table.move_cursor(row=4)
        table.focus()
        selected_key = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        await pilot.press("d")
        await pilot.pause(0.1)
        assert app.view is ViewId.DEVICES
        assert app.operation == "device"

        await pilot.press("escape")
        await pilot.pause(0.1)
        assert app.view is ViewId.EVENTS
        assert app.operation == "events"
        assert app.result.row_keys == page_two_keys
        assert app.current_state.selected_key == selected_key
        assert app._cursor_history().current_cursor == "50"

        await pilot.click("#previous")
        await pilot.pause()
        assert app.current_state.cursor == "0"
        assert app.query_one("#previous", Button).disabled
        assert service.reads.count("events") == events_reads
