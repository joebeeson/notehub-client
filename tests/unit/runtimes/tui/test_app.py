"""Textual Pilot coverage for the terminal workspace's user-visible shell."""

from __future__ import annotations

import asyncio

import pytest
from rich.text import Text
from textual.content import Content
from textual.widgets import (
    Button,
    ContentSwitcher,
    DataTable,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
)

from notehub_client.errors import NotehubAPIError, NotehubRateLimitError
from notehub_client.filters import Query
from notehub_client.runtimes.tui.app import NotehubApp, TextDialog
from notehub_client.runtimes.tui.demo import DEMO_PROJECT_UID, DemoReadService
from notehub_client.runtimes.tui.screens.devices import DeviceDetailView, DeviceListView
from notehub_client.runtimes.tui.screens.fleets import FleetDetailView, FleetListView
from notehub_client.runtimes.tui.screens.operations import OperationsPanel
from notehub_client.runtimes.tui.screens.overview import OverviewPanel
from notehub_client.runtimes.tui.state import PageResult, TUIOptions, ViewId


@pytest.mark.asyncio
async def test_demo_launch_is_credential_free_and_reads_only_after_project_choice() -> None:
    """The demo path remains local, labelled, and scoped by explicit project choice."""
    app = NotehubApp(options=TUIOptions(demo=True))
    async with app.run_test(size=(140, 42)) as pilot:
        await pilot.pause()
        brand = app.query_one("#brand", Static).render()
        assert isinstance(brand, (Text, Content))
        assert brand.plain == "NOTEHUB / DEMO"
        assert app.query_one("#login").display is False
        assert app.project_uid is None
        assert isinstance(app.service, DemoReadService)
        assert app.service.reads == ["projects"]

        project_picker = app.query_one("#project", Select)
        project_picker.value = DEMO_PROJECT_UID
        await pilot.pause()

        assert app.project_uid == DEMO_PROJECT_UID
        assert app.view is ViewId.OVERVIEW
        assert set(app.service.reads) >= {"projects", "events", "project"}
        assert "routes" not in app.service.reads
        assert len(app.query_one(OverviewPanel).events) == 50


@pytest.mark.asyncio
async def test_navigation_and_current_page_search_use_loaded_demo_data() -> None:
    """Primary destinations work in the terminal and page search does not fetch."""
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(140, 42)) as pilot:
        await pilot.pause(0.1)
        assert app.query_one(OverviewPanel).events
        service = app.service
        assert isinstance(service, DemoReadService)
        reads_before = tuple(service.reads)

        await pilot.click("#nav-events")
        await pilot.pause(0.1)
        assert app.view is ViewId.EVENTS
        assert app.operation == "events"
        assert app.query_one("#records", DataTable).row_count == 50

        await pilot.click("#search")
        await pilot.press("ctrl+a")
        await pilot.press(*list("sensor:demo-temperature"))
        await pilot.pause()
        assert app.query_one("#records", DataTable).row_count <= 50
        assert tuple(service.reads) == reads_before + ("events",)


@pytest.mark.asyncio
async def test_event_device_events_back_restores_event_selection() -> None:
    """Related device events are scoped and Back restores the source row."""
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        app.action_navigate("events")
        await pilot.pause(0.1)
        source_table = app.query_one("#records", DataTable)
        source_key = str(
            source_table.coordinate_to_cell_key(source_table.cursor_coordinate).row_key.value
        )
        source_table.focus()
        await pilot.press("d")
        await pilot.pause(0.1)
        device_uid = app.uid
        assert app.view is ViewId.DEVICES
        assert app.operation == "device"
        assert device_uid

        app.query_one(DeviceDetailView).query_one(TabbedContent).active = "device-events"
        await pilot.pause(0.1)
        assert app.operation == "events"
        detail_events = app.query_one(DeviceDetailView).events
        assert detail_events is not None and detail_events.rows
        assert {row.get("device") for row in detail_events.rows} == {device_uid}

        await pilot.press("escape")
        await pilot.pause(0.1)
        assert app.view is ViewId.EVENTS
        assert app.operation == "events"
        assert app.current_state.selected_key == source_key


@pytest.mark.asyncio
async def test_device_detail_tabs_load_through_app_and_show_environment_names_only() -> None:
    """Device sections use app-owned reads and never render environment values."""
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(140, 42)) as pilot:
        await pilot.pause(0.1)
        delegate = app.service
        assert isinstance(delegate, DemoReadService)

        class RawEnvironmentService:
            def __init__(self) -> None:
                self.calls: list[str] = []

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
                self.calls.append(operation)
                if operation == "environment":
                    return PageResult(
                        rows=(
                            {"name": "API_TOKEN", "scope": "device", "value": "secret-sentinel"},
                            {"name": "REPORT_INTERVAL", "scope": "device", "value": "60"},
                        ),
                        row_keys=("API_TOKEN", "REPORT_INTERVAL"),
                    )
                return await delegate.read(
                    operation,
                    project_uid=project_uid,
                    uid=uid,
                    query=query,
                    cursor=cursor,
                    page_num=page_num,
                )

        service = RawEnvironmentService()
        app.service = service
        await pilot.click("#nav-devices")
        await pilot.pause(0.1)
        device_list = app.query_one(DeviceListView)
        table = device_list.query_one(DataTable)
        assert table.row_count > 1
        table.move_cursor(row=1)
        await pilot.pause()
        selected_key = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        table.focus()
        await pilot.press("enter")
        await pilot.pause(0.1)

        detail = app.query_one(DeviceDetailView)
        device_uid = detail.device_uid
        assert app.query_one("#view-host", ContentSwitcher).current == "device-detail-view"
        assert device_uid

        tabs = detail.query_one(TabbedContent)
        tabs.active = "device-latest"
        await pilot.pause(0.1)
        assert detail.latest is not None and detail.latest.rows
        assert "latest" in service.calls

        tabs.active = "device-environment"
        await pilot.pause(0.1)
        assert detail.environment is not None
        assert [row["name"] for row in detail.environment.rows] == [
            "API_TOKEN",
            "REPORT_INTERVAL",
        ]
        rendered = app.export_screenshot().casefold()
        assert "api_token" in rendered
        assert "report_interval" in rendered
        assert "secret-sentinel" not in rendered
        assert tabs.active == "device-environment"

        await pilot.press("escape")
        await pilot.pause(0.1)
        assert app.view is ViewId.DEVICES
        assert app.uid is None
        assert app.query_one("#view-host", ContentSwitcher).current == "devices-view"
        restored_table = app.query_one(DeviceListView).query_one(DataTable)
        restored_key = str(
            restored_table.coordinate_to_cell_key(restored_table.cursor_coordinate).row_key.value
        )
        assert restored_key == selected_key


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["device", "fleet"])
async def test_detail_pages_preserve_scope_when_a_read_finishes_after_navigation(kind: str) -> None:
    section = "sessions" if kind == "device" else "devices"
    operation_name = "sessions" if kind == "device" else "fleet_devices"
    list_type = DeviceListView if kind == "device" else FleetListView
    detail_type = DeviceDetailView if kind == "device" else FleetDetailView

    class SessionsService(DemoReadService):
        def __init__(self) -> None:
            super().__init__()
            self.session_requests: list[tuple[str, int]] = []
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
                    rows=({"uid": "fleet:first"}, {"uid": "fleet:second"}),
                    row_keys=("fleet:first", "fleet:second"),
                    has_more=False,
                )
            if operation != operation_name:
                return await super().read(
                    operation,
                    project_uid=project_uid,
                    uid=uid,
                    query=query,
                    cursor=cursor,
                    page_num=page_num,
                )
            assert uid is not None
            self.session_requests.append((uid, page_num))
            if page_num == 3:
                self.pending.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.returned_after_cancel = True
            key = f"{uid}-page-{page_num}"
            return PageResult(
                rows=({"session" if kind == "device" else "uid": key},),
                row_keys=(key,),
                page_num=page_num,
                has_more=uid == self.session_requests[0][0] and page_num < 3,
            )

    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        service = SessionsService()
        app.service = service
        await pilot.click(f"#nav-{kind}s")
        await pilot.pause(0.1)
        detail = app.query_one(detail_type)
        tabs = detail.query_one(TabbedContent)

        async def open_sessions(row: int) -> str:
            table = app.query_one(list_type).query_one(DataTable)
            table.move_cursor(row=row)
            table.focus()
            await pilot.press("enter")
            await pilot.pause()
            tabs.active = f"{kind}-{section}"
            await pilot.pause()
            return getattr(detail, f"{kind}_uid")

        first = await open_sessions(0)
        previous = detail.query_one(f"#{kind}-{section}-previous", Button)
        following = detail.query_one(f"#{kind}-{section}-next", Button)
        number = detail.query_one(f"#{kind}-{section}-page", Label)
        assert previous.disabled and not following.disabled
        await pilot.click(following)
        await pilot.pause()
        assert str(number.content) == "Page 2"
        assert not previous.disabled
        app.action_refresh()
        await pilot.pause()
        assert str(number.content) == "Page 2"
        await pilot.click(previous)
        await pilot.pause()
        assert str(number.content) == "Page 1"
        await pilot.click(following)
        await pilot.pause()
        assert str(number.content) == "Page 2"
        following.press()
        await asyncio.wait_for(service.pending.wait(), timeout=2)

        await pilot.press("escape")
        await pilot.pause()
        second = await open_sessions(1)
        assert first != second
        assert service.returned_after_cancel
        assert str(number.content) == "Page 1"
        assert previous.disabled and following.disabled
        assert getattr(detail, section) is not None and getattr(detail, section).row_keys == (
            f"{second}-page-1",
        )

        await pilot.press("escape")
        await pilot.pause()
        assert await open_sessions(0) == first
        assert str(number.content) == "Page 2"
        assert getattr(detail, section) is not None and getattr(detail, section).row_keys == (
            f"{first}-page-2",
        )
        assert service.session_requests == [
            (first, 1),
            (first, 2),
            (first, 2),
            (first, 1),
            (first, 2),
            (first, 3),
            (second, 1),
        ]


@pytest.mark.asyncio
async def test_fleet_detail_sections_load_and_back_restores_fleet_selection() -> None:
    """Fleet member/event tabs load lazily and Escape returns to the chosen fleet."""
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(140, 42)) as pilot:
        await pilot.pause(0.1)
        await pilot.click("#nav-fleets")
        await pilot.pause(0.1)
        fleet_list = app.query_one(FleetListView)
        table = fleet_list.query_one(DataTable)
        selected_key = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        table.focus()
        await pilot.press("enter")
        await pilot.pause(0.1)

        detail = app.query_one(FleetDetailView)
        assert detail.fleet_uid
        assert app.query_one("#view-host", ContentSwitcher).current == "fleet-detail-view"
        tabs = detail.query_one(TabbedContent)
        tabs.active = "fleet-devices"
        await pilot.pause(0.1)
        assert detail.devices is not None and detail.devices.rows
        tabs.active = "fleet-events"
        await pilot.pause(0.1)
        assert detail.events is not None and detail.events.rows
        service = app.service
        assert isinstance(service, DemoReadService)
        assert service.reads.count("fleet_devices") == 1
        assert service.reads.count("fleet_events") == 1

        tabs.active = "fleet-devices"
        await pilot.pause()
        assert app.operation == "devices"
        assert service.reads.count("fleet_devices") == 1
        app.action_refresh()
        await pilot.pause()
        assert service.reads.count("fleet_devices") == 2
        assert service.reads.count("fleet_events") == 1

        await pilot.press("escape")
        await pilot.pause(0.1)
        assert app.view is ViewId.FLEETS
        assert app.uid is None
        assert app.query_one("#view-host", ContentSwitcher).current == "fleets-view"
        restored_table = app.query_one(FleetListView).query_one(DataTable)
        restored_key = str(
            restored_table.coordinate_to_cell_key(restored_table.cursor_coordinate).row_key.value
        )
        assert restored_key == selected_key


@pytest.mark.asyncio
async def test_navigation_shortcuts_do_not_consume_text_input() -> None:
    """The letter shortcuts remain ordinary text in an editor."""
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        search = app.query_one("#search", Input)
        search.focus()
        await pilot.press("f", "d", "r", "q")
        assert search.value == "fdrq"
        assert app.view is ViewId.OVERVIEW


@pytest.mark.asyncio
async def test_old_generation_result_is_discarded_after_scope_change() -> None:
    """A response started under a stale generation cannot repaint the active scope."""
    from asyncio import Event

    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    entered, release = Event(), Event()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        original = app.service
        assert original is not None

        class DelayedService:
            reads: list[str] = []

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
                if operation == "events" and not entered.is_set():
                    entered.set()
                    await release.wait()
                self.reads.append(operation)
                return await original.read(
                    operation,
                    project_uid=project_uid,
                    uid=uid,
                    query=query,
                    cursor=cursor,
                    page_num=page_num,
                )

        app.service = DelayedService()
        app.project_uid = DEMO_PROJECT_UID
        app.action_navigate("events")
        await entered.wait()
        generation = app.generation
        app.generation += 1
        app.project_uid = "app:demo-empty"
        release.set()
        await pilot.pause(0.1)
        assert app.generation == generation + 1
        assert app.project_uid == "app:demo-empty"
        assert app.result.rows == ()


@pytest.mark.asyncio
async def test_signal_and_inbox_controls_are_present_and_session_local() -> None:
    """The shell exposes the optional signal and notification affordances."""
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(140, 42)) as pilot:
        await pilot.pause(0.1)
        assert str(app.query_one("#signals", Button).label) == "Signals"
        assert str(app.query_one("#inbox", Button).label) == "Inbox"
        service = app.service
        assert isinstance(service, DemoReadService)
        before = tuple(service.reads)
        await pilot.click("#signals")
        await pilot.pause()
        assert app.query_one("#signals-strip").display is True
        assert tuple(service.reads) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (NotehubRateLimitError(429, "throttled", retry_after="30"), "Rate limited"),
        (NotehubAPIError(404, "missing"), "Resource not found"),
    ],
)
async def test_recovery_feedback_distinguishes_throttle_and_missing_scope(
    error: Exception, expected: str
) -> None:
    """Report actionable API recovery while retaining the last-good event page."""
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        app.action_navigate("events")
        await pilot.pause(0.1)
        previous_rows = app.result.rows
        assert previous_rows
        assert isinstance(app.service, DemoReadService)
        app.service.fail_next("events", error)
        app.action_refresh()
        await pilot.pause(0.1)

        status = app.query_one("#status", Static).render()
        assert isinstance(status, (Text, Content))
        assert expected in status.plain
        assert app.result.rows == previous_rows


@pytest.mark.asyncio
async def test_operations_reads_are_lazy_and_use_one_section_selector() -> None:
    """Open Operations before reading; its panel owns section selection and refresh."""
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        assert isinstance(app.service, DemoReadService)
        assert "routes" not in app.service.reads

        await pilot.click("#nav-operations")
        await pilot.pause(0.1)
        assert app.service.reads.count("routes") == 1
        assert app.query_one("#sections").display is False
        assert app.query_one("#operations-section").display is True

        app.query_one(OperationsPanel).query_one("#operations-section", Select).value = "jobs"
        await pilot.pause(0.1)
        assert app.service.reads.count("jobs") == 1
        assert "jobs" not in app.service.reads[:-1]


@pytest.mark.asyncio
async def test_below_minimum_size_offers_help_and_resize_controls() -> None:
    """A too-small terminal presents the direct Help and Quit actions."""
    app = NotehubApp(options=TUIOptions(demo=True))
    async with app.run_test(size=(78, 23)) as pilot:
        await pilot.pause()
        assert app.query_one("#resize-notice").display is True

        await pilot.click("#resize-help")
        await pilot.pause()
        assert isinstance(app.screen, TextDialog)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert (app.size.width, app.size.height) == (80, 24)
        assert app.query_one("#resize-notice").display is False
        assert app.query_one(OverviewPanel).region.height > 0
        assert all(button.region.right <= 80 for button in app.query("#nav Button"))

        await pilot.resize_terminal(140, 42)
        await pilot.pause()
        assert app.query_one("#inspector").display is True
