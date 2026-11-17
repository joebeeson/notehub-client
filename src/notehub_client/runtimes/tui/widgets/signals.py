"""Small session-only instruments built from existing Notehub observations."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label, Sparkline, Static

if TYPE_CHECKING:
    from .status import RequestActivity


class SignalKind(StrEnum):
    """Available numeric signals with a clear source and unit."""

    REQUEST_DURATION = "request_duration"
    RECEIPT_DELAY = "receipt_delay"


def receipt_delays(rows: Sequence[Mapping[str, Any]]) -> tuple[float, ...]:
    """Return nonnegative received-minus-captured seconds for this page."""
    values: list[tuple[float, float]] = []
    for row in rows:
        when, received = row.get("when"), row.get("received")
        if isinstance(when, bool) or not isinstance(when, (float, int)):
            continue
        if isinstance(received, bool) or not isinstance(received, (float, int)):
            continue
        captured = float(row.get("when_ms", when * 1000)) / 1000
        received_at = float(received)
        if not math.isfinite(captured) or not math.isfinite(received_at):
            continue
        values.append((captured, received_at - captured))
    return tuple(delay for _, delay in sorted(values) if delay >= 0)


class SignalStrip(Static):
    """Configurable two-instrument strip; it never starts network requests."""

    DEFAULT_CSS = """
    SignalStrip { height: 3; padding: 0 1; }
    SignalStrip Horizontal { height: 3; }
    SignalStrip .instrument { width: 1fr; height: 3; padding-right: 1; }
    SignalStrip Sparkline { height: 1; width: 1fr; }
    SignalStrip .instrument-title { height: 1; text-style: bold; }
    SignalStrip .instrument-meta { height: 1; color: $text-muted; }
    """

    def __init__(
        self,
        activity: RequestActivity | None = None,
        rows: Sequence[Mapping[str, Any]] = (),
        *,
        selected: Sequence[SignalKind] = (SignalKind.REQUEST_DURATION, SignalKind.RECEIPT_DELAY),
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.activity = activity
        self.rows = tuple(rows)
        self.selected = tuple(selected[:2])

    def compose(self) -> ComposeResult:
        """Render the selected instruments from already available data."""
        with Horizontal():
            for kind in self.selected:
                yield from self._instrument(kind)

    def _instrument(self, kind: SignalKind) -> ComposeResult:
        values = self._values(kind)
        with Vertical(classes="instrument"):
            if kind == SignalKind.REQUEST_DURATION:
                title = "Request duration · ms"
                source = "completed reads this session"
                reducer = max
            else:
                title = "Receipt delay · seconds"
                source = "timed events on this loaded page"
                reducer = max
            yield Label(title, classes="instrument-title")
            if len(values) >= 2:
                yield Sparkline(values[-60:], summary_function=reducer)
                yield Static(self._summary(values, source), classes="instrument-meta")
            else:
                yield Static(self._summary(values, source), classes="instrument-meta")

    def _values(self, kind: SignalKind) -> tuple[float, ...]:
        if kind == SignalKind.REQUEST_DURATION:
            raw = tuple(self.activity.durations) if self.activity else ()
        else:
            raw = receipt_delays(self.rows)
        return tuple(
            float(value)
            for value in raw
            if not isinstance(value, bool) and math.isfinite(float(value))
        )

    @staticmethod
    def _summary(values: tuple[float, ...], source: str) -> str:
        if not values:
            return f"No samples · {source}"
        if len(values) < 2:
            return f"{values[-1]:g} · 1 sample · not enough samples for a trend"
        return f"{len(values)} samples · min {min(values):g} · max {max(values):g} · {source}"

    def set_data(self, activity: RequestActivity | None, rows: Sequence[Mapping[str, Any]]) -> None:
        """Replace data for the current scope and rebuild the instruments."""
        self.activity = activity
        self.rows = tuple(rows)
        self.refresh(recompose=True)

    def configure(self, selected: Sequence[SignalKind]) -> None:
        """Select up to two instruments for this app session."""
        self.selected = tuple(dict.fromkeys(selected))[:2]
        self.refresh(recompose=True)


class SignalSettingsScreen(ModalScreen[tuple[SignalKind, ...] | None]):
    """Choose which built-in signals appear during the current session."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    SignalSettingsScreen { align: center middle; background: $background 70%; }
    SignalSettingsScreen > Vertical { width: 64; height: 15; padding: 1 2;
        border: round $accent; background: $surface; }
    SignalSettingsScreen Horizontal { height: 3; }
    """

    def __init__(self, selected: Sequence[SignalKind] = ()) -> None:
        super().__init__()
        self.selected = set(selected)

    def compose(self) -> ComposeResult:
        """Render session-local signal choices."""
        with Vertical():
            yield Label("Choose up to two session signals")
            yield Checkbox(
                "Request duration (ms, completed reads)",
                value=SignalKind.REQUEST_DURATION in self.selected,
                id="signal-request-duration",
            )
            yield Checkbox(
                "Receipt delay (s, current page)",
                value=SignalKind.RECEIPT_DELAY in self.selected,
                id="signal-receipt-delay",
            )
            yield Static("Signals use data already collected; this does not start requests.")
            with Horizontal():
                yield Button("Apply", id="signal-apply", variant="primary")
                yield Button("Cancel", id="signal-cancel")

    def action_cancel(self) -> None:
        """Close without changing session preferences."""
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Apply the selected instruments or cancel the draft."""
        if event.button.id == "signal-cancel":
            self.action_cancel()
        elif event.button.id == "signal-apply":
            selected = []
            for kind, identifier in (
                (SignalKind.REQUEST_DURATION, "#signal-request-duration"),
                (SignalKind.RECEIPT_DELAY, "#signal-receipt-delay"),
            ):
                if self.query_one(identifier, Checkbox).value:
                    selected.append(kind)
            self.dismiss(tuple(selected[:2]))


__all__ = ["SignalKind", "SignalSettingsScreen", "SignalStrip", "receipt_delays"]
