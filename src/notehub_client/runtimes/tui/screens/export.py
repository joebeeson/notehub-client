"""Explicit JSON export with replacement confirmation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from ..presentation import safe_text, sanitize_record


class ExportScreen(ModalScreen[Path | None]):
    """Save a sanitized selected record or explicitly scoped page as UTF-8 JSON."""

    DEFAULT_CSS = """
    ExportScreen { align: center middle; }
    ExportScreen > Vertical { width: 76; height: auto; max-height: 90%; padding: 1 2; background: $surface; border: round $accent; }
    ExportScreen Input { width: 1fr; }
    ExportScreen Static { height: auto; }
    """
    BINDINGS = [("escape", "dismiss(None)", "Cancel")]

    def __init__(
        self,
        value: object,
        title: str = "Export selected record",
        *,
        feedback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        if isinstance(value, Mapping):
            self.value: Any = sanitize_record(value)
        elif isinstance(value, (tuple, list)):
            self.value = [
                sanitize_record(item) if isinstance(item, Mapping) else item for item in value
            ]
        else:
            self.value = value
        self.heading = title
        self.feedback = feedback
        self._confirmed_path: Path | None = None

    def compose(self) -> ComposeResult:
        """Build path and explicit replacement controls."""
        with Vertical():
            yield Label(safe_text(self.heading))
            yield Label("Parsed JSON; environment values and credentials are excluded.")
            yield Input(placeholder="Path to UTF-8 JSON file", id="export-path")
            yield Static(
                "Choose a path. Existing files require explicit replacement.",
                id="export-status",
                markup=False,
            )
            yield Button("Save JSON", id="export-save", variant="primary")
            yield Button(
                "Replace existing file", id="export-replace", variant="error", disabled=True
            )
            yield Button("Cancel", id="export-cancel")

    @on(Input.Changed, "#export-path")
    def reset_confirmation(self) -> None:
        """Invalidate replacement consent after editing the destination."""
        self._confirmed_path = None
        self.query_one("#export-replace", Button).disabled = True

    @on(Button.Pressed, "#export-save")
    async def save(self) -> None:
        """Create a new file, offering separate confirmation if it exists."""
        await self._write(replace=False)

    @on(Button.Pressed, "#export-replace")
    async def replace(self) -> None:
        """Replace only the exact destination previously confirmed as existing."""
        await self._write(replace=True)

    async def _write(self, *, replace: bool) -> None:
        raw = self.query_one("#export-path", Input).value.strip()
        status = self.query_one("#export-status", Static)
        if not raw:
            status.update("Enter a file path.")
            return
        path = Path(raw).expanduser().absolute()
        if replace and path != self._confirmed_path:
            status.update("Choose Save first to review this destination.")
            return

        def write() -> None:
            text = json.dumps(self.value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            with path.open("w" if replace else "x", encoding="utf-8") as stream:
                stream.write(text)

        try:
            await asyncio.to_thread(write)
        except FileExistsError:
            self._confirmed_path = path
            self.query_one("#export-replace", Button).disabled = False
            status.update(
                safe_text(f"Already exists: {path}. Select Replace existing file to overwrite it.")
            )
        except (OSError, TypeError, ValueError):
            status.update("Could not save JSON. Check the destination and permissions.")
        else:
            if self.feedback is None:
                self.notify("Export saved.", markup=False)
            else:
                self.feedback("Export saved.")
            self.dismiss(path)

    @on(Button.Pressed, "#export-cancel")
    def cancel(self) -> None:
        """Leave without exporting."""
        self.dismiss(None)
