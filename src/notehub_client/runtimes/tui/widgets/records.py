"""Shared, source-faithful record formatting for resource views."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.widgets import DataTable, Label

from ..presentation import safe_string, safe_text
from ..state import PageResult

RecordField = str | tuple[str, ...]


def display_field(record: dict[str, Any], key: RecordField, missing: str = "not reported") -> str:
    """Format an optional source field without implying absent values."""
    value: Any = record
    for part in (key,) if isinstance(key, str) else key:
        if not isinstance(value, dict):
            return missing
        value = value.get(part)
    return missing if value is None or value == "" else safe_string(value)


def record_table(
    title: str,
    page: PageResult | None,
    columns: tuple[str, ...],
    fields: tuple[str, ...],
    *,
    empty: str = "No records were returned.",
) -> ComposeResult:
    """Compose a bounded table with consistent empty and continuation states."""
    yield Label(title, classes="resource-heading")
    table = DataTable(cursor_type="row", zebra_stripes=True, classes="resource-table")
    table.add_columns(*columns)
    rows = page.rows if page is not None else ()
    row_keys = page.row_keys if page is not None else ()
    for index, row in enumerate(rows):
        key = row_keys[index] if index < len(row_keys) else f"anonymous:{index}"
        table.add_row(*(safe_text(display_field(row, field)) for field in fields), key=key)
    if table.row_count == 0:
        yield Label(empty, classes="resource-empty")
    else:
        yield table
    if page is not None and page.has_more is True:
        yield Label("More records are available on the next page.", classes="resource-page-hint")
    elif page is not None and page.has_more is None:
        yield Label(
            "Returned records; total availability was not reported.",
            classes="resource-page-hint",
        )


def populate_record_table(
    table: DataTable,
    page: PageResult | None,
    fields: tuple[RecordField, ...],
    empty_label: Label,
) -> None:
    """Replace a mounted detail table without rebuilding its parent screen."""
    table.clear()
    rows = page.rows if page is not None else ()
    row_keys = page.row_keys if page is not None else ()
    for index, row in enumerate(rows):
        key = row_keys[index] if index < len(row_keys) else f"anonymous:{index}"
        table.add_row(*(safe_text(display_field(row, field)) for field in fields), key=key)
    table.display = bool(rows)
    empty_label.display = not rows


__all__ = ["display_field", "populate_record_table", "record_table"]
