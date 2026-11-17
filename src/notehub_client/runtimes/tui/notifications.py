"""Session-only notification history and safe Textual toast adapter."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Label

from .presentation import safe_text

if TYPE_CHECKING:
    from textual.app import App

NotificationCategory = Literal["information", "warning", "error", "success"]
TargetKind = Literal["event", "device"]


@dataclass(frozen=True, slots=True)
class NotificationEntry:
    """Safe, navigable notification metadata without source payloads."""

    created_at: datetime
    category: NotificationCategory
    summary: str
    project_uid: str | None = None
    target_kind: TargetKind | None = None
    target_uid: str | None = None


class NotificationCenter:
    """Bounded inbox owned by one authenticated app session."""

    def __init__(self, *, limit: int = 100) -> None:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("notification limit must be from 1 to 100")
        self._entries: deque[NotificationEntry] = deque(maxlen=limit)

    @property
    def entries(self) -> tuple[NotificationEntry, ...]:
        """Newest first, as an immutable view."""
        return tuple(reversed(self._entries))

    @property
    def unread_count(self) -> int:
        """Return entries currently held in this session's inbox."""
        return len(self._entries)

    def add(
        self,
        category: NotificationCategory,
        summary: str,
        *,
        project_uid: str | None = None,
        target_kind: TargetKind | None = None,
        target_uid: str | None = None,
    ) -> NotificationEntry:
        """Add sanitized metadata and return its immutable entry."""
        if category not in {"information", "warning", "error", "success"}:
            raise ValueError("unsupported notification category")
        if target_kind is not None and target_kind not in {"event", "device"}:
            raise ValueError("unsupported notification target")
        if (target_kind is None) != (target_uid is None):
            raise ValueError("target kind and UID must be supplied together")
        entry = NotificationEntry(
            datetime.now(timezone.utc),
            category,
            safe_text(summary).plain[:240],
            safe_text(project_uid).plain[:256] if project_uid else None,
            target_kind,
            safe_text(target_uid).plain[:256] if target_uid else None,
        )
        self._entries.append(entry)
        return entry

    def clear(self) -> None:
        """Erase all session notifications on disconnect."""
        self._entries.clear()


def notify_safe(
    app: App[Any],
    center: NotificationCenter,
    category: NotificationCategory,
    summary: str,
    *,
    project_uid: str | None = None,
    target_kind: TargetKind | None = None,
    target_uid: str | None = None,
    toasts_enabled: bool = True,
) -> NotificationEntry:
    """Add an inbox item and optionally show a literal four-second toast."""
    entry = center.add(
        category, summary, project_uid=project_uid, target_kind=target_kind, target_uid=target_uid
    )
    if toasts_enabled:
        severity = (
            "error"
            if category == "error"
            else "warning"
            if category == "warning"
            else "information"
        )
        app.notify(entry.summary, title="Notehub", severity=severity, timeout=4, markup=False)
    return entry


class NotificationInboxScreen(ModalScreen[NotificationEntry | None]):
    """Keyboard-accessible view of session notifications."""

    BINDINGS = [("escape", "cancel", "Back")]
    DEFAULT_CSS = """
    NotificationInboxScreen { align: center middle; background: $background 70%; }
    NotificationInboxScreen > Vertical { width: 85%; height: 80%; padding: 1 2;
        border: round $accent; background: $surface; }
    NotificationInboxScreen DataTable { height: 1fr; }
    NotificationInboxScreen Horizontal { height: 3; }
    """

    def __init__(self, center: NotificationCenter) -> None:
        super().__init__()
        self.center = center

    def compose(self) -> ComposeResult:
        """Render the safe notification list and available actions."""
        with Vertical():
            yield Label("Session inbox · opening a target returns it to the app")
            yield DataTable(id="notification-list", cursor_type="row")
            with Horizontal():
                yield Button("Open", id="notification-open", variant="primary")
                yield Button("Clear inbox", id="notification-clear")
                yield Button("Close", id="notification-close")

    def on_mount(self) -> None:
        """Populate the table when the inbox opens."""
        table = self.query_one(DataTable)
        table.add_columns("Time (UTC)", "Type", "Summary", "Scope")
        for index, entry in enumerate(self.center.entries):
            table.add_row(
                entry.created_at.strftime("%H:%M:%S"),
                entry.category,
                safe_text(entry.summary),
                safe_text(entry.project_uid or "Session"),
                key=str(index),
            )
        if table.row_count:
            table.focus()
        else:
            self.query_one("#notification-open", Button).disabled = True

    def action_cancel(self) -> None:
        """Dismiss the inbox without opening a target."""
        self.dismiss(None)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Return the selected entry as the modal result."""
        self._open(str(event.row_key.value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Open, Clear, and Close controls."""
        if event.button.id == "notification-close":
            self.dismiss(None)
        elif event.button.id == "notification-clear":
            self.center.clear()
            self.dismiss(None)
        elif event.button.id == "notification-open":
            table = self.query_one(DataTable)
            if table.row_count:
                self._open(str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value))

    def _open(self, key: str) -> None:
        try:
            entry = self.center.entries[int(key)]
        except (ValueError, IndexError):
            self.dismiss(None)
        else:
            self.dismiss(entry)


__all__ = ["NotificationCenter", "NotificationEntry", "NotificationInboxScreen", "notify_safe"]
