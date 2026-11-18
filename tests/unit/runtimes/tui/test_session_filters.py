import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from textual.app import App
from textual.containers import VerticalScroll
from textual.widgets import Input, Select, TextArea

from notehub_client.filters import Query
from notehub_client.runtimes.tui import main
from notehub_client.runtimes.tui.screens.filters import FilterScreen, build_query, remove_filter
from notehub_client.runtimes.tui.session import SessionController
from notehub_client.runtimes.tui.state import TUIOptions


def test_launcher_passes_explicit_scope_and_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTEHUB_PROJECT_UID", "environment")
    app = Mock()
    with patch("notehub_client.runtimes.tui.create_app", return_value=app) as factory:
        main(["--project", "explicit", "--demo"])
    assert factory.call_args.kwargs["options"] == TUIOptions(project_uid="explicit", demo=True)
    app.run.assert_called_once_with()


def test_launcher_rejects_stdin() -> None:
    with pytest.raises(SystemExit) as captured:
        main(["--token-file", "-"])
    assert captured.value.code == 2


def test_token_file_precedes_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "token"
    source.write_text("file-token\n", encoding="utf-8")
    monkeypatch.setenv("NOTEHUB_TOKEN", "env-token")
    session = SessionController(TUIOptions(token_file=source))
    assert session.token() == "file-token"
    assert SessionController(TUIOptions(demo=True, token_file=source)).token() is None


@pytest.mark.asyncio
async def test_owned_client_closes_once_and_borrowed_client_stays_open() -> None:
    client = Mock(aclose=AsyncMock())
    borrowed = SessionController(client=client)
    assert borrowed.connect() is client
    await borrowed.disconnect()
    client.aclose.assert_not_called()
    with patch("notehub_client.runtimes.tui.session.NotehubClient", return_value=client):
        owned = SessionController()
        assert owned.connect("test-token") is client
    await owned.disconnect()
    await owned.disconnect()
    client.aclose.assert_awaited_once()


def test_missing_token_file_does_not_fall_back_to_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NOTEHUB_TOKEN", "env-token")
    with pytest.raises(ValueError, match="Could not read token file"):
        SessionController(TUIOptions(token_file=tmp_path / "absent")).token()


def test_filter_builder_preserves_structured_and_extra_values() -> None:
    query = build_query(
        {"deviceUID": "dev:one, dev:two", "files": "a.qo,b.qo"},
        start="2026-01-01T00:00:00Z",
        end="2026-01-02T00:00:00+00:00",
        date_type="captured",
        advanced='{"selectFields":"event,body"}',
    )
    assert query["deviceUID"] == ("dev:one", "dev:two")
    assert query["files"] == "a.qo,b.qo"
    assert query["selectFields"] == "event,body"
    start_seconds, end_seconds = query["startDate"], query["endDate"]
    assert isinstance(start_seconds, int) and not isinstance(start_seconds, bool)
    assert isinstance(end_seconds, int) and not isinstance(end_seconds, bool)
    assert end_seconds - start_seconds == 86400


@pytest.mark.parametrize(
    "advanced", ['{"cursor":"x"}', '{"sortBy":"captured"}', '{"deviceUID":"x"}', "[]", "{"]
)
def test_filter_builder_rejects_conflicting_or_invalid_advanced_input(advanced: str) -> None:
    with pytest.raises(ValueError):
        build_query({}, advanced=advanced)


@pytest.mark.parametrize("start,end", [("2026-01-01", ""), ("200", "100")])
def test_filter_builder_rejects_ambiguous_or_reversed_dates(start: str, end: str) -> None:
    with pytest.raises(ValueError):
        build_query({}, start=start, end=end)


def test_filter_removal_returns_a_new_validated_query() -> None:
    initial = Query().devices("dev:one", "dev:two").files("sensors.qo")

    updated = remove_filter(initial, "deviceUID")

    assert updated == Query().files("sensors.qo")
    assert updated is not initial
    assert initial["deviceUID"] == ("dev:one", "dev:two")


@pytest.mark.asyncio
async def test_filter_removal_updates_draft_and_apply_returns_composed_query() -> None:
    initial = Query().devices("dev:one").files("sensors.qo")
    result = []
    app = App()
    async with app.run_test() as pilot:
        screen = FilterScreen(initial)
        app.push_screen(screen, result.append)
        await pilot.pause()

        await pilot.click("#filter-remove-0")
        await pilot.pause()
        assert screen.query_one("#filter-devices", Input).value == ""
        assert screen.query_one("#filter-files", Input).value == "sensors.qo"
        screen.query_one(VerticalScroll).scroll_end(animate=False)
        await pilot.pause()
        await pilot.click("#filter-apply")
        await pilot.pause()

    assert result == [Query().files("sensors.qo")]
    assert result[0] is not initial
    assert initial["deviceUID"] == ("dev:one",)


@pytest.mark.asyncio
async def test_filter_removal_updates_advanced_json_draft() -> None:
    initial = Query.from_value({"selectFields": "event,body", "since": "cursor"})
    result = []
    app = App()
    async with app.run_test() as pilot:
        screen = FilterScreen(initial)
        app.push_screen(screen, result.append)
        await pilot.pause()

        await pilot.click("#filter-remove-0")
        await pilot.pause()
        assert json.loads(screen.query_one("#filter-advanced", TextArea).text) == {
            "since": "cursor"
        }
        screen.query_one(VerticalScroll).scroll_end(animate=False)
        await pilot.pause()
        await pilot.click("#filter-apply")
        await pilot.pause()

    assert result == [Query.from_value({"since": "cursor"})]
    assert initial["selectFields"] == "event,body"


@pytest.mark.asyncio
async def test_filter_cancel_keeps_initial_query() -> None:
    initial = Query().devices("dev:one")
    result = []
    app = App()
    async with app.run_test() as pilot:
        screen = FilterScreen(initial)
        app.push_screen(screen, result.append)
        await pilot.pause()
        assert screen.query_one("#filter-date-type", Select).value is Select.NULL
        await pilot.click("#filter-remove-0")
        await pilot.pause()
        screen.query_one("#filter-devices", Input).value = "changed"
        await pilot.press("escape")
        await pilot.pause()
    assert result == [None]
    assert initial["deviceUID"] == ("dev:one",)
