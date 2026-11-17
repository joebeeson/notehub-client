"""Bounded cursor navigation independent of terminal widgets."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...errors import NotehubResponseError
from .state import PageResult


@dataclass(slots=True)
class CursorHistory:
    """Retain bounded page snapshots and detect loops within retained history."""

    capacity: int = 10
    _pages: list[tuple[str, PageResult]] = field(default_factory=list, repr=False)
    _position: int = -1
    _seen: set[str] = field(default_factory=set, repr=False)

    @property
    def current(self) -> PageResult | None:
        """Return the visible page, when one has been loaded."""
        return self._pages[self._position][1] if self._position >= 0 else None

    @property
    def current_cursor(self) -> str | None:
        """Return the request cursor associated with the visible page."""
        return self._pages[self._position][0] if self._position >= 0 else None

    @property
    def can_previous(self) -> bool:
        """Whether a preceding page is retained."""
        return self._position > 0

    @property
    def next_cursor(self) -> str | None:
        """Return the cursor to fetch, or None when traversal is complete."""
        page = self.current
        if page is None:
            return "0"
        if self._position + 1 < len(self._pages):
            return self._pages[self._position + 1][0]
        return page.next_cursor if page.has_more else None

    @property
    def can_next(self) -> bool:
        """Whether a retained page or server continuation is available."""
        return self.current is not None and self.next_cursor is not None

    def reset(self) -> None:
        """Discard snapshots when a query or scope changes."""
        self._pages.clear()
        self._seen.clear()
        self._position = -1

    def append(self, cursor: str, page: PageResult) -> None:
        """Accept one page, rejecting loops before changing visible state."""
        if cursor in self._seen or (
            page.has_more
            and (
                not page.next_cursor or page.next_cursor == cursor or page.next_cursor in self._seen
            )
        ):
            raise NotehubResponseError("Event cursor missing or repeated; restart the query")
        if self.capacity < 1:
            raise ValueError("capacity must be positive")
        self._pages = self._pages[: self._position + 1]
        self._seen = {page_cursor for page_cursor, _ in self._pages}
        self._pages.append((cursor, page))
        self._seen.add(cursor)
        if len(self._pages) > self.capacity:
            evicted_cursor, _ = self._pages.pop(0)
            self._seen.discard(evicted_cursor)
        self._position = len(self._pages) - 1

    def previous(self) -> PageResult | None:
        """Select a retained preceding page without making a request."""
        if self.can_previous:
            self._position -= 1
        return self.current

    def forward(self) -> PageResult | None:
        """Select a retained following page, or None when a read is needed."""
        if self._position + 1 < len(self._pages):
            self._position += 1
            return self.current
        return None


__all__ = ["CursorHistory"]
