"""Integrated cursor-paging behavior through the Textual workspace."""

from __future__ import annotations

from dataclasses import replace

import pytest
from textual.widgets import Button, DataTable

from notehub_client.filters import Query
from notehub_client.runtimes.tui.app import NotehubApp
from notehub_client.runtimes.tui.demo import DEMO_PROJECT_UID, DemoReadService
from notehub_client.runtimes.tui.state import PageResult, TUIOptions, ViewId


@pytest.mark.asyncio
async def test_next_and_previous_use_bounded_page_snapshots() -> None:
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        app.action_navigate("events")
        await pilot.pause(0.1)

        first_page = app.result
        first_reads = app.service.reads.count("events")
        assert app._cursor_history().current_cursor == "0"
        assert app.query_one("#previous", Button).disabled

        await pilot.click("#next")
        await pilot.pause(0.1)
        second_page = app.result
        assert second_page.rows != first_page.rows
        assert app.current_state.cursor == "50"
        assert app.query_one("#previous", Button).disabled is False
        assert app.service.reads.count("events") == first_reads + 1

        await pilot.click("#previous")
        await pilot.pause()
        assert app.result.rows == first_page.rows
        assert app.current_state.cursor == "0"
        assert app.query_one("#previous", Button).disabled
        assert app.service.reads.count("events") == first_reads + 1

        await pilot.click("#next")
        await pilot.pause()
        assert app.result.rows == second_page.rows
        assert app.current_state.cursor == "50"
        assert app.service.reads.count("events") == first_reads + 1


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

            async def read(self, operation: str, **kwargs: object) -> PageResult:
                if operation != "events":
                    return await original.read(operation, **kwargs)
                cursor = str(kwargs["cursor"])
                self.cursors.append(cursor)
                return PageResult(
                    rows=({"event": f"ev:{cursor}", "device": "dev:demo-west"},),
                    row_keys=(f"ev:{cursor}",),
                    has_more=True,
                    next_cursor=self.next_by_cursor[cursor],
                )

        service = RepeatingService()
        app.service = service  # type: ignore[assignment]
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
        assert "repeated" in app.query_one("#status").render().plain.casefold()

        await pilot.click("#refresh")
        await pilot.pause(0.1)
        assert service.cursors == ["0", "a", "b", "0"]
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
        events_reads = app.service.reads.count("events")

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
        assert app.service.reads.count("events") == events_reads
