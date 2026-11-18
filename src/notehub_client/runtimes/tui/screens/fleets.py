"""Reusable project-fleet list and fleet-detail views."""

from __future__ import annotations

from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, DataTable, Label, TabbedContent, TabPane

from ..state import PageResult
from ..widgets.records import display_field, populate_record_table, record_table


class FleetListView(Vertical):
    """A collection of project fleets keyed by source UID."""

    DEFAULT_CSS = """
    FleetListView { height: 1fr; }
    .resource-heading { height: 1; color: $accent; text-style: bold; }
    .resource-table { height: 1fr; }
    .resource-empty { height: auto; color: $text-muted; padding: 1; }
    .resource-page-hint { height: 1; color: $text-muted; }
    """

    class Selected(Message):
        """A fleet row was activated."""

        def __init__(self, fleet: dict[str, Any]) -> None:
            super().__init__()
            self.fleet = fleet

    def __init__(self, page: PageResult, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.page = page

    def set_result(self, page: PageResult) -> None:
        """Replace the bounded fleet result in the existing workspace."""
        if page == self.page:
            return
        self.page = page
        self.refresh(recompose=True)

    def compose(self) -> ComposeResult:
        """Render the returned fleet records and honest continuation hint."""
        yield from record_table(
            "Fleets",
            self.page,
            ("Fleet", "UID", "Description"),
            ("label", "uid", "description"),
            empty="No fleets were returned for this project.",
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Send the selected source fleet to the owning app."""
        key = str(event.row_key.value)
        fleet = next(
            (
                row
                for row, row_key in zip(self.page.rows, self.page.row_keys, strict=True)
                if row_key == key
            ),
            None,
        )
        if fleet is not None and fleet.get("uid"):
            self.post_message(self.Selected(dict(fleet)))


class FleetDetailView(Vertical):
    """Fleet facts with bounded member-device and event sections."""

    DEFAULT_CSS = """
    #fleet-devices-pagination, #fleet-events-pagination { height: auto; align-vertical: middle; }
    #fleet-devices-page { width: auto; margin: 0 1; }
    """

    class DevicePageRequested(Message):
        """Move one page from the currently displayed member devices."""

        def __init__(self, fleet_uid: str, *, forward: bool) -> None:
            super().__init__()
            self.fleet_uid = fleet_uid
            self.forward = forward

    class SectionSelected(Message):
        """A section became active; the owner can lazily request it."""

        def __init__(self, fleet_uid: str, section: str) -> None:
            super().__init__()
            self.fleet_uid, self.section = fleet_uid, section

    class EventPageRequested(Message):
        """Navigate the app-owned event cursor history."""

        def __init__(self, fleet_uid: str, *, forward: bool) -> None:
            super().__init__()
            self.fleet_uid = fleet_uid
            self.forward = forward

    def set_event_navigation(self, *, previous: bool, following: bool) -> None:
        """Reflect available retained pages and upstream continuation."""
        self.query_one("#fleet-events-previous", Button).disabled = not previous
        self.query_one("#fleet-events-next", Button).disabled = not following

    def __init__(
        self,
        fleet: dict[str, Any],
        *,
        devices: PageResult | None = None,
        events: PageResult | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.fleet = dict(fleet)
        self.devices, self.events = devices, events

    def set_section_result(self, section: str, page: PageResult | None) -> None:
        """Install a lazily fetched section without owning its request."""
        if section not in {"devices", "events"}:
            raise ValueError("Unknown fleet detail section")
        setattr(self, section, page)
        if self.is_mounted:
            self._render_section(section)

    def set_fleet(self, fleet: dict[str, Any]) -> None:
        """Replace the selected fleet, clearing rows when its UID changes."""
        if self.fleet == fleet:
            return
        previous_uid = self.fleet_uid
        self.fleet = dict(fleet)
        if self.fleet_uid != previous_uid:
            self.devices = self.events = None
        if self.is_mounted:
            self.query_one("#fleet-detail-heading", Label).update(
                f"Fleet · {display_field(self.fleet, 'label')}"
            )
            self.query_one("#fleet-detail-summary", Label).update(
                f"UID {display_field(self.fleet, 'uid')} · {display_field(self.fleet, 'description')}"
            )
            self._render_section("devices")
            self._render_section("events")

    @property
    def fleet_uid(self) -> str:
        """Return the source UID when present."""
        value = self.fleet.get("uid")
        return value if isinstance(value, str) else ""

    def compose(self) -> ComposeResult:
        """Render cached fleet facts and bounded related collections."""
        yield Label(
            f"Fleet · {display_field(self.fleet, 'label')}",
            id="fleet-detail-heading",
            classes="resource-heading",
        )
        yield Label(
            f"UID {display_field(self.fleet, 'uid')} · {display_field(self.fleet, 'description')}",
            id="fleet-detail-summary",
        )
        with TabbedContent(initial="fleet-overview", id="fleet-sections"):
            with TabPane("Overview", id="fleet-overview"):
                yield Label("Fleet details reported by Notehub.")
            with TabPane("Devices", id="fleet-devices"):
                yield Label("Member devices", classes="resource-heading")
                yield self._make_table(
                    "fleet-devices-table",
                    ("Device UID", "Serial number", "Last reported activity"),
                )
                yield Label(
                    "Select this tab to load records.",
                    id="fleet-devices-empty",
                    classes="resource-empty",
                )
                yield Label("", id="fleet-devices-hint", classes="resource-page-hint")
                with Horizontal(id="fleet-devices-pagination"):
                    yield Button("Previous", id="fleet-devices-previous", disabled=True)
                    yield Label("", id="fleet-devices-page")
                    yield Button("Next", id="fleet-devices-next", disabled=True)
            with TabPane("Events", id="fleet-events"):
                yield Label("Fleet events", classes="resource-heading")
                yield self._make_table(
                    "fleet-events-table", ("File", "Event UID", "Device", "Captured")
                )
                yield Label(
                    "Select this tab to load records.",
                    id="fleet-events-empty",
                    classes="resource-empty",
                )
                yield Label("", id="fleet-events-hint", classes="resource-page-hint")
                with Horizontal(id="fleet-events-pagination"):
                    yield Button("Previous", id="fleet-events-previous", disabled=True)
                    yield Button("Next", id="fleet-events-next", disabled=True)

    @staticmethod
    def _make_table(table_id: str, columns: tuple[str, ...]) -> DataTable:
        table = DataTable(
            cursor_type="row", zebra_stripes=True, id=table_id, classes="resource-table"
        )
        table.add_columns(*columns)
        return table

    def on_mount(self) -> None:
        """Render any cached pages supplied before this view was mounted."""
        self._render_section("devices")
        self._render_section("events")

    def _render_section(self, section: str) -> None:
        page = getattr(self, section)
        if section == "devices":
            number = self.devices.page_num if self.devices is not None else None
            self.query_one("#fleet-devices-pagination", Horizontal).display = number is not None
            self.query_one("#fleet-devices-page", Label).update(f"Page {number}" if number else "")
            self.query_one("#fleet-devices-previous", Button).disabled = (
                number is None or number <= 1
            )
            self.query_one("#fleet-devices-next", Button).disabled = (
                number is None or self.devices is None or self.devices.has_more is not True
            )
        fields = (
            ("uid", "serial_number", "last_activity")
            if section == "devices"
            else ("file", "event", "device", "when")
        )
        table = self.query_one(f"#fleet-{section}-table", DataTable)
        empty = self.query_one(f"#fleet-{section}-empty", Label)
        if page is None:
            table.display = False
            empty.display = True
            empty.update("Select this tab to load records.")
            self.query_one(f"#fleet-{section}-hint", Label).update("")
            return
        populate_record_table(table, page, fields, empty)
        empty.update("No records were returned.")
        hint = self.query_one(f"#fleet-{section}-hint", Label)
        hint_text = (
            "More records are available on the next page."
            if page.has_more is True and (section != "devices" or page.page_num is None)
            else "Returned records; total availability was not reported."
            if page.has_more is None
            else ""
        )
        hint.update(hint_text)
        hint.display = bool(hint_text)
        if not table.row_count:
            table.display = False

    @on(Button.Pressed, "#fleet-devices-previous, #fleet-devices-next")
    def request_device_page(self, event: Button.Pressed) -> None:
        """Request another member page through the owning app."""
        event.stop()
        self.post_message(
            self.DevicePageRequested(
                self.fleet_uid, forward=event.button.id == "fleet-devices-next"
            )
        )

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Ask the owning app to load an uncached fleet section."""
        section = event.pane.id.removeprefix("fleet-") if event.pane.id else "overview"
        if section != "overview" and self.fleet_uid:
            self.post_message(self.SectionSelected(self.fleet_uid, section))

    @on(Button.Pressed, "#fleet-events-previous, #fleet-events-next")
    def request_event_page(self, event: Button.Pressed) -> None:
        """Request cursor navigation without exposing opaque tokens."""
        event.stop()
        self.post_message(
            self.EventPageRequested(self.fleet_uid, forward=event.button.id == "fleet-events-next")
        )
