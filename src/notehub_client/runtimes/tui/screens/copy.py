"""Selectable clipboard fallback without claiming clipboard delivery."""

from collections.abc import Callable

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, TextArea

from ..presentation import safe_string


class CopyScreen(ModalScreen[None]):
    """Offer selectable literal text and a best-effort terminal copy request."""

    DEFAULT_CSS = """
    CopyScreen { align: center middle; }
    CopyScreen > Vertical { width: 80%; height: 70%; padding: 1 2; background: $surface; border: round $accent; }
    CopyScreen TextArea { height: 1fr; }
    """
    BINDINGS = [("escape", "dismiss", "Back")]

    def __init__(
        self,
        value: str,
        title: str = "Copy value",
        *,
        feedback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self.value = value
        self.heading = title
        self.feedback = feedback

    def compose(self) -> ComposeResult:
        """Build the selectable fallback and clipboard controls."""
        with Vertical():
            yield Label(safe_string(self.heading), markup=False)
            yield TextArea(safe_string(self.value), read_only=True, id="copy-value")
            yield Label(
                "Select text here if your terminal blocks clipboard requests.", markup=False
            )
            yield Button("Request clipboard copy", id="copy-request")
            yield Button("Close", id="copy-close")

    @on(Button.Pressed, "#copy-request")
    def copy_value(self) -> None:
        """Request clipboard transfer through the terminal protocol."""
        self.app.copy_to_clipboard(self.value)
        message = "Copy requested; terminal permission may be required."
        if self.feedback is None:
            self.notify(message, markup=False)
        else:
            self.feedback(message)

    @on(Button.Pressed, "#copy-close")
    def close(self) -> None:
        """Dismiss the fallback screen."""
        self.dismiss(None)
