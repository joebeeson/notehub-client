"""Rich human presentation and machine-readable CLI output."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from rich import box
from rich.console import Console
from rich.style import Style
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from typing import Any


_PREFERRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "projects": ("uid", "label", "role", "created"),
    "devices": ("uid", "best_id", "product_uid", "serial_number", "last_activity"),
    "events": ("when", "device", "file", "event", "sensor"),
}
_TITLES = {
    "projects": "🗂️  Projects",
    "project": "🗂️  Project",
    "devices": "📱  Devices",
    "device": "📱  Device",
    "events": "📡  Events",
    "environment_variables": "⚙️  Device environment",
}
_LABELS = {
    "uid": "UID",
    "label": "Name",
    "created": "Created",
    "best_id": "Best ID",
    "product_uid": "Product",
    "serial_number": "Serial number",
    "last_activity": "Last activity",
    "when": "Captured",
    "received": "Received",
    "device": "Device",
    "file": "Notefile",
    "event": "Event",
    "sensor": "Sensor",
    "name": "Variable",
    "value": "Value",
}
_REDACTED = "\u2022" * 8
_SECRET_NAME_MARKERS = (
    "password",
    "passwd",
    "passcode",
    "passphrase",
    "secret",
    "token",
    "credential",
    "privatekey",
    "apikey",
    "accesskey",
    "secretkey",
    "signingkey",
    "encryptionkey",
    "authorization",
    "bearer",
    "psk",
    "cookie",
)
_URL_PATTERN = re.compile(r"https?://[^\s<>\[\]{}\"']+", re.IGNORECASE)


def emit_result(
    value: object,
    *,
    output_format: str,
    records_key: str | None = None,
    entity: str | None = None,
    show_secrets: bool = False,
) -> None:
    """Write a response in the selected format, preserving envelopes in JSON mode."""
    safe_value = _sanitize(value, show_secrets=show_secrets)
    if output_format == "json":
        click_echo(_json(safe_value, indent=2))
        return
    if output_format == "ndjson":
        for record in _records(safe_value, records_key):
            click_echo(_json(record))
        return
    _emit_human(safe_value, records_key=records_key, entity=entity)


def emit_ndjson(value: object, *, show_secrets: bool = False) -> None:
    """Write one event record as a compact JSON line."""
    click_echo(_json(_sanitize(value, show_secrets=show_secrets)))


def _emit_human(
    value: object,
    *,
    records_key: str | None,
    entity: str | None,
) -> None:
    console = Console(highlight=False)
    if isinstance(value, Mapping):
        summary = _action_summary(value)
        if summary is not None:
            console.print(summary)
            return
        if entity is not None and records_key is None:
            _print_key_values(console, value, title=_TITLES.get(entity, entity.title()))
            return

    rows = _records(value, records_key)
    if rows:
        table = _table(rows, records_key=records_key, entity=entity)
        console.print(table)
        if isinstance(value, Mapping):
            metadata = {
                key: item
                for key, item in value.items()
                if key not in {records_key, "has_more", "next_cursor"}
            }
            if metadata:
                _print_key_values(console, metadata, title="ℹ️  Details")
            if "has_more" in value:
                _print_page_status(console, value)
        return

    if (
        records_key is not None
        and isinstance(value, Mapping)
        and isinstance(value.get(records_key), list)
    ):
        title = _TITLES.get(records_key, records_key)
        console.print(Text(f"No {title.lower()} on this page.", style="dim"))
        if "has_more" in value:
            _print_page_status(console, value)
        return

    if isinstance(value, Mapping):
        environment = value.get("environment_variables")
        if isinstance(environment, Mapping):
            if not environment:
                console.print(Text("⚙️  No environment variables set.", style="dim"))
                return
            rows: list[Mapping[str, Any]] = [
                {"name": key, "value": item} for key, item in environment.items()
            ]
            console.print(_table(rows, records_key="environment_variables"))
            return
        if not value:
            console.print(Text("No results.", style="dim"))
            return
        _print_key_values(console, value, title=_TITLES.get(entity or "", "📄  Result"))
        return

    if value is None:
        console.print(Text("✓ Done.", style="green"))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            console.print(_cell(item))
    else:
        console.print(_cell(value))


def _table(
    rows: list[Mapping[str, Any]],
    *,
    records_key: str | None = None,
    entity: str | None = None,
) -> Table:
    keys = _columns(rows, records_key)
    title = _TITLES.get(records_key or "", _TITLES.get(entity or ""))
    table = Table(
        title=title,
        box=box.ROUNDED,
        header_style="bold cyan",
        border_style="blue",
        show_lines=False,
        pad_edge=False,
    )
    for key in keys:
        table.add_column(_LABELS.get(key, key.replace("_", " ").title()), overflow="fold")
    for row in rows:
        table.add_row(
            *(_cell(row.get(key), key=key, records_key=records_key, entity=entity) for key in keys)
        )
    return table


def _print_key_values(console: Console, value: Mapping[str, Any], *, title: str) -> None:
    table = Table(
        title=title,
        box=box.ROUNDED,
        header_style="bold cyan",
        border_style="blue",
        pad_edge=False,
    )
    table.add_column("Field", style="bold")
    table.add_column("Value", overflow="fold")
    for key, item in value.items():
        table.add_row(_cell(key), _cell(item, key=key))
    console.print(table)


def _print_page_status(console: Console, response: Mapping[str, Any]) -> None:
    if response.get("has_more"):
        message = Text("↪ More results")
        cursor = response.get("next_cursor")
        if cursor is not None:
            message.append(f" · next cursor {cursor}")
        console.print(message, style="dim")
    else:
        console.print(Text("✓ End of results", style="dim"))


def _records(value: object, records_key: str | None) -> list[Mapping[str, Any]]:
    if records_key is not None and isinstance(value, Mapping):
        items = value.get(records_key, [])
        if isinstance(items, list):
            return [item for item in items if isinstance(item, Mapping)]
        if records_key == "environment_variables" and isinstance(items, Mapping):
            return [{"name": key, "value": item} for key, item in items.items()]
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        return [value]
    return []


def _action_summary(value: Mapping[str, Any]) -> Text | None:
    action = value.get("action")
    project = value.get("project_uid")
    device = value.get("device_uid")
    if action == "devices.env.set":
        names = ", ".join(value.get("variables", [])) or "no variables"
        return Text(f"🔧 Updated {names} on device {device} in project {project}.")
    if action == "devices.env.delete":
        return Text(
            f"🗑️  Deleted environment variable {value.get('variable')!r} "
            f"from device {device} in project {project}."
        )
    note_actions = {
        "notes.add-qi": "Added queue-in note",
        "notes.add-db": "Added database note",
        "notes.update-db": "Updated database note",
        "notes.delete": "Deleted database note",
    }
    if action in note_actions:
        note_id = value.get("note_id")
        note_label = f" {note_id!r}" if note_id is not None else ""
        return Text(
            f"📝 {note_actions[action]}{note_label} in {value.get('notefile')!r} "
            f"on device {device} in project {project}."
        )
    return None


def _sanitize(value: object, *, show_secrets: bool) -> object:
    """Redact explicit secret sources and conventional sensitive wire keys."""
    reveal = getattr(value, "get_secret_value", None)
    if callable(reveal):
        if not show_secrets:
            return _REDACTED
        value = reveal()
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
    if isinstance(value, Mapping):
        safe: dict[str, object] = {}
        for key, item in value.items():
            name = str(key)
            if not show_secrets and _sensitive_name(name):
                safe[name] = _REDACTED
            else:
                safe[name] = _sanitize(item, show_secrets=show_secrets)
        return safe
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, show_secrets=show_secrets) for item in value]
    return value


def _sensitive_name(value: str) -> bool:
    normalized = "".join(character for character in value.casefold() if character.isalnum())
    return any(marker in normalized for marker in _SECRET_NAME_MARKERS)


def _columns(rows: list[Mapping[str, Any]], records_key: str | None) -> tuple[str, ...]:
    preferred = _PREFERRED_COLUMNS.get(records_key or "", ())
    available = set().union(*(row.keys() for row in rows))
    columns = [key for key in preferred if key in available]
    if not columns:
        columns = sorted(available)
    return tuple(columns[:8])


def _cell(
    value: object,
    *,
    key: str = "",
    records_key: str | None = None,
    entity: str | None = None,
) -> Text:
    if isinstance(value, (dict, list)):
        text = _json(value)
    else:
        text = "" if value is None else str(value)
    rendered = _linkify(text)
    icon = _cell_icon(key, value, records_key, entity)
    if icon:
        result = Text(f"{icon} ")
        result.append(rendered)
        return result
    return rendered


def _cell_icon(
    key: str,
    value: object,
    records_key: str | None,
    entity: str | None,
) -> str:
    kind = records_key or entity
    if key == "uid" and kind in {"projects", "project"}:
        return "🗂️"
    if key == "uid" and kind in {"devices", "device"}:
        return "📱"
    if kind == "events" and key == "device":
        return "📱"
    if kind == "events" and key == "file":
        return "📄"
    if kind == "events" and key == "event":
        return "📡"
    if kind == "environment_variables" and key == "name":
        return "🔐" if _sensitive_name(str(value)) else "⚙️"
    return ""


def _linkify(value: str) -> Text:
    """Render HTTP(S) URLs as OSC 8 hyperlinks in Rich-capable terminals."""
    value = "".join(
        character if character.isprintable() or character in "\r\n\t" else "�"
        for character in value
    )
    result = Text()
    position = 0
    for match in _URL_PATTERN.finditer(value):
        candidate = match.group(0)
        url = candidate.rstrip(".,;:!?")
        suffix = candidate[len(url) :]
        if not url:
            continue
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            continue
        result.append(value[position : match.start()])
        result.append(url, style=Style(link=url))
        result.append(suffix)
        position = match.end()
    result.append(value[position:])
    return result


def _json(value: object, *, indent: int | None = None) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        indent=indent,
        separators=None if indent else (",", ":"),
    )


def click_echo(value: str) -> None:
    """Echo machine-readable output without Click's color or markup handling."""
    from click import echo

    echo(value, color=False)


__all__ = ["emit_ndjson", "emit_result"]
