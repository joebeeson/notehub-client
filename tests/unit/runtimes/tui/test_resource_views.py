from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Label, TabbedContent

from notehub_client.runtimes.tui.screens.devices import DeviceDetailView, DeviceListView
from notehub_client.runtimes.tui.screens.fleets import FleetDetailView, FleetListView
from notehub_client.runtimes.tui.state import PageResult


class DeviceListApp(App[None]):
    def __init__(self, page: PageResult) -> None:
        super().__init__()
        self.page = page
        self.selected: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        yield DeviceListView(self.page, id="devices")

    def on_device_list_view_selected(self, event: DeviceListView.Selected) -> None:
        self.selected = event.device


class FleetListApp(App[None]):
    def __init__(self, page: PageResult) -> None:
        super().__init__()
        self.page = page
        self.selected: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        yield FleetListView(self.page, id="fleets")

    def on_fleet_list_view_selected(self, event: FleetListView.Selected) -> None:
        self.selected = event.fleet


class DeviceDetailApp(App[None]):
    def __init__(self, device: dict[str, Any]) -> None:
        super().__init__()
        self.device = device
        self.section: tuple[str, str] | None = None

    def compose(self) -> ComposeResult:
        yield DeviceDetailView(self.device, id="device-detail")

    def on_device_detail_view_section_selected(
        self, event: DeviceDetailView.SectionSelected
    ) -> None:
        self.section = event.device_uid, event.section


@pytest.mark.asyncio
async def test_device_selection_uses_source_uid_and_reports_activity() -> None:
    page = PageResult(
        rows=({"uid": "dev:west", "serial_number": "West", "last_activity": "yesterday"},),
        row_keys=("dev:west",),
        has_more=True,
        page_num=1,
    )
    app = DeviceListApp(page)
    async with app.run_test() as pilot:
        table = app.query_one(DataTable)
        table.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert app.selected == page.rows[0]
        assert table.row_count == 1


@pytest.mark.asyncio
async def test_empty_devices_have_explanation() -> None:
    app = DeviceListApp(PageResult())
    async with app.run_test() as pilot:
        await pilot.pause()
        label = app.query_one(".resource-empty", Label)
        assert "No devices were returned" in str(label.content)


@pytest.mark.asyncio
async def test_environment_values_are_never_rendered_and_tab_requests_lazy_read() -> None:
    env = PageResult(
        rows=({"name": "API_TOKEN", "scope": "device", "value": "secret-value"},),
        row_keys=("API_TOKEN",),
    )
    app = DeviceDetailApp({"uid": "dev:west", "last_activity": "yesterday"})
    async with app.run_test() as pilot:
        view = app.query_one(DeviceDetailView)
        view.set_section_result("environment", env)
        await pilot.pause()
        sections = view.query_one(TabbedContent)
        sections.active = "device-environment"
        await pilot.pause()
        assert app.section == ("dev:west", "environment")
        rendered = app.export_screenshot()
        assert "secret-value" not in rendered.casefold()
        assert "API_TOKEN" in rendered
        assert "does not establish current connectivity" in str(view.children[2].content)


@pytest.mark.asyncio
async def test_fleet_list_and_lazy_sections() -> None:
    page = PageResult(
        rows=({"uid": "fleet:west", "label": "West sensors"},),
        row_keys=("fleet:west",),
        has_more=None,
    )
    app = FleetListApp(page)
    async with app.run_test() as pilot:
        table = app.query_one(DataTable)
        table.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert app.selected == page.rows[0]
        detail = FleetDetailView(page.rows[0])
        assert detail.fleet_uid == "fleet:west"


@pytest.mark.asyncio
async def test_detail_rejects_unknown_lazy_section() -> None:
    view = DeviceDetailView({"uid": "dev:west"})
    with pytest.raises(ValueError, match="Unknown device detail section"):
        view.set_section_result("environment-values", PageResult())
