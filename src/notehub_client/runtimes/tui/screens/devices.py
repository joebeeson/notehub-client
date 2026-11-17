"""Reusable project-device list and device-detail views."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DataTable, Label, TabbedContent, TabPane

from ..state import PageResult
from ..widgets.records import display_field, populate_record_table, record_table


class DeviceListView(Vertical):
    """A page of project devices, keyed by their source UID."""

    DEFAULT_CSS = """
    DeviceListView { height: 1fr; }
    .resource-heading { height: 1; color: $accent; text-style: bold; }
    .resource-table { height: 1fr; }
    .resource-empty { height: auto; color: $text-muted; padding: 1; }
    .resource-page-hint { height: 1; color: $text-muted; }
    """

    class Selected(Message):
        """A device row was activated by keyboard or mouse."""

        def __init__(self, device: dict[str, Any]) -> None:
            super().__init__()
            self.device = device

    def __init__(self, page: PageResult, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.page = page

    def set_result(self, page: PageResult) -> None:
        """Replace the current page while retaining the owning app's state."""
        if page == self.page:
            return
        self.page = page
        self.refresh(recompose=True)

    def compose(self) -> ComposeResult:
        """Render this page without triggering another device read."""
        yield from record_table(
            "Devices",
            self.page,
            ("Device", "Serial number", "Fleets", "Last reported activity"),
            ("uid", "serial_number", "fleet_uids", "last_activity"),
            empty="No devices were returned for this project.",
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Post the source device selected by stable table key."""
        key = str(event.row_key.value)
        device = next(
            (
                row
                for row, row_key in zip(self.page.rows, self.page.row_keys, strict=True)
                if row_key == key
            ),
            None,
        )
        if device is not None and device.get("uid"):
            self.post_message(self.Selected(dict(device)))


class DeviceDetailView(Vertical):
    """A device report with lazily requested, independent detail sections."""

    class SectionSelected(Message):
        """A detail section became active; the app may issue its read."""

        def __init__(self, device_uid: str, section: str) -> None:
            super().__init__()
            self.device_uid, self.section = device_uid, section

    def __init__(
        self,
        device: dict[str, Any],
        *,
        latest: PageResult | None = None,
        sessions: PageResult | None = None,
        environment: PageResult | None = None,
        events: PageResult | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.device = dict(device)
        self.latest, self.sessions = latest, sessions
        self.environment, self.events = environment, events

    def set_section_result(self, section: str, page: PageResult) -> None:
        """Install a lazily fetched detail result without owning the request."""
        if section not in {"latest", "sessions", "environment", "events"}:
            raise ValueError("Unknown device detail section")
        setattr(self, section, page)
        if self.is_mounted:
            self._render_section(section)

    def set_device(self, device: dict[str, Any]) -> None:
        """Replace the selected device, clearing section rows when its UID changes."""
        if self.device == device:
            return
        previous_uid = self.device_uid
        self.device = dict(device)
        if self.device_uid != previous_uid:
            self.latest = self.sessions = self.environment = self.events = None
        if self.is_mounted:
            self.query_one("#device-detail-heading", Label).update(
                f"Device · {display_field(self.device, 'uid')}"
            )
            self.query_one("#device-detail-summary", Label).update(
                f"Serial {display_field(self.device, 'serial_number')} · Last reported activity {display_field(self.device, 'last_activity')}"
            )
            for section in ("latest", "sessions", "environment", "events"):
                self._render_section(section)

    @property
    def device_uid(self) -> str:
        """Return the real UID, or empty when the source omitted it."""
        value = self.device.get("uid")
        return value if isinstance(value, str) else ""

    def compose(self) -> ComposeResult:
        """Render cached device sections and their lazy-load tabs."""
        yield Label(
            f"Device · {display_field(self.device, 'uid')}",
            id="device-detail-heading",
            classes="resource-heading",
        )
        yield Label(
            f"Serial {display_field(self.device, 'serial_number')} · Last reported activity {display_field(self.device, 'last_activity')}",
            id="device-detail-summary",
        )
        yield Label(
            "Activity is reported by Notehub; it does not establish current connectivity.",
            classes="resource-page-hint",
        )
        with TabbedContent(initial="device-overview", id="device-sections"):
            with TabPane("Overview", id="device-overview"):
                yield Label(
                    f"Fleets {display_field(self.device, 'fleet_uids')} · Voltage {display_field(self.device, 'voltage')} · Temperature {display_field(self.device, 'temperature')}"
                )
            with TabPane("Latest", id="device-latest"):
                yield Label("Latest reported events", classes="resource-heading")
                yield self._make_table("device-latest-table", ("File", "Event UID", "Captured"))
                yield Label(
                    "Select this tab to load records.",
                    id="device-latest-empty",
                    classes="resource-empty",
                )
                yield Label("", id="device-latest-hint", classes="resource-page-hint")
            with TabPane("Sessions", id="device-sessions"):
                yield Label("Reported sessions", classes="resource-heading")
                yield self._make_table(
                    "device-sessions-table", ("Session UID", "Started", "Duration")
                )
                yield Label(
                    "Select this tab to load records.",
                    id="device-sessions-empty",
                    classes="resource-empty",
                )
                yield Label("", id="device-sessions-hint", classes="resource-page-hint")
            with TabPane("Environment keys", id="device-environment"):
                yield Label("Environment values are not displayed.")
                yield Label("Variable names", classes="resource-heading")
                yield self._make_table("device-environment-table", ("Variable", "Scope"))
                yield Label(
                    "Select this tab to load environment variable names.",
                    id="device-environment-empty",
                    classes="resource-empty",
                )
                yield Label("", id="device-environment-hint", classes="resource-page-hint")
            with TabPane("Events", id="device-events"):
                yield Label("Related events", classes="resource-heading")
                yield self._make_table("device-events-table", ("File", "Event UID", "Captured"))
                yield Label(
                    "Select this tab to load records.",
                    id="device-events-empty",
                    classes="resource-empty",
                )
                yield Label("", id="device-events-hint", classes="resource-page-hint")

    def on_mount(self) -> None:
        """Render any cached pages supplied before this view was mounted."""
        for section in ("latest", "sessions", "environment", "events"):
            self._render_section(section)

    @staticmethod
    def _make_table(table_id: str, columns: tuple[str, ...]) -> DataTable:
        table = DataTable(
            cursor_type="row", zebra_stripes=True, id=table_id, classes="resource-table"
        )
        table.add_columns(*columns)
        return table

    def _render_section(self, section: str) -> None:
        page = getattr(self, section)
        fields = {
            "latest": ("file", "event", "when"),
            "sessions": ("uid", "when", "duration"),
            "environment": ("name", "scope"),
            "events": ("file", "event", "when"),
        }[section]
        table = self.query_one(f"#device-{section}-table", DataTable)
        empty = self.query_one(f"#device-{section}-empty", Label)
        if page is None:
            table.display = False
            empty.display = True
            empty.update(
                "Select this tab to load environment variable names."
                if section == "environment"
                else "Select this tab to load records."
            )
            self.query_one(f"#device-{section}-hint", Label).update("")
            return
        populate_record_table(table, page, fields, empty)
        empty.update(
            "No environment variable names were returned."
            if section == "environment"
            else "No records were returned."
        )
        hint = self.query_one(f"#device-{section}-hint", Label)
        hint_text = (
            "More records are available on the next page."
            if page.has_more is True
            else "Returned records; total availability was not reported."
            if page.has_more is None
            else ""
        )
        hint.update(hint_text)
        hint.display = bool(hint_text)
        if not table.row_count:
            table.display = False

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Notify the app to lazily load a not-yet-cached detail section."""
        section = event.pane.id.removeprefix("device-") if event.pane.id else "overview"
        if section != "overview" and self.device_uid:
            self.post_message(self.SectionSelected(self.device_uid, section))
