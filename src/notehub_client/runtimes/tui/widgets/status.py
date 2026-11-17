"""Bounded, metadata-only request observations for Textual presentation."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone

from textual.widgets import Static

from ....observe import RequestCancelled, RequestFailed, RequestFinished, RequestStarted
from ..presentation import safe_text


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    """A safe request outcome without response, query, or credential values."""

    checked_at: datetime
    outcome: str
    status_code: int | None
    duration_ms: float | None


class RequestActivity:
    """Observe request outcomes without owning terminal output or client lifetime."""

    def __init__(self) -> None:
        self.entries: deque[ActivityEntry] = deque(maxlen=200)
        self.durations: deque[float] = deque(maxlen=60)
        self.counts: Counter[str] = Counter()
        self.active: set[int] = set()

    def on_event(self, event: object, /) -> None:
        """Consume only safe request metadata; ignore other client events."""
        if isinstance(event, RequestStarted):
            self.active.add(event.request_id)
            return
        if not isinstance(event, (RequestFinished, RequestFailed, RequestCancelled)):
            return
        self.active.discard(event.request_id)
        status = event.status_code if isinstance(event, RequestFinished) else None
        outcome = (
            ("success" if event.successful else "http_error")
            if isinstance(event, RequestFinished)
            else ("cancelled" if isinstance(event, RequestCancelled) else "transport_error")
        )
        self.counts[outcome] += 1
        if isinstance(event, RequestFinished):
            self.durations.append(event.duration_ms)
        self.entries.append(
            ActivityEntry(datetime.now(timezone.utc), outcome, status, event.duration_ms)
        )

    def reset(self) -> None:
        """Clear observations when the credential session ends."""
        self.entries.clear()
        self.durations.clear()
        self.counts.clear()
        self.active.clear()


class ActivityStatus(Static):
    """A compact request state widget refreshed explicitly by the owning app."""

    def show_activity(self, activity: RequestActivity) -> None:
        """Present counts without making claims about device health."""
        self.update(
            safe_text(
                f"API reads: {len(activity.active)} active | {activity.counts['success']} succeeded | {sum(v for k, v in activity.counts.items() if k != 'success')} other outcomes"
            )
        )
