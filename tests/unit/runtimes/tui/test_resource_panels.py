"""Pilot tests for project and account resource panels."""

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Select, Static

from notehub_client.runtimes.tui.demo import DEMO_PROJECT_UID, DemoReadService
from notehub_client.runtimes.tui.screens.account import AccountPanel
from notehub_client.runtimes.tui.screens.operations import OperationsPanel
from notehub_client.runtimes.tui.screens.overview import OverviewPanel


class OverviewTestApp(App[None]):
    def compose(self) -> ComposeResult:
        yield OverviewPanel(DemoReadService(), DEMO_PROJECT_UID)


class OperationsTestApp(App[None]):
    def compose(self) -> ComposeResult:
        yield OperationsPanel(DemoReadService(), DEMO_PROJECT_UID)


class AccountTestApp(App[None]):
    def compose(self) -> ComposeResult:
        yield AccountPanel(DemoReadService())


async def test_overview_loads_only_project_and_one_event_page() -> None:
    app = OverviewTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        panel = app.query_one(OverviewPanel)
        assert panel.project["uid"] == DEMO_PROJECT_UID
        assert len(panel.events) == 50
        assert "one recent event page" in str(app.query_one("#overview-status", Static).render())


async def test_overview_clears_old_project_scope() -> None:
    app = OverviewTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        panel = app.query_one(OverviewPanel)
        panel.set_scope(None)
        await pilot.pause()
        assert panel.events == ()
        assert "Choose a project" in str(app.query_one("#overview-status", Static).render())


async def test_operations_load_selected_section_lazily() -> None:
    app = OperationsTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        panel = app.query_one(OperationsPanel)
        assert set(panel.results) == {"routes"}
        select = app.query_one("#operations-section", Select)
        select.value = "jobs"
        await pilot.pause()
        assert set(panel.results) == {"routes", "jobs"}
        assert panel.results["jobs"][0]["status"] == "completed"
        assert app.query_one("#operations-status", Static)


async def test_operations_scope_change_discards_old_records() -> None:
    app = OperationsTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        panel = app.query_one(OperationsPanel)
        panel.set_scope("app:demo-empty")
        await pilot.pause()
        assert panel.results == {"routes": ()}
        assert "0 returned" in str(app.query_one("#operations-status", Static).render())


async def test_account_is_project_independent_and_detail_is_lazy() -> None:
    app = AccountTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        panel = app.query_one(AccountPanel)
        assert panel.rows[0]["uid"] == "org:demo"
        panel.set_scope("app:unrelated")
        assert panel.rows[0]["uid"] == "org:demo"
        await pilot.click("#account-records")
        table = app.query_one("#account-records", DataTable)
        table.move_cursor(row=0)
        await pilot.press("enter")
        await pilot.pause()
        assert panel.detail is True
        assert panel.uid == "org:demo"
        panel.action_back_to_accounts()
        await pilot.pause()
        assert panel.detail is False
        assert panel.uid is None
