"""Generate credential-free, headless TUI screenshots for the docs and README."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, tzinfo
from pathlib import Path

from notehub_client.runtimes.tui import state as tui_state
from notehub_client.runtimes.tui.app import NotehubApp
from notehub_client.runtimes.tui.demo import DEMO_PROJECT_UID
from notehub_client.runtimes.tui.state import TUIOptions


class _FixedDateTime(datetime):
    """Freeze the visible check time so generated documentation diffs stay stable."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> _FixedDateTime:
        return cls(2026, 11, 17, 12, 0, 0, tzinfo=tz)


async def _save_events_preview(width: int, height: int, output: Path) -> None:
    """Render one demo Events view and write its normalized SVG screenshot."""
    app = NotehubApp(options=TUIOptions(demo=True, project_uid=DEMO_PROJECT_UID))
    async with app.run_test(size=(width, height)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("2")
        await pilot.pause(0.1)
        svg = app.export_screenshot()
    if not svg:
        raise RuntimeError("Textual did not export a screenshot")
    normalized = re.sub(r"\bterminal-\d+-([\w-]+)", r"terminal-\1", svg)
    portable = re.sub(r"\s*@font-face\s*\{[^}]*\}\s*", "\n", normalized, flags=re.DOTALL)
    output.write_text(portable, encoding="utf-8")


async def _main() -> None:
    """Write compact and wide demo screenshots into the documentation image folder."""
    tui_state.datetime = _FixedDateTime
    images = Path(__file__).resolve().parents[1] / "images"
    images.mkdir(parents=True, exist_ok=True)
    for width, height, name in (
        (80, 24, "tui-events-compact.svg"),
        (140, 42, "tui-events-wide.svg"),
    ):
        await _save_events_preview(width, height, images / name)


if __name__ == "__main__":
    asyncio.run(_main())
