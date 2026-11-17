"""Reviewed SVG snapshots for the stable, credential-free demo workbench."""

from __future__ import annotations

from datetime import tzinfo

import pytest
from textual.pilot import Pilot

from notehub_client.runtimes.tui import state as tui_state
from notehub_client.runtimes.tui.app import NotehubApp
from notehub_client.runtimes.tui.demo import DEMO_PROJECT_UID
from notehub_client.runtimes.tui.state import TUIOptions


class _FixedDateTime(tui_state.datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> _FixedDateTime:
        return cls(2026, 11, 17, 12, 0, 0, tzinfo=tz)


@pytest.mark.parametrize(
    "terminal_size",
    [
        pytest.param((80, 24), id="compact"),
        pytest.param((140, 42), id="wide"),
    ],
)
def test_demo_events_visual_snapshot(
    snap_compare, monkeypatch: pytest.MonkeyPatch, terminal_size: tuple[int, int]
) -> None:
    """Pin the event workspace at compact and wide terminal dimensions."""
    monkeypatch.setattr(tui_state, "datetime", _FixedDateTime)
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))

    async def show_events(pilot: Pilot[None]) -> None:
        await pilot.pause(0.1)
        await pilot.press("2")
        await pilot.pause(0.1)

    assert snap_compare(app, terminal_size=terminal_size, run_before=show_events)
