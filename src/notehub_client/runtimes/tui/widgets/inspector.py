"""Bounded parsed-record inspector with explicit body and record views."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Button, Static, TabbedContent, TabPane, Tree
from textual.widgets.tree import TreeNode

from ..presentation import json_text, record_label, safe_text, sanitize_record


@dataclass
class _Branch:
    value: Any
    offset: int = 0
    populated: bool = False
    more: bool = False


class RecordInspector(Widget):
    """Inspect a parsed record while bounding initial text and tree work."""

    DEFAULT_CSS = """
    RecordInspector { height: 1fr; min-height: 8; }
    RecordInspector TabbedContent { height: 1fr; }
    RecordInspector VerticalScroll { height: 1fr; }
    RecordInspector .inspector-text { height: auto; padding: 0 1; }
    RecordInspector Tree { height: 1fr; }
    RecordInspector Button { height: 3; }
    """

    def __init__(self, record: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.record = sanitize_record(record or {})

    @property
    def export_record(self) -> dict[str, Any]:
        """Return an independent sanitized parsed record for copy or export."""
        return deepcopy(self.record)

    def compose(self) -> ComposeResult:
        """Build independent summary, body, tree, and record views."""
        yield Static("Select a record", id="inspector-title", markup=False)
        with TabbedContent(id="inspector-tabs"):
            with TabPane("Summary", id="inspector-summary-tab"):
                with VerticalScroll():
                    yield Static(id="inspector-summary", classes="inspector-text", markup=False)
            with TabPane("Body", id="inspector-body-tab"):
                with VerticalScroll():
                    yield Static(id="inspector-body", classes="inspector-text", markup=False)
                    yield Button("Expand body", id="expand-body")
            with TabPane("Tree", id="inspector-tree-tab"):
                yield Tree("Record", id="inspector-tree")
            with TabPane("Record", id="inspector-record-tab"):
                with VerticalScroll():
                    yield Static(id="inspector-record", classes="inspector-text", markup=False)
                    yield Button("Expand record", id="expand-record")

    def on_mount(self) -> None:
        """Populate after child widgets are available."""
        self._update_record()

    def set_record(self, record: Mapping[str, Any]) -> None:
        """Replace displayed data without changing the active inspector tab."""
        self.record = sanitize_record(record)
        if not self.is_mounted:
            return
        self._update_record()

    def _update_record(self) -> None:
        self.query_one("#inspector-title", Static).update(safe_text(record_label(self.record)))
        metadata = {
            key: value
            for key, value in self.record.items()
            if key not in {"body", "payload", "environment"}
        }
        summary, _ = json_text(metadata)
        self.query_one("#inspector-summary", Static).update(summary)
        body = self.record.get("body")
        body_text, body_more = (
            json_text(body) if "body" in self.record else (safe_text("Body not reported"), False)
        )
        self.query_one("#inspector-body", Static).update(body_text)
        self.query_one("#expand-body", Button).display = body_more
        record_text, record_more = json_text(self.record)
        self.query_one("#inspector-record", Static).update(record_text)
        self.query_one("#expand-record", Button).display = record_more
        tree = self.query_one("#inspector-tree", Tree)
        tree.clear()
        tree.root.data = _Branch(self.record)
        self._populate(tree.root)
        tree.root.expand()

    def _populate(self, node: TreeNode) -> None:
        branch = node.data
        if not isinstance(branch, _Branch) or branch.populated:
            return
        branch.populated = True
        if isinstance(branch.value, Mapping):
            items = list(branch.value.items())
        elif isinstance(branch.value, list):
            items = list(enumerate(branch.value))
        else:
            return
        for key, value in items[branch.offset : branch.offset + 200]:
            expandable = isinstance(value, (Mapping, list)) and bool(value)
            label = f"{key}: {type(value).__name__}" if expandable else f"{key}: {value!r}"
            node.add(safe_text(label[:2048]), _Branch(value), allow_expand=expandable)
        if len(items) > branch.offset + 200:
            node.add(
                safe_text("Show next 200 items…"),
                _Branch(branch.value, branch.offset + 200, more=True),
            )

    @on(Tree.NodeExpanded)
    def expand_node(self, event: Tree.NodeExpanded) -> None:
        """Populate one level only when a branch is expanded."""
        self._populate(event.node)

    @on(Tree.NodeSelected)
    def select_node(self, event: Tree.NodeSelected) -> None:
        """Load the next bounded sibling slice when requested."""
        if isinstance(event.node.data, _Branch) and event.node.data.more:
            branch = event.node.data
            parent = event.node.parent
            if parent is not None:
                event.node.remove()
                parent.data = _Branch(branch.value, branch.offset)
                self._populate(parent)

    @on(Button.Pressed, "#expand-body")
    def expand_body(self) -> None:
        """Expand the explicitly requested body preview."""
        text, _ = json_text(self.record.get("body"), limit=None)
        self.query_one("#inspector-body", Static).update(text)
        self.query_one("#expand-body", Button).display = False

    @on(Button.Pressed, "#expand-record")
    def expand_record(self) -> None:
        """Expand the explicitly requested parsed record preview."""
        text, _ = json_text(self.record, limit=None)
        self.query_one("#inspector-record", Static).update(text)
        self.query_one("#expand-record", Button).display = False
