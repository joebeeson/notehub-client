"""Immutable values shared by the terminal workbench."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from ...filters import Query


class ViewId(str, Enum):
    """Primary workspaces available through navigation and commands."""

    OVERVIEW = "overview"
    EVENTS = "events"
    DEVICES = "devices"
    FLEETS = "fleets"
    OPERATIONS = "operations"
    ACCOUNT = "account"
    SIMULATION = "simulation"


@dataclass(frozen=True, slots=True)
class TUIOptions:
    """Credential-free startup options suitable for embedding."""

    project_uid: str | None = None
    token_file: Path | None = None
    demo: bool = False


@dataclass(frozen=True, slots=True)
class Scope:
    """Identifiers that scope the current workspace."""

    project_uid: str | None = None
    device_uid: str | None = None
    fleet_uid: str | None = None


@dataclass(frozen=True, slots=True)
class Location:
    """A restorable navigation destination."""

    view: ViewId = ViewId.OVERVIEW
    scope: Scope = field(default_factory=Scope)
    selected_key: str | None = None


@dataclass(frozen=True, slots=True)
class PageResult:
    """A bounded result and its explicit continuation metadata."""

    rows: tuple[dict[str, Any], ...] = ()
    row_keys: tuple[str, ...] = ()
    has_more: bool | None = None
    next_cursor: str | None = None
    page_num: int | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __rich_repr__(self) -> Iterator[tuple[str, object]]:
        """Expose page diagnostics without dumping record values or opaque cursors."""
        yield ("row_count", len(self.rows))
        yield ("has_more", self.has_more)
        if self.page_num is not None:
            yield ("page_num", self.page_num)
        if self.next_cursor is not None:
            yield ("next_cursor_available", True)
        yield ("checked_at", self.checked_at)


@dataclass(frozen=True, slots=True)
class ViewState:
    """Last-good workspace data retained while a replacement read is pending."""

    query: Query = field(default_factory=Query)
    selected_key: str | None = None
    scroll_y: float = 0
    cursor: str = "0"
    page_num: int = 1
    result: PageResult | None = None


__all__ = ["Location", "PageResult", "Scope", "TUIOptions", "ViewId", "ViewState"]
