"""Organization and legacy billing account reads outside project scope."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, DataTable, Select, Static

from ..presentation import record_label, safe_text

ACCOUNT_SECTIONS = ("organizations", "billing_accounts")


class AccountPanel(Vertical):
    """Browse account collections and lazily fetch selected details/history."""

    DEFAULT_CSS = """
    AccountPanel { height: 1fr; padding: 1; }
    AccountPanel #account-section { width: 40; }
    AccountPanel #account-status { height: 1; color: $text-muted; }
    AccountPanel #account-records { height: 1fr; }
    """

    def __init__(self, service: Any, **kwargs: Any) -> None:
        self.auto_load = bool(kwargs.pop("auto_load", True))
        self._active = self.auto_load
        super().__init__(**kwargs)
        self.service = service
        self.section = "organizations"
        self.uid: str | None = None
        self.detail = False
        self.rows: tuple[dict[str, Any], ...] = ()
        self._generation = 0

    def compose(self) -> ComposeResult:
        """Compose account selectors, detail actions, status and table."""
        yield Static("Account · independent of project", id="account-title")
        yield Select(
            [(x.replace("_", " ").title(), x) for x in ACCOUNT_SECTIONS],
            value="organizations",
            id="account-section",
        )
        yield Button("Balance history", id="account-history")
        yield Button("Back to accounts", id="account-back")
        yield Static("Choose an account section to read it.", id="account-status")
        yield DataTable(id="account-records", cursor_type="row", zebra_stripes=True)

    def render(self) -> Text:
        """Render a blank container background behind composed children."""
        return Text(" ")

    def on_mount(self) -> None:
        """Set table columns and load organizations independently of project."""
        self.query_one("#account-records", DataTable).add_columns(
            "Account", "UID", "Reported details"
        )
        if self.auto_load:
            self.load()

    def set_scope(self, project_uid: str | None) -> None:
        """Ignore project scope by design; accounts remain separately scoped."""
        del project_uid

    def refresh_data(self) -> None:
        """Refresh current account list or detail."""
        self._active = True
        self.load()

    def load(self) -> None:
        """Start a new account request generation."""
        self._generation += 1
        self._read(self.section, self.uid, self.detail, self._generation)

    @on(Select.Changed, "#account-section")
    def section_changed(self, event: Select.Changed) -> None:
        """Return to the selected account collection when switching type."""
        if event.value is Select.NULL:
            return
        self.section = str(event.value)
        self.uid = None
        self.detail = False
        if self._active:
            self.load()

    @on(DataTable.RowSelected, "#account-records")
    def select_account(self, event: DataTable.RowSelected) -> None:
        """Read details for an activated account row."""
        if self.detail:
            return
        row = next(
            (r for r in self.rows if str(r.get("uid", "")) == str(event.row_key.value)), None
        )
        if row and row.get("uid"):
            self.uid = str(row["uid"])
            self.detail = True
            self.load()

    def action_back_to_accounts(self) -> None:
        """Return from account details to its independent collection."""
        self.uid = None
        self.detail = False
        self.load()

    @on(Button.Pressed, "#account-history")
    def open_history(self) -> None:
        """Read balance history only after an account is selected."""
        if not self.uid:
            self.query_one("#account-status", Static).update("Select an account first.")
            return
        self.detail = True
        self.section = (
            "organization_history" if self.section == "organizations" else "billing_history"
        )
        self.load()

    @on(Button.Pressed, "#account-back")
    def back_button(self) -> None:
        """Return to account collection from its detail/history."""
        self.section = (
            "organizations" if self.section.startswith("organization") else "billing_accounts"
        )
        self.action_back_to_accounts()

    @work(exclusive=True, group="account", exit_on_error=False)
    async def _read(self, section: str, uid: str | None, detail: bool, generation: int) -> None:
        status = self.query_one("#account-status", Static)
        status.update("Reading account data…")
        try:
            if detail and uid:
                page = await self.service.read(section, uid=uid)
            else:
                page = await self.service.read(section)
        except Exception as error:
            if generation == self._generation:
                status.update(
                    safe_text(f"Account read unavailable ({type(error).__name__}); retry.")
                )
            return
        if generation != self._generation:
            return
        self.rows = page.rows
        self._render_data()

    def _render_data(self) -> None:
        table = self.query_one("#account-records", DataTable)
        table.clear()
        used: set[str] = set()
        for index, row in enumerate(self.rows):
            uid = str(row.get("uid", f"anonymous:{index}"))
            while uid in used:
                uid = f"{uid}#{index}"
            used.add(uid)
            table.add_row(
                safe_text(record_label(row)),
                safe_text(row.get("uid", "not reported")),
                safe_text(row.get("balance", row.get("status", "not reported"))),
                key=uid,
            )
        state = "details" if self.detail else "accounts"
        self.query_one("#account-back", Button).display = self.detail
        self.query_one("#account-status", Static).update(
            safe_text(
                f"{len(self.rows)} returned {self.section.replace('_', ' ')} {state}; source-reported values"
            )
        )


__all__ = ["ACCOUNT_SECTIONS", "AccountPanel"]
