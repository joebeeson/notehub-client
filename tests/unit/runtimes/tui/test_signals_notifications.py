from unittest.mock import Mock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Checkbox, Sparkline, Static

from notehub_client.observe import RequestFinished, RequestStarted
from notehub_client.runtimes.tui.notifications import (
    NotificationCenter,
    NotificationInboxScreen,
    notify_safe,
)
from notehub_client.runtimes.tui.screens.copy import CopyScreen
from notehub_client.runtimes.tui.screens.export import ExportScreen
from notehub_client.runtimes.tui.widgets.signals import (
    SignalKind,
    SignalSettingsScreen,
    SignalStrip,
    receipt_delays,
)
from notehub_client.runtimes.tui.widgets.status import RequestActivity


def test_receipt_delay_uses_finite_timestamp_pairs_and_excludes_negative_values() -> None:
    rows = [
        {"when": 10, "received": 12},
        {"when": 11, "received": 10},
        {"when": 12, "received": 12.5},
        {"when": True, "received": 99},
        {"when": float("nan"), "received": 99},
        {"when": 14, "received": float("inf")},
    ]
    assert receipt_delays(rows) == (2.0, 0.5)


def test_notification_center_is_bounded_sanitized_and_clearable() -> None:
    center = NotificationCenter(limit=2)
    center.add("information", "[red]literal[/red]\x1b[31m", project_uid="app:one")
    center.add("warning", "second")
    center.add("success", "third", target_kind="event", target_uid="ev:3")
    assert center.unread_count == 2
    assert [item.summary for item in center.entries] == ["third", "second"]
    assert center.entries[0].target_uid == "ev:3"
    center.clear()
    assert center.unread_count == 0


def test_notification_center_rejects_invalid_target_pairs() -> None:
    center = NotificationCenter()
    with pytest.raises(ValueError, match="supplied together"):
        center.add("information", "x", target_kind="device")  # type: ignore[arg-type]


class SignalApp(App[None]):
    def compose(self) -> ComposeResult:
        activity = RequestActivity()
        activity.durations.extend([12.0, 31.5, 19.0])
        yield SignalStrip(
            activity,
            [
                {"when": 10, "received": 11},
                {"when": 12, "received": 14},
                {"when": 15, "received": 18},
            ],
        )


@pytest.mark.asyncio
async def test_signal_strip_uses_existing_samples_and_can_be_reconfigured() -> None:
    async with SignalApp().run_test(size=(140, 42)) as pilot:
        strip = pilot.app.query_one(SignalStrip)
        assert len(strip.query(Sparkline)) == 2
        assert "3 samples" in str(strip.query(".instrument-meta")[0].render())
        strip.configure((SignalKind.RECEIPT_DELAY,))
        await pilot.pause()
        assert len(strip.query(Sparkline)) == 1
        assert "No samples" not in str(strip.query(".instrument-meta")[0].render())


@pytest.mark.asyncio
async def test_signal_settings_apply_and_cancel_return_session_choices() -> None:
    class Host(App[None]):
        def compose(self) -> ComposeResult:
            yield Static("host")

    app = Host()
    async with app.run_test(size=(100, 30)) as pilot:
        result: list[object] = []
        app.push_screen(SignalSettingsScreen((SignalKind.REQUEST_DURATION,)), result.append)
        await pilot.pause()
        screen = app.screen
        screen.query_one("#signal-receipt-delay", Checkbox).value = True
        screen.query_one("#signal-apply").press()
        await pilot.pause()
        assert result == [(SignalKind.REQUEST_DURATION, SignalKind.RECEIPT_DELAY)]


@pytest.mark.asyncio
async def test_inbox_keyboard_selection_returns_safe_target() -> None:
    center = NotificationCenter()
    center.add(
        "information",
        "event arrived",
        project_uid="app:one",
        target_kind="event",
        target_uid="ev:1",
    )

    class Host(App[None]):
        def compose(self) -> ComposeResult:
            yield Static("host")

    app = Host()
    async with app.run_test(size=(100, 30)) as pilot:
        results: list[object] = []
        app.push_screen(NotificationInboxScreen(center), results.append)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert results[0].target_uid == "ev:1"


@pytest.mark.asyncio
async def test_copy_feedback_uses_session_inbox_adapter() -> None:
    class Host(App[None]):
        def compose(self) -> ComposeResult:
            yield Static("host")

    app = Host()
    feedback: list[str] = []
    async with app.run_test(size=(100, 30)) as pilot:
        app.copy_to_clipboard = Mock()
        app.push_screen(CopyScreen("evt:1", feedback=feedback.append))
        await pilot.pause()
        await pilot.click("#copy-request")
        assert feedback == ["Copy requested; terminal permission may be required."]


@pytest.mark.asyncio
async def test_export_success_uses_session_inbox_adapter(tmp_path) -> None:
    class Host(App[None]):
        def compose(self) -> ComposeResult:
            yield Static("host")

    app = Host()
    feedback: list[str] = []
    target = tmp_path / "export.json"
    async with app.run_test(size=(100, 30)) as pilot:
        app.push_screen(ExportScreen({"event": "evt:1"}, feedback=feedback.append))
        await pilot.pause()
        app.screen.query_one("#export-path").value = str(target)
        app.screen.query_one("#export-save").press()
        await pilot.pause()
        assert target.exists()
        assert feedback == ["Export saved."]


@pytest.mark.asyncio
async def test_notify_safe_uses_literal_markup_off_and_inbox_entry() -> None:
    center = NotificationCenter()

    class Host(App[None]):
        def compose(self) -> ComposeResult:
            yield Static("host")

    app = Host()
    async with app.run_test(size=(100, 30)):
        app.notify = Mock()
        entry = notify_safe(app, center, "information", "[red]plain[/red]", toasts_enabled=False)
        assert entry.summary == "[red]plain[/red]"
        assert center.entries[0] == entry
        app.notify.assert_not_called()
        notify_safe(app, center, "warning", "literal [yellow] source", toasts_enabled=True)
        app.notify.assert_called_once_with(
            "literal [yellow] source", title="Notehub", severity="warning", timeout=4, markup=False
        )


def test_activity_samples_are_metadata_only() -> None:
    activity = RequestActivity()
    activity.on_event(RequestStarted(1, "GET", "projects/app:private/events", "events"))
    activity.on_event(RequestFinished(1, "GET", "projects/app:private/events", 200, 14.5, True))
    assert tuple(activity.durations) == (14.5,)
    assert activity.entries[0].outcome == "success"
    assert not hasattr(activity.entries[0], "path")
    activity.reset()
    assert not activity.entries
    assert not activity.durations
    assert not activity.counts
    assert not activity.active
