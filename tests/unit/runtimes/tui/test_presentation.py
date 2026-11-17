import json
from pathlib import Path

import pytest
from rich.pretty import pretty_repr
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Static, Tree

from notehub_client.runtimes.tui.presentation import json_text, safe_text, sanitize_record
from notehub_client.runtimes.tui.screens.export import ExportScreen
from notehub_client.runtimes.tui.state import PageResult
from notehub_client.runtimes.tui.widgets.inspector import RecordInspector


def test_page_result_rich_repr_shows_safe_page_diagnostics_only() -> None:
    result = PageResult(
        rows=({"event": "event-secret-id", "body": {"token": "payload-secret"}},),
        row_keys=("event-secret-id",),
        has_more=True,
        next_cursor="opaque-secret-cursor",
        page_num=2,
    )

    rendered = pretty_repr(result)

    assert "row_count=1" in rendered
    assert "has_more=True" in rendered
    assert "page_num=2" in rendered
    assert "next_cursor_available=True" in rendered
    assert "event-secret-id" not in rendered
    assert "payload-secret" not in rendered
    assert "opaque-secret-cursor" not in rendered


def test_literal_text_removes_terminal_sequences_without_parsing_markup() -> None:
    assert safe_text("[red]hello[/red]\x1b]52;c;secret\x07\x1b[31m!").plain == "[red]hello[/red]!"


def test_sanitization_preserves_input_and_masks_nested_environment_values() -> None:
    source = {"body": {"temperature": 21, "token": "private"}, "environment": {"KEY": "secret"}}
    safe = sanitize_record(source)
    assert safe == {
        "body": {"temperature": 21, "token": "[redacted]"},
        "environment": {"KEY": "[masked]"},
    }
    assert source["environment"]["KEY"] == "secret"


def test_json_preview_bounds_utf8_without_changing_input() -> None:
    text, truncated = json_text({"value": "界" * 1000}, limit=100)
    assert truncated
    assert "Preview limited" in text.plain
    assert "�" not in text.plain


class InspectorApp(App[None]):
    def compose(self) -> ComposeResult:
        yield RecordInspector({"event": "e:1", "body": None, "items": list(range(450))})


@pytest.mark.asyncio
async def test_inspector_preserves_tab_and_bounds_tree_expansion() -> None:
    app = InspectorApp()
    async with app.run_test(size=(100, 35)) as pilot:
        inspector = app.query_one(RecordInspector)
        tree = inspector.query_one(Tree)
        items = next(node for node in tree.root.children if str(node.label).startswith("items:"))
        items.expand()
        await pilot.pause()
        assert len(items.children) == 201
        assert "null" in str(inspector.query_one("#inspector-body", Static).render())
        inspector.set_record({"event": "e:2"})
        assert "Body not reported" in str(inspector.query_one("#inspector-body", Static).render())
        assert inspector.export_record == {"event": "e:2"}


@pytest.mark.asyncio
async def test_export_requires_explicit_replacement_and_masks_values(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    path.write_text("original", encoding="utf-8")
    app = App()
    async with app.run_test(size=(100, 35)) as pilot:
        modal = ExportScreen({"environment": {"KEY": "secret"}, "body": {"value": 12}})
        app.push_screen(modal)
        await pilot.pause()
        modal.query_one(Input).value = str(path)
        await pilot.pause()
        await modal.save()
        assert path.read_text(encoding="utf-8") == "original"
        assert not modal.query_one("#export-replace", Button).disabled
        await modal.replace()
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["environment"] == {"KEY": "[masked]"}
        assert saved["body"] == {"value": 12}
