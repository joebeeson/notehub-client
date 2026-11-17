"""Draft-and-apply event query composer for cursor-paginated browsing."""

from __future__ import annotations

import json
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TextArea

from ....filters import Query

SELECTORS = {
    "deviceUID": ("Devices", "devices"),
    "files": ("Files", "files"),
    "fleetUID": ("Fleets", "fleets"),
    "sensorUID": ("Sensors", "sensors"),
    "sessionUID": ("Sessions", "sessions"),
    "eventUID": ("Events", "events"),
    "serialNumber": ("Serial numbers", "serials"),
}
STRUCTURED = {*SELECTORS, "startDate", "endDate", "dateType", "systemFilesOnly"}
FORBIDDEN = {"cursor", "pageSize", "pageNum", "sortBy", "sortOrder"}


def parse_date(value: str) -> int | datetime | None:
    """Parse epoch seconds or a timezone-aware ISO date for Query.date_range."""
    value = value.strip()
    if not value:
        return None
    if value.isdecimal():
        return int(value)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Use epoch seconds or a timezone-aware ISO-8601 date") from None
    if result.utcoffset() is None:
        raise ValueError("Dates must include a timezone, for example +00:00")
    return result


def build_query(
    selectors: dict[str, str],
    *,
    start: str = "",
    end: str = "",
    date_type: str = "",
    system_only: bool = False,
    advanced: str = "{}",
) -> Query:
    """Build a validated query without modifying the active query."""
    try:
        extra = json.loads(advanced or "{}")
    except json.JSONDecodeError as error:
        raise ValueError(f"Advanced JSON: invalid JSON at line {error.lineno}") from None
    if not isinstance(extra, dict):
        raise ValueError("Advanced JSON must be an object")
    if FORBIDDEN.intersection(extra):
        raise ValueError("Advanced JSON cannot contain pagination or sorting keys")
    if STRUCTURED.intersection(extra):
        raise ValueError("Use the structured fields for selectors, dates and system-file mode")
    query = Query()
    for key, raw in selectors.items():
        values = tuple(value.strip() for value in raw.split(",") if value.strip())
        if not values:
            continue
        methods = {
            "deviceUID": query.devices,
            "files": query.files,
            "fleetUID": query.fleets,
            "sensorUID": query.sensors,
            "sessionUID": query.sessions,
            "eventUID": query.events,
            "serialNumber": query.serial_numbers,
        }
        query = methods[key](*values)
    query = query.date_range(parse_date(start), parse_date(end))
    if date_type:
        query = query.date_type(date_type)  # type: ignore[arg-type]
    if system_only:
        query = query.system_files_only()
    return query.combine(Query.from_value(extra))


def remove_filter(query: Query, key: str) -> Query:
    """Return a newly composed, validated query without one filter key."""
    if not key:
        raise ValueError("filter key must be nonempty")
    params = Query.from_value(query).to_query_params()
    params.pop(key, None)
    return Query.from_value(params)


def _display_filter_value(value: object) -> str:
    if isinstance(value, tuple):
        return ", ".join(value)
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


class FilterScreen(ModalScreen[Query | None]):
    """Edit a query draft; Apply returns a new value and Escape cancels it."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    FilterScreen { align: center middle; background: $background 70%; }
    FilterScreen > VerticalScroll {
        width: 76; max-width: 95%; height: 90%; border: round $accent;
        background: $surface; padding: 1 2;
    }
    FilterScreen Input { margin-bottom: 1; }
    FilterScreen TextArea { height: 7; }
    FilterScreen #filter-error { color: $error; height: auto; }
    FilterScreen Horizontal { height: 3; margin-top: 1; }
    FilterScreen #filter-removals { height: auto; }
    FilterScreen .filter-removal { height: auto; min-height: 3; }
    FilterScreen .filter-removal Static { width: 1fr; height: auto; }
    FilterScreen .filter-removal Button { width: auto; }
    """

    def __init__(self, initial: Query | None = None) -> None:
        super().__init__()
        self.initial = initial or Query()
        self.draft_query = Query.from_value(self.initial)
        self._removal_keys = tuple(self.initial)

    def compose(self) -> ComposeResult:
        """Render structured selectors and an independent advanced JSON draft."""
        params = self.initial.to_query_params()
        with VerticalScroll():
            yield Label("Event filters - Apply starts a new query")
            if self._removal_keys:
                yield Label("Remove a filter from this draft", id="filter-removal-label")
                with Vertical(id="filter-removals"):
                    for index, key in enumerate(self._removal_keys):
                        yield Horizontal(
                            Static(f"{key} = {_display_filter_value(params[key])}", markup=False),
                            Button("Remove", id=f"filter-remove-{index}"),
                            classes="filter-removal",
                            id=f"filter-removal-row-{index}",
                        )
            for key, (label, identifier) in SELECTORS.items():
                value = params.get(key, "")
                text = ",".join(value) if isinstance(value, tuple) else str(value)
                yield Label(label + " (comma separated)")
                yield Input(text, id=f"filter-{identifier}")
            yield Label("From / To (epoch seconds or ISO-8601 with timezone)")
            yield Input(str(params.get("startDate", "")), id="filter-start")
            yield Input(str(params.get("endDate", "")), id="filter-end")
            date_type = params.get("dateType")
            if not isinstance(date_type, str) or date_type not in {"captured", "uploaded"}:
                date_type = Select.NULL
            yield Select[str](
                [("Captured", "captured"), ("Uploaded", "uploaded")],
                prompt="Default date type",
                value=date_type,
                id="filter-date-type",
            )
            yield Checkbox(
                "System files only", value=params.get("systemFilesOnly") is True, id="filter-system"
            )
            yield Label("Advanced JSON (additional query keys; no paging or sorting)")
            extra = {key: value for key, value in params.items() if key not in STRUCTURED}
            yield TextArea(json.dumps(extra, indent=2), id="filter-advanced")
            yield Static("", id="filter-error", markup=False)
            with Horizontal():
                yield Button("Apply", variant="primary", id="filter-apply")
                yield Button("Clear draft", id="filter-clear")
                yield Button("Cancel", id="filter-cancel")

    def action_cancel(self) -> None:
        """Dismiss without changing the active query."""
        self.dismiss(None)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Apply a valid draft or update modal feedback."""
        if event.button.id == "filter-cancel":
            self.action_cancel()
        elif event.button.id == "filter-clear":
            for widget in self.query(Input):
                widget.value = ""
            self.query_one(Select).value = Select.NULL
            self.query_one(Checkbox).value = False
            self.query_one(TextArea).load_text("{}")
            self.query_one("#filter-error", Static).update("")
            self.draft_query = Query()
            if self._removal_keys:
                self.query_one("#filter-removal-label", Label).display = False
                self.query_one("#filter-removals", Vertical).display = False
        elif event.button.id and event.button.id.startswith("filter-remove-"):
            index_text = event.button.id.removeprefix("filter-remove-")
            try:
                key = self._removal_keys[int(index_text)]
            except (ValueError, IndexError):
                return
            if not self._clear_filter_draft(key):
                return
            self.draft_query = remove_filter(self.draft_query, key)
            await self.query_one(f"#filter-removal-row-{index_text}", Horizontal).remove()
            removals = self.query_one("#filter-removals", Vertical)
            if not removals.children:
                self.query_one("#filter-removal-label", Label).display = False
                removals.display = False
            self.query_one("#filter-error", Static).update("")
        elif event.button.id == "filter-apply":
            try:
                date_type = self.query_one(Select).value
                query = build_query(
                    {
                        key: self.query_one(f"#filter-{identifier}", Input).value
                        for key, (_, identifier) in SELECTORS.items()
                    },
                    start=self.query_one("#filter-start", Input).value,
                    end=self.query_one("#filter-end", Input).value,
                    date_type=date_type if isinstance(date_type, str) else "",
                    system_only=self.query_one(Checkbox).value,
                    advanced=self.query_one(TextArea).text,
                )
            except (ValueError, TypeError) as error:
                self.query_one("#filter-error", Static).update(str(error))
            else:
                self.dismiss(query)

    def _clear_filter_draft(self, key: str) -> bool:
        """Clear one field in the form, retaining every other draft value."""
        if key in SELECTORS:
            self.query_one(f"#filter-{SELECTORS[key][1]}", Input).value = ""
        elif key == "startDate":
            self.query_one("#filter-start", Input).value = ""
        elif key == "endDate":
            self.query_one("#filter-end", Input).value = ""
        elif key == "dateType":
            self.query_one("#filter-date-type", Select).value = Select.NULL
        elif key == "systemFilesOnly":
            self.query_one(Checkbox).value = False
        else:
            advanced = self.query_one("#filter-advanced", TextArea)
            try:
                extra = json.loads(advanced.text or "{}")
            except json.JSONDecodeError as error:
                self.query_one("#filter-error", Static).update(
                    f"Fix Advanced JSON before removing a filter (line {error.lineno})"
                )
                return False
            if not isinstance(extra, dict):
                self.query_one("#filter-error", Static).update(
                    "Advanced JSON must be an object before removing a filter"
                )
                return False
            extra.pop(key, None)
            advanced.load_text(json.dumps(extra, indent=2))
        return True


__all__ = ["FilterScreen", "build_query", "parse_date", "remove_filter"]
