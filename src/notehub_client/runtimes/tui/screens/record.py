"""Full-width record inspection for compact terminal layouts."""

from typing import Any

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer

from ..widgets.inspector import RecordInspector


class RecordScreen(Screen[None]):
    """Inspect a cached record and return to the original table."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, record: dict[str, Any]) -> None:
        super().__init__()
        self.record = record

    def compose(self) -> ComposeResult:
        """Show the inspector in a full-screen context."""
        yield RecordInspector(self.record)
        yield Footer()
