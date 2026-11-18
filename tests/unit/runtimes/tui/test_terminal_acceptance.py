"""Keyboard-only acceptance coverage for the terminal workspace shell."""

from __future__ import annotations

import pytest
from textual.command import CommandPalette
from textual.pilot import Pilot
from textual.widgets import Button, ContentSwitcher, DataTable, Input, Select

from notehub_client.runtimes.tui.app import NotehubApp
from notehub_client.runtimes.tui.demo import DEMO_PROJECT_UID
from notehub_client.runtimes.tui.state import TUIOptions, ViewId


async def _choose_demo_project(pilot: Pilot[None], app: NotehubApp) -> None:
    """Select the first project through the focused picker, using only keys."""
    project_picker = app.query_one("#project", Select)
    assert app.focused is project_picker

    await pilot.press("enter")
    await pilot.pause(0.05)
    await pilot.press("down")
    await pilot.pause(0.05)
    await pilot.press("enter")
    await pilot.pause(0.1)

    assert app.project_uid == DEMO_PROJECT_UID


def _text_keys(value: str) -> list[str]:
    """Convert text to Pilot key names, including Textual's space key."""
    return ["space" if character == " " else character for character in value]


async def _tab_to(pilot: Pilot[None], app: NotehubApp, widget_id: str) -> None:
    """Reach a visible control through normal keyboard focus order."""
    for _ in range(20):
        if getattr(app.focused, "id", None) == widget_id:
            return
        await pilot.press("tab")
    raise AssertionError(f"Tab focus did not reach #{widget_id}")


@pytest.mark.asyncio
async def test_keyboard_only_shell_opens_events_at_80_by_24() -> None:
    """A keyboard-only project-to-events path fits the minimum terminal size."""
    app = NotehubApp(options=TUIOptions(demo=True))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        assert (app.size.width, app.size.height) == (80, 24)
        assert app.query_one("#resize-notice").display is False
        assert app.focused is app.query_one("#project", Select)

        await _choose_demo_project(pilot, app)
        await pilot.press("2")
        await pilot.pause(0.1)

        assert app.view is ViewId.EVENTS
        assert app.query_one("#records", DataTable).row_count == 50
        assert all(button.region.right <= 80 for button in app.query("#nav Button"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("size", "breakpoint", "inspector_visible"),
    [
        ((80, 24), "compact", False),
        ((100, 30), "roomy", False),
        ((140, 42), "wide", True),
    ],
)
async def test_layout_focus_and_visible_controls_fit_each_acceptance_size(
    size: tuple[int, int], breakpoint: str, inspector_visible: bool
) -> None:
    """The shell fits supported sizes and keeps its key controls reachable."""
    app = NotehubApp(options=TUIOptions(demo=True))
    async with app.run_test(size=size) as pilot:
        await pilot.pause(0.1)
        await _choose_demo_project(pilot, app)
        await pilot.press("2")
        await pilot.pause(0.1)

        assert breakpoint in app.screen.classes
        assert app.view is ViewId.EVENTS
        assert app.query_one("#records", DataTable).row_count == 50
        assert app.query_one("#inspector").display is inspector_visible
        visible = app.query_one("#view-host", ContentSwitcher).visible_content
        assert visible is not None
        assert visible.id == "records-view"
        assert [child.id for child in app.query_one("#view-host").children if child.display] == [
            "records-view"
        ]

        shell_rows = [
            app.query_one(widget_id)
            for widget_id in (
                "#scope-bar",
                "#nav",
                "#status",
                "#tools",
                "#query-summary",
                "#view-host",
                "#paging",
                "Footer",
            )
        ]
        for widget in shell_rows:
            assert widget.region.x >= 0
            assert widget.region.y >= 0
            assert widget.region.right <= size[0]
            assert widget.region.bottom <= size[1]
        assert all(
            previous.region.bottom <= current.region.y
            for previous, current in zip(shell_rows, shell_rows[1:])
        )
        assert app.query_one("#view-host").region.height >= 5
        assert app.query_one("#nav").region.height == 1
        assert all(button.region.height == 1 for button in app.query("#nav Button"))

        toast_button = app.query_one("#toasts", Button)
        assert toast_button.display
        assert str(toast_button.label) == "Toasts: On"
        assert toast_button.region.right <= size[0]
        assert toast_button.region.bottom <= size[1]
        await _tab_to(pilot, app, "toasts")
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert app.toasts_enabled is False
        assert str(toast_button.label) == "Toasts: Off"

        await pilot.press("/")
        assert getattr(app.focused, "id", None) == "search"
        await pilot.press("escape")
        await pilot.pause(0.05)
        assert getattr(app.focused, "id", None) == "records"


@pytest.mark.asyncio
async def test_ctrl_p_opens_each_workspace_destination() -> None:
    """Every current workspace can be reached from Textual's command palette."""
    app = NotehubApp(options=TUIOptions(demo=True))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        await _choose_demo_project(pilot, app)

        for view in ViewId:
            await pilot.press("ctrl+p")
            await pilot.pause(0.05)
            assert isinstance(app.screen, CommandPalette)

            await pilot.press(*_text_keys(f"Go to {view.value}".lower()))
            await pilot.pause(0.1)
            await pilot.press("enter")
            await pilot.pause(0.1)

            assert app.view is view
            assert app.query_one(f"#nav-{view.value}", Button)
            if view is ViewId.EVENTS:
                assert app.query_one("#records", DataTable).row_count == 50


@pytest.mark.asyncio
async def test_search_shortcuts_and_resize_preserve_keyboard_focus_and_selection() -> None:
    """Shortcut letters edit search, and resize keeps the selected event active."""
    app = NotehubApp(options=TUIOptions(demo=True))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        await _choose_demo_project(pilot, app)
        await pilot.press("2")
        await pilot.pause(0.1)

        await pilot.press("/")
        search = app.query_one("#search", Input)
        assert app.focused is search
        await pilot.press(*_text_keys("fdrq123"))
        assert search.value == "fdrq123"
        assert app.view is ViewId.EVENTS
        assert app.is_running

        await pilot.press("escape")
        await pilot.pause(0.1)
        table = app.query_one("#records", DataTable)
        assert search.value == ""
        assert app.focused is table
        assert table.row_count == 50

        await pilot.press("down")
        await pilot.pause(0.05)
        selected = app.selected_record
        assert selected is not None
        selected_event = selected["event"]

        await pilot.resize_terminal(140, 42)
        await pilot.pause(0.1)
        assert app.query_one("#inspector").display is True
        assert app.focused is table
        selected = app.selected_record
        assert selected is not None
        assert selected["event"] == selected_event

        await pilot.resize_terminal(80, 24)
        await pilot.pause(0.1)
        assert app.query_one("#inspector").display is False
        assert app.focused is table
        selected = app.selected_record
        assert selected is not None
        assert selected["event"] == selected_event
