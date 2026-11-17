"""Lazy, project-scoped operations reads."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Select, Static

from ..presentation import record_label, safe_text

if TYPE_CHECKING:
    from ..service import ReadService

SECTIONS = ("routes", "jobs", "monitors", "usage")


class OperationsPanel(Vertical):
    """Read one operations section at a time and preserve per-section results."""

    DEFAULT_CSS = """
    OperationsPanel { height: 1fr; padding: 1; }
    OperationsPanel #operations-section { width: 36; }
    OperationsPanel #operations-status { height: 1; color: $text-muted; }
    OperationsPanel #operations-records { height: 1fr; }
    """

    def __init__(
        self,
        service: ReadService,
        project_uid: str | None = None,
        *,
        auto_load: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.service = service
        self.project_uid = project_uid
        self._active = auto_load
        self.section = "routes"
        self.results: dict[str, tuple[dict[str, Any], ...]] = {}
        self.failures: dict[str, str] = {}
        self._generation = 0

    def compose(self) -> ComposeResult:
        """Compose the section selector, status and reported records."""
        yield Static("Operations · source-reported values", id="operations-title")
        yield Select(
            [(section.title(), section) for section in SECTIONS],
            value="routes",
            id="operations-section",
        )
        yield Static("Choose a section to read it.", id="operations-status")
        yield DataTable(id="operations-records", cursor_type="row", zebra_stripes=True)

    def render(self) -> Text:
        """Render a blank container background behind composed children."""
        return Text(" ")

    def on_mount(self) -> None:
        """Set table columns and load the initial Routes section."""
        self.query_one("#operations-records", DataTable).add_columns(
            "Record", "Reported status", "Details"
        )
        if self.project_uid and self._active:
            self.load_section()

    def set_scope(self, project_uid: str | None) -> None:
        """Set project and clear data that belongs to the previous scope."""
        if project_uid == self.project_uid:
            return
        self.project_uid = project_uid
        self._generation += 1
        self.results.clear()
        self.failures.clear()
        if self.is_mounted:
            self.query_one("#operations-records", DataTable).clear()
            if self._active:
                self.load_section()

    def activate(self) -> None:
        """Load the selected section only after its workspace is opened."""
        was_active = self._active
        self._active = True
        if self.project_uid and not was_active:
            self.load_section()

    @on(Select.Changed, "#operations-section")
    def section_changed(self, event: Select.Changed) -> None:
        """Load a section on demand and reuse its session result thereafter."""
        if event.value is Select.NULL:
            return
        self.section = str(event.value)
        self._render_data()
        if self._active and self.section not in self.results:
            self.load_section()

    def load_section(self) -> None:
        """Read only the selected section, never all operations at once."""
        if self.project_uid:
            self._read(self.section, self.project_uid, self._generation)
        else:
            self.query_one("#operations-status", Static).update("Choose a project first.")

    def refresh_data(self) -> None:
        """Refresh the visible section only."""
        self._active = True
        self.results.pop(self.section, None)
        self.load_section()

    @work(exclusive=True, group="operations", exit_on_error=False)
    async def _read(self, section: str, project_uid: str, generation: int) -> None:
        self.query_one("#operations-status", Static).update(f"Reading {section}…")
        try:
            page = await self.service.read(section, project_uid=project_uid)
        except Exception as error:
            if generation != self._generation or project_uid != self.project_uid:
                return
            self.failures[section] = type(error).__name__
            self._render_data()
            return
        if generation != self._generation or project_uid != self.project_uid:
            return
        self.failures.pop(section, None)
        self.results[section] = page.rows
        self._render_data()

    def _render_data(self) -> None:
        table = self.query_one("#operations-records", DataTable)
        table.clear()
        rows = self.results.get(self.section, ())
        used: set[str] = set()
        for index, row in enumerate(rows):
            status = row.get("status", row.get("disabled", "not reported"))
            details = row.get("label", row.get("date", row.get("count", "not reported")))
            key = str(row.get("uid", f"{self.section}:{index}"))
            while key in used:
                key = f"{key}#{index}"
            used.add(key)
            table.add_row(
                safe_text(record_label(row)), safe_text(status), safe_text(details), key=key
            )
        failure = self.failures.get(self.section)
        if failure:
            message = f"{self.section.title()} unavailable ({failure}); retry this section."
        elif self.section in self.results:
            message = f"{len(rows)} returned records · source values only"
        else:
            message = "Section has not been loaded."
        self.query_one("#operations-status", Static).update(safe_text(message))


__all__ = ["SECTIONS", "OperationsPanel"]
