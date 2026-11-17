"""Project overview assembled from a small, partial-success read set."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Label, Static

from ..presentation import record_label, safe_text

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..service import ReadService


class OverviewPanel(Vertical):
    """Show project identity and one bounded page of recent events."""

    DEFAULT_CSS = """
    OverviewPanel { height: 1fr; padding: 1; }
    OverviewPanel #overview-title { height: auto; text-style: bold; }
    OverviewPanel #overview-status { height: 1; color: $text-muted; }
    OverviewPanel #overview-events { height: 1fr; }
    OverviewPanel .overview-actions { height: 3; }
    """

    def __init__(
        self,
        service: ReadService,
        project_uid: str | None = None,
        on_open: Callable[[str, dict[str, Any]], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.service = service
        self.project_uid = project_uid
        self.on_open = on_open
        self._generation = 0
        self.project: dict[str, Any] = {}
        self.events: tuple[dict[str, Any], ...] = ()

    def compose(self) -> ComposeResult:
        """Compose identity, navigation shortcuts and a bounded event table."""
        yield Label("Project overview", id="overview-title")
        yield Static("Choose a project to load its overview.", id="overview-status")
        with Horizontal(classes="overview-actions"):
            yield Button("Events", id="overview-open-events")
            yield Button("Devices", id="overview-open-devices")
            yield Button("Fleets", id="overview-open-fleets")
            yield Button("Operations", id="overview-open-operations")
        yield DataTable(id="overview-events", cursor_type="row")

    def render(self) -> Text:
        """Render a blank container background behind composed children."""
        return Text(" ")

    def on_mount(self) -> None:
        """Configure columns and load data only after attachment."""
        table = self.query_one("#overview-events", DataTable)
        table.add_columns("Captured", "File", "Device", "Event")
        if self.project_uid:
            self.refresh_data()

    def set_scope(self, project_uid: str | None) -> None:
        """Change project scope and invalidate any response from the old scope."""
        if project_uid == self.project_uid:
            return
        self.project_uid = project_uid
        self.project = {}
        self.events = ()
        self._generation += 1
        if self.is_mounted:
            self.query_one("#overview-events", DataTable).clear()
            self.refresh_data()

    def refresh_data(self) -> None:
        """Request project details and one event page, without fan-out reads."""
        if self.project_uid:
            self._load(self.project_uid, self._generation)
        else:
            self.query_one("#overview-status", Static).update(
                "Choose a project to load its overview."
            )

    @work(exclusive=True, group="overview", exit_on_error=False)
    async def _load(self, project_uid: str, generation: int) -> None:
        """Keep independent source outcomes and discard stale scope results."""
        status = self.query_one("#overview-status", Static)
        status.update("Loading project and recent events…")
        project_result = events_result = None
        failures: list[str] = []
        try:
            project_result = await self.service.read("project", project_uid=project_uid)
        except Exception as error:
            failures.append(f"Project details unavailable ({type(error).__name__})")
        if generation != self._generation or project_uid != self.project_uid:
            return
        try:
            events_result = await self.service.read("events", project_uid=project_uid)
        except Exception as error:
            failures.append(f"Recent events unavailable ({type(error).__name__})")
        if generation != self._generation or project_uid != self.project_uid:
            return
        self.project = project_result.rows[0] if project_result and project_result.rows else {}
        self.events = events_result.rows if events_result else ()
        self._render_data()
        status.update(
            " · ".join(failures)
            if failures
            else f"Project and one recent event page checked · {len(self.events)} events on this page"
        )

    def _render_data(self) -> None:
        project_name = self.project.get(
            "label", self.project.get("name", self.project_uid or "Project")
        )
        self.query_one("#overview-title", Label).update(
            safe_text(f"{project_name} · {self.project_uid or 'No project'}")
        )
        table = self.query_one("#overview-events", DataTable)
        table.clear()
        used: set[str] = set()
        for index, row in enumerate(self.events):
            key = str(row.get("event") or f"anonymous:{index}")
            while key in used:
                key = f"{key}#{index}"
            used.add(key)
            table.add_row(
                safe_text(row.get("when", row.get("received", "not reported"))),
                safe_text(row.get("file", "not reported")),
                safe_text(row.get("device", "not reported")),
                safe_text(record_label(row)),
                key=key,
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Send navigation intent to the parent app, which owns routing."""
        target = (event.button.id or "").removeprefix("overview-open-")
        if target and self.on_open:
            self.on_open(target, {})


__all__ = ["OverviewPanel"]
