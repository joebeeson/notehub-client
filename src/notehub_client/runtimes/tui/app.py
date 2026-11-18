"""Textual workspace for bounded, contextual Notehub exploration."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from textual import on, work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    ContentSwitcher,
    DataTable,
    Footer,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TextArea,
)
from textual.worker import NoActiveWorker, get_current_worker

from ...errors import (
    NotehubAPIError,
    NotehubAuthenticationError,
    NotehubError,
    NotehubPermissionError,
    NotehubRateLimitError,
    NotehubResponseError,
)
from ...filters import Query
from ...simulate import (
    Simulation,
)
from ...simulate import (
    available as available_scenarios,
)
from ...simulate import (
    named as named_scenario,
)
from .demo import DemoReadService
from .notifications import NotificationCenter, NotificationInboxScreen, notify_safe
from .paging import CursorHistory
from .presentation import record_label, safe_text
from .screens.account import AccountPanel
from .screens.copy import CopyScreen
from .screens.devices import DeviceDetailView, DeviceListView
from .screens.export import ExportScreen
from .screens.filters import FilterScreen
from .screens.fleets import FleetDetailView, FleetListView
from .screens.operations import OperationsPanel
from .screens.overview import OverviewPanel
from .screens.simulation import SimulationPanel
from .service import ReadService, SimulationProjectService, TUIReadService
from .session import SessionController
from .state import PageResult, TUIOptions, ViewId, ViewState
from .widgets.inspector import RecordInspector
from .widgets.signals import SignalKind, SignalSettingsScreen, SignalStrip
from .widgets.status import RequestActivity

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ...client import NotehubClient


class TextDialog(ModalScreen[None]):
    """A keyboard-reachable information dialog."""

    BINDINGS = [("escape", "dismiss", "Back")]

    def __init__(self, title: str, text: str) -> None:
        super().__init__()
        self.title_text, self.body_text = title, text

    def compose(self) -> ComposeResult:
        """Compose the dialog's readable message and close action."""
        with Vertical(classes="dialog"):
            yield Label(self.title_text)
            yield TextArea(self.body_text, read_only=True)
            yield Button("Close", id="close-dialog")

    @on(Button.Pressed, "#close-dialog")
    def close_dialog(self) -> None:
        """Return to the originating view."""
        self.dismiss(None)


class _WorkspaceScreen(Screen):
    """Expose native Textual breakpoints to the workbench styles."""

    HORIZONTAL_BREAKPOINTS = [
        (120, "wide"),
        (90, "roomy"),
        (80, "compact"),
        (0, "narrow"),
    ]
    VERTICAL_BREAKPOINTS = [(30, "tall"), (24, "minimum"), (0, "short")]


class NotehubApp(App[None]):
    """Own the workspace state and async request lifetimes."""

    TITLE = "Notehub workbench"
    CSS_PATH = "styles.tcss"
    SIMULATION_PROJECT_PREFIX = "__simulation__:"
    BINDINGS = [
        Binding("1", "navigate('overview')", "Overview"),
        Binding("2", "navigate('events')", "Events"),
        Binding("3", "navigate('devices')", "Devices"),
        Binding("4", "navigate('fleets')", "Fleets"),
        Binding("5", "navigate('operations')", "Ops"),
        Binding("6", "navigate('simulation')", "Sim"),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("f", "filters", "Filters", show=False),
        Binding("d", "device", "Device", show=False),
        Binding("/", "search", "Search page", show=False),
        Binding("escape", "back", "Back", show=False),
        Binding("?", "help", "Help"),
        Binding("q", "quit", "Quit", show=False),
    ]

    def __init__(
        self, *, client: NotehubClient | None = None, options: TUIOptions | None = None
    ) -> None:
        super().__init__()
        self.options = options or TUIOptions()
        self.activity = RequestActivity()
        self.session = SessionController(self.options, client=client, observer=self.activity)
        self.service: ReadService | None = None
        self.live_service: ReadService | None = None
        self.simulation_project: SimulationProjectService | None = None
        self.project_uid = self.options.project_uid
        self.live_projects: list[tuple[str, str]] = []
        self._project_option_value: str | None = None
        self.view = ViewId.OVERVIEW
        self.operation = "overview"
        self.uid: str | None = None
        self.states: dict[tuple[str, str | None], ViewState] = {}
        self.history: deque[tuple[ViewId, str, str | None]] = deque(maxlen=30)
        self.device_records: dict[tuple[str | None, str], dict[str, Any]] = {}
        self.fleet_records: dict[tuple[str | None, str], dict[str, Any]] = {}
        self.detail_results: dict[tuple[str | None, ViewId, str, str], PageResult] = {}
        self.generation = 0
        self.result = PageResult()
        self.loading = False
        self._restoring = False
        self._cursor_histories: dict[
            tuple[str | None, ViewId, str, str | None, Query], CursorHistory
        ] = {}
        self.notifications = NotificationCenter()
        self.signal_selection: tuple[SignalKind, ...] = (
            SignalKind.REQUEST_DURATION,
            SignalKind.RECEIPT_DELAY,
        )
        self.toasts_enabled = True
        self._panels_ready = False
        self.signals_visible = False

    def compose(self) -> ComposeResult:
        """Build the persistent navigation shell and active workspace."""
        yield Static("NOTEHUB / DEMO" if self.options.demo else "NOTEHUB", id="brand")
        with Horizontal(id="scope-bar"):
            yield Select([], prompt="Choose project", id="project")
            yield Button("Signals", id="signals")
            yield Button("Settings", id="signals-settings")
            yield Button("Inbox", id="inbox")
            yield Button("Disconnect", id="disconnect")
            yield Button("Toasts: On", id="toasts")
        with Horizontal(id="login"):
            yield Input(placeholder="Notehub token (session only)", password=True, id="token")
            yield Button("Connect", id="connect", variant="primary")
        with Horizontal(id="nav"):
            for view in ViewId:
                yield Button(view.value.title(), id=f"nav-{view.value}")
        yield SignalStrip(self.activity, id="signals-strip", selected=self.signal_selection)
        yield Static("Starting session…", id="status")
        with Horizontal(id="resize-notice"):
            yield Label("Resize terminal to at least 80 × 24", id="resize-message")
            yield Button("Help", id="resize-help")
            yield Button("Quit", id="resize-quit")
        with Horizontal(id="tools"):
            yield Input(placeholder="Search current page", id="search")
            yield Button("Filters", id="filters")
            yield Button("Refresh", id="refresh")
        with Horizontal(id="sections"):
            yield Select([], prompt="Section", id="section")
            yield Button("Related events", id="related-events")
        yield Static("", id="query-summary")
        with ContentSwitcher(initial="records-view", id="view-host", classes="workspace"):
            with Horizontal(id="records-view"):
                yield DataTable(id="records", cursor_type="row", zebra_stripes=True)
                yield RecordInspector(id="inspector")
        with Horizontal(id="paging"):
            yield Button("Previous", id="previous")
            yield Static("", id="page-info")
            yield Button("Next", id="next")
            yield Button("Copy UID", id="copy")
            yield Button("Export record", id="export")
            yield Button("Export page", id="export-page")
        yield Footer()

    async def on_mount(self) -> None:
        """Resolve credentials and begin the bounded project read."""
        await self._install_simulation_panel()
        try:
            if self.options.demo:
                self.service = DemoReadService()
                self.live_service = self.service
            elif self.session.client is not None or self.session.token():
                self.service = TUIReadService(self.session.connect())
                self.live_service = self.service
            else:
                self._set_project_options([])
                self.query_one("#status", Static).update(
                    "Connect to Notehub or choose a local Simulation project."
                )
                self.query_one("#project", Select).focus()
                return
            self.query_one("#login").display = False
            await self._install_panels()
            self.load_projects()
        except (OSError, ValueError, NotehubError):
            self.query_one("#status", Static).update(
                "Unable to open session. Check token source and reconnect."
            )

    async def _install_simulation_panel(self) -> None:
        """Mount the local-only simulation lab even before API authentication."""
        host = self.query_one("#view-host", ContentSwitcher)
        await host.mount(SimulationPanel(id="simulation-view"))

    def get_default_screen(self) -> Screen:
        """Install the responsive workspace screen as Textual's default."""
        return _WorkspaceScreen(id="_default")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Keep ordinary shortcut letters available to text editors."""
        # Textual's override signature includes arguments; this policy uses only focus/action.
        del parameters
        if isinstance(self.focused, (Input, TextArea)) and action in {
            "navigate",
            "refresh",
            "filters",
            "device",
            "search",
            "help",
            "quit",
        }:
            return False
        return True

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Expose every destination through Textual's native palette."""
        yield from super().get_system_commands(screen)
        for view in ViewId:
            yield SystemCommand(
                f"Go to {view.value.title()}",
                "Open workspace",
                lambda v=view: self.action_navigate(v.value),
            )
        yield SystemCommand(
            "Switch project", "Focus the project picker", lambda: self.query_one("#project").focus()
        )
        yield SystemCommand("Refresh view", "Read the current scope", self.action_refresh)
        yield SystemCommand("Signals", "Toggle session instrumentation", self.action_signals)
        yield SystemCommand("Notifications", "Open session inbox", self.action_inbox)
        yield SystemCommand("Help", "Keyboard guide", self.action_help)

    @work(exclusive=True, group="projects", exit_on_error=False)
    async def load_projects(self) -> None:
        """Load a page of accessible projects without borrowing another runtime."""
        if self.live_service is None:
            self._set_project_options([])
            return
        generation = self.generation
        try:
            page = await self.live_service.read("projects")
            if generation != self.generation:
                return
            options = [(record_label(row), str(row["uid"])) for row in page.rows if row.get("uid")]
            self.live_projects = options
            self._set_project_options(options)
            picker = self.query_one("#project", Select)
            if self.simulation_project is not None:
                selected = self.SIMULATION_PROJECT_PREFIX + self.simulation_project.scenario_name
                picker.value = selected
                self._project_option_value = selected
                return
            if self.project_uid:
                if self.project_uid not in {uid for _, uid in options}:
                    options.append((self.project_uid, self.project_uid))
                    self._set_project_options(options)
                picker.value = self.project_uid
                self._project_option_value = self.project_uid
            else:
                self.query_one("#status", Static).update("Choose a project to explore.")
                picker.focus()
        except NotehubError as error:
            await self._failure(error)

    def _simulation_options(self) -> list[tuple[str, str]]:
        """Represent each packaged scenario as a selectable local project."""
        return [
            (
                f"Simulation · {named_scenario(name).projects[0].label or name}",
                f"{self.SIMULATION_PROJECT_PREFIX}{name}",
            )
            for name in available_scenarios()
        ]

    def _set_project_options(self, live_options: list[tuple[str, str]]) -> None:
        """Keep local scenarios available beside the current remote project list."""
        picker = self.query_one("#project", Select)
        picker.set_options([*live_options, *self._simulation_options()])

    async def _activate_simulation_project(
        self, scenario_name: str, simulation: Simulation | None = None
    ) -> None:
        """Swap the active reader to a local scenario without closing the live session."""
        await self._cancel_view_work()
        panel = self.query_one(SimulationPanel)
        if self._panels_ready:
            await self._remove_panels()
        if self.simulation_project is not None:
            await self.simulation_project.close()
            self.simulation_project = None
        simulation = simulation or panel.start_scenario(scenario_name)
        project = await SimulationProjectService.open(
            simulation, scenario_name, observer=self.activity
        )
        panel.set_project_active(True)
        self.simulation_project = project
        self.service = project
        self.project_uid = project.project_uid
        self.generation += 1
        self.states.clear()
        self._cursor_histories.clear()
        self.device_records.clear()
        self.fleet_records.clear()
        self.detail_results.clear()
        self.history.clear()
        self.result = PageResult()
        self.uid = None
        self.view = ViewId.OVERVIEW
        self.operation = "overview"
        self._set_project_options(self.live_projects)
        option = f"{self.SIMULATION_PROJECT_PREFIX}{scenario_name}"
        self.query_one("#project", Select).value = option
        self._project_option_value = option
        await self._install_panels()
        self._configure_sections()
        self._restore_or_load()

    @on(SimulationPanel.ScenarioStarted)
    async def simulation_scenario_started(self, message: SimulationPanel.ScenarioStarted) -> None:
        """Keep the selected simulated project attached to the panel's new run."""
        if self.simulation_project is not None:
            await self._activate_simulation_project(message.scenario_name, message.simulation)

    @on(Select.Changed, "#project")
    async def project_changed(self, event: Select.Changed) -> None:
        """Invalidate old scope before starting a new project read."""
        if event.value is Select.NULL:
            return
        selected = str(event.value)
        if selected == self._project_option_value:
            return
        self._project_option_value = selected
        if self.simulation_project is not None and not selected.startswith(
            self.SIMULATION_PROJECT_PREFIX
        ):
            await self._cancel_view_work()
        if selected.startswith(self.SIMULATION_PROJECT_PREFIX):
            scenario_name = selected.removeprefix(self.SIMULATION_PROJECT_PREFIX)
            if scenario_name in available_scenarios():
                await self._activate_simulation_project(scenario_name)
            return
        self.generation += 1
        self.project_uid = selected
        self.states = {k: v for k, v in self.states.items() if k[0].startswith("account:")}
        self._cursor_histories.clear()
        self.device_records.clear()
        self.fleet_records.clear()
        self.detail_results.clear()
        self.history.clear()
        self.result = PageResult()
        if self.simulation_project is not None:
            if self._panels_ready:
                await self._remove_panels()
            await self.simulation_project.close()
            self.simulation_project = None
            panel = self.query_one(SimulationPanel)
            panel.set_project_active(False)
            panel.start_scenario(panel.scenario_name)
            self.service = self.live_service
            if self.service is not None:
                await self._install_panels()
        self.action_navigate("overview")

    def _key(self) -> tuple[str, str | None]:
        return (
            f"account:{self.operation}" if self.view == ViewId.ACCOUNT else self.operation,
            self.uid,
        )

    async def _cancel_view_work(self) -> None:
        """Invalidate and await the current app-owned read before swapping services."""
        self.generation += 1
        self.loading = False
        workers = [
            worker for worker in self.workers if worker.node is self and worker.group == "view"
        ]
        await self._cancel_and_wait(workers)

    async def _cancel_and_wait(self, workers: list[Any]) -> None:
        """Cancel and drain app workers without awaiting the calling worker itself."""
        try:
            current = get_current_worker()
        except NoActiveWorker:
            current = None
        pending = [worker for worker in workers if worker is not current]
        for worker in pending:
            worker.cancel()
        if pending:
            await asyncio.gather(*(worker.wait() for worker in pending), return_exceptions=True)

    def _uses_cursor_paging(self) -> bool:
        """Return whether the active read follows an event cursor."""
        return self.operation in {"events", "overview", "fleet_events"}

    def _cursor_history_key(self) -> tuple[str | None, ViewId, str, str | None, Query]:
        """Scope event page history to project, location, and immutable query."""
        return self.project_uid, self.view, self.operation, self.uid, self.current_state.query

    def _cursor_history(self) -> CursorHistory:
        """Return the bounded pager for the active location and query."""
        return self._cursor_histories.setdefault(self._cursor_history_key(), CursorHistory())

    def _discard_other_cursor_queries(self) -> None:
        """Drop unreachable query histories at the active project location."""
        current_key = self._cursor_history_key()
        location = current_key[:4]
        for key in tuple(self._cursor_histories):
            if key[:4] == location and key != current_key:
                del self._cursor_histories[key]

    async def _install_panels(self) -> None:
        """Mount the resource workspaces once a read service is available."""
        if self._panels_ready or self.service is None:
            return
        host = self.query_one("#view-host", ContentSwitcher)
        await host.mount(
            OverviewPanel(
                self.service, self.project_uid, self._panel_navigation, id="overview-view"
            ),
            DeviceListView(PageResult(), id="devices-view"),
            DeviceDetailView({"uid": ""}, id="device-detail-view"),
            FleetListView(PageResult(), id="fleets-view"),
            FleetDetailView({"uid": "", "label": ""}, id="fleet-detail-view"),
            OperationsPanel(self.service, self.project_uid, auto_load=False, id="operations-view"),
            AccountPanel(self.service, auto_load=False, id="account-view"),
        )
        self._panels_ready = True
        self._sync_view_host()

    async def _remove_panels(self) -> None:
        """Unmount service-bound panels before the session client is closed."""
        if not self._panels_ready:
            return
        host = self.query_one("#view-host", ContentSwitcher)
        host.current = "records-view"
        for panel_type in (
            OverviewPanel,
            OperationsPanel,
            AccountPanel,
            DeviceListView,
            DeviceDetailView,
            FleetListView,
            FleetDetailView,
        ):
            panel = self.query_one(panel_type)
            await panel.remove()
        self._panels_ready = False

    def _sync_view_host(self) -> None:
        """Show the composed screen for the active destination."""
        if self.view == ViewId.SIMULATION:
            self.query_one("#view-host", ContentSwitcher).current = "simulation-view"
            return
        if not self._panels_ready:
            return
        view_id = {
            ViewId.OVERVIEW: "overview-view",
            ViewId.DEVICES: "device-detail-view" if self.uid else "devices-view",
            ViewId.FLEETS: "fleet-detail-view" if self.uid else "fleets-view",
            ViewId.OPERATIONS: "operations-view",
            ViewId.ACCOUNT: "account-view",
            ViewId.EVENTS: "records-view",
            ViewId.SIMULATION: "simulation-view",
        }[self.view]
        self.query_one("#view-host", ContentSwitcher).current = view_id
        detail_active = bool(self.uid and self.view in {ViewId.DEVICES, ViewId.FLEETS})
        tools = self.query("#tools")
        paging = self.query("#paging")
        if tools:
            tools.first().display = not detail_active
        if paging:
            paging.first().display = not detail_active

    def _sync_panels(self) -> None:
        """Update project scopes and the latest bounded page in mounted views."""
        if not self._panels_ready:
            return
        self.query_one(OverviewPanel).set_scope(self.project_uid)
        self.query_one(OperationsPanel).set_scope(self.project_uid)
        self.query_one(AccountPanel).set_scope(self.project_uid)
        self.query_one(DeviceListView).set_result(
            self.result if self.view == ViewId.DEVICES else PageResult()
        )
        self.query_one(FleetListView).set_result(
            self.result if self.view == ViewId.FLEETS else PageResult()
        )

    def _panel_navigation(self, target: str, _payload: dict[str, Any]) -> None:
        """Route overview actions through the same workspace navigation."""
        if target in {item.value for item in ViewId}:
            self.action_navigate(target)

    @on(DeviceListView.Selected)
    def device_selected(self, message: DeviceListView.Selected) -> None:
        """Open dedicated device details from the stable-key device list."""
        self._save_selection()
        self.history.append((self.view, self.operation, self.uid))
        uid = str(message.device.get("uid"))
        self.device_records[(self.project_uid, uid)] = dict(message.device)
        self.uid = uid
        self.view = ViewId.DEVICES
        self.operation = "device"
        self._configure_sections()
        self._sync_view_host()
        detail = self.query_one(DeviceDetailView)
        detail.query_one(TabbedContent).active = "device-overview"
        detail.set_device(message.device)
        self._restore_or_load()

    @on(FleetListView.Selected)
    def fleet_selected(self, message: FleetListView.Selected) -> None:
        """Open dedicated fleet details from the stable-key fleet list."""
        self._save_selection()
        self.history.append((self.view, self.operation, self.uid))
        uid = str(message.fleet.get("uid"))
        self.fleet_records[(self.project_uid, uid)] = dict(message.fleet)
        self.uid = uid
        self.view = ViewId.FLEETS
        self.operation = "fleets"
        self._configure_sections()
        self._sync_view_host()
        detail = self.query_one(FleetDetailView)
        detail.query_one(TabbedContent).active = "fleet-overview"
        detail.set_fleet(message.fleet)
        self._restore_or_load()

    @property
    def current_state(self) -> ViewState:
        """Return immutable state for the active location."""
        return self.states.get(self._key(), ViewState())

    def _save_selection(self) -> None:
        table = self.query_one("#records", DataTable)
        selected = None
        if table.row_count and table.cursor_row < table.row_count:
            selected = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        self.states[self._key()] = replace(
            self.current_state, selected_key=selected, scroll_y=table.scroll_y
        )

    def action_navigate(self, view: str) -> None:
        """Open a primary workspace with its last-good state."""
        self._save_selection()
        self.view = ViewId(view)
        self.uid = None
        self.operation = {
            ViewId.OVERVIEW: "overview",
            ViewId.EVENTS: "events",
            ViewId.DEVICES: "devices",
            ViewId.FLEETS: "fleets",
            ViewId.OPERATIONS: "routes",
            ViewId.ACCOUNT: "organizations",
            ViewId.SIMULATION: "simulation",
        }[self.view]
        self._configure_sections()
        self._sync_view_host()
        self._restore_or_load()

    def _configure_sections(self) -> None:
        self._restoring = True
        # Operations, Account, Device, and Fleet panels own their section tabs.
        # The shell selector remains for account detail only when routed there.
        sections: list[tuple[str, str]] = []
        if self.uid and self.view == ViewId.ACCOUNT:
            prefix = "billing" if self.operation.startswith("billing") else "organization"
            sections = [
                ("Details", "billing_account" if prefix == "billing" else "organization"),
                ("Balance history", f"{prefix}_history"),
            ]
        # A scope switch can run while Textual is replacing the active screen.
        # Keep routing safe if the shell controls are not mounted yet.
        try:
            select = self.query_one("#section", Select)
            sections_group = self.query_one("#sections")
        except NoMatches:
            self._restoring = False
            return
        try:
            related_button = self.query_one("#related-events", Button)
        except NoMatches:
            related_button = None
        if sections:
            select.set_options(sections)
            select.value = self.operation
        select.display = bool(sections)
        sections_group.display = bool(sections) or bool(
            self.uid and self.view in {ViewId.DEVICES, ViewId.FLEETS}
        )
        if related_button is not None:
            related_button.display = bool(self.uid and self.view in {ViewId.DEVICES, ViewId.FLEETS})
        self._restoring = False

    @on(Select.Changed, "#section")
    def section_changed(self, event: Select.Changed) -> None:
        """Load detail tabs lazily."""
        if self._restoring or event.value is Select.NULL or str(event.value) == self.operation:
            return
        self._save_selection()
        self.operation = str(event.value)
        self._restore_or_load()

    def _apply_device_detail_cache(self, uid: str) -> None:
        detail = self.query_one(DeviceDetailView)
        for section in ("latest", "sessions", "environment", "events"):
            page = self.detail_results.get((self.project_uid, ViewId.DEVICES, uid, section))
            detail.set_section_result(section, page)

    def _apply_fleet_detail_cache(self, uid: str) -> None:
        detail = self.query_one(FleetDetailView)
        page = self.detail_results.get((self.project_uid, ViewId.FLEETS, uid, "devices"))
        detail.set_section_result("devices", page)
        self._render_fleet_events(uid)

    def _fleet_event_history_key(self, uid: str) -> tuple[str | None, ViewId, str, str, Query]:
        query = self.states.get(("events", uid), ViewState()).query
        return self.project_uid, ViewId.FLEETS, "events", uid, query

    def _render_fleet_events(self, uid: str) -> None:
        pager = self._cursor_histories.setdefault(
            self._fleet_event_history_key(uid), CursorHistory()
        )
        detail = self.query_one(FleetDetailView)
        detail.set_section_result("events", pager.current)
        detail.set_event_navigation(previous=pager.can_previous, following=pager.can_next)

    def _request_detail_section(
        self,
        view: ViewId,
        uid: str,
        section: str,
        *,
        refresh: bool = False,
        page_num: int | None = None,
        cursor: str | None = None,
    ) -> None:
        """Serve a cached detail page or schedule one app-owned read."""
        self.operation = section
        self.generation += 1
        self.workers.cancel_group(self, "view")
        cache_key = (self.project_uid, view, uid, section)
        if view == ViewId.FLEETS and section == "events":
            pager = self._cursor_histories.get(self._fleet_event_history_key(uid))
            if pager is not None and pager.current is not None and not refresh and cursor is None:
                self._render_fleet_events(uid)
                return
            if pager is None:
                self._render_fleet_events(uid)
            self._read_detail_section(view, uid, section, self.generation, 1, cursor or "0")
            return
        if view == ViewId.DEVICES and section == "device":
            cached_record = self.device_records.get((self.project_uid, uid))
            if cached_record is not None and not refresh:
                self.query_one(DeviceDetailView).set_device(cached_record)
                return
        else:
            cached_page = self.detail_results.get(cache_key)
            if cached_page is not None and not refresh and page_num is None:
                if view == ViewId.DEVICES:
                    self.query_one(DeviceDetailView).set_section_result(section, cached_page)
                else:
                    self.query_one(FleetDetailView).set_section_result(section, cached_page)
                self._status(
                    f"Cached {section} details · checked {cached_page.checked_at:%H:%M:%S} UTC"
                )
                return
            if page_num is None and cached_page is not None:
                page_num = cached_page.page_num

        self._read_detail_section(view, uid, section, self.generation, page_num or 1)

    @work(exclusive=True, group="view", exit_on_error=False)
    async def _read_detail_section(
        self,
        view: ViewId,
        uid: str,
        section: str,
        generation: int,
        page_num: int,
        cursor: str = "0",
    ) -> None:
        """Read one detail section and apply it only to its original scope."""
        service = self.service
        project_uid = self.project_uid
        if service is None:
            self._status("Connect to Notehub or choose a local Simulation project first.")
            return
        operation = section
        query = Query()
        event_key = self._fleet_event_history_key(uid)
        if view == ViewId.FLEETS and section == "events":
            query = event_key[-1]
        if view == ViewId.DEVICES and section == "events":
            query = query.devices(uid)
        elif view == ViewId.FLEETS:
            operation = {"devices": "fleet_devices", "events": "fleet_events"}.get(section, section)
        self._status(f"Reading {section} details…")
        try:
            page = await service.read(
                operation,
                project_uid=project_uid,
                uid=uid,
                query=query,
                page_num=page_num,
                cursor=cursor,
            )
        except asyncio.CancelledError:
            raise
        except NotehubError as error:
            if generation == self.generation and service is self.service:
                await self._failure(error)
            return
        except Exception as error:
            if generation == self.generation and service is self.service:
                self._status(f"{section.title()} unavailable ({type(error).__name__}); retry.")
            return
        if (
            generation != self.generation
            or project_uid != self.project_uid
            or service is not self.service
            or self.view != view
            or self.uid != uid
        ):
            return
        if view == ViewId.DEVICES and section == "device":
            record = page.rows[0] if page.rows else {"uid": uid}
            self.device_records[(project_uid, uid)] = dict(record)
            self.query_one(DeviceDetailView).set_device(dict(record))
            self._status("Device details checked")
            return
        if view == ViewId.FLEETS and section == "events":
            pager = (
                CursorHistory()
                if cursor == "0"
                else self._cursor_histories.setdefault(event_key, CursorHistory())
            )
            try:
                pager.append(cursor, page)
            except NotehubResponseError:
                self._status("Cursor unavailable or repeated. Refresh with r to restart.")
                return
            self._cursor_histories[event_key] = pager
            self._render_fleet_events(uid)
            self._status(f"Events details checked · {len(page.rows)} returned")
            return
        self.detail_results[(project_uid, view, uid, section)] = page
        if view == ViewId.DEVICES:
            self.query_one(DeviceDetailView).set_section_result(section, page)
        else:
            self.query_one(FleetDetailView).set_section_result(section, page)
        self._status(f"{section.title()} details checked · {len(page.rows)} returned")

    @on(DeviceDetailView.SectionSelected)
    def device_detail_section_selected(self, message: DeviceDetailView.SectionSelected) -> None:
        """Load a device tab through the app-owned service and worker."""
        if self.view == ViewId.DEVICES and message.device_uid == self.uid:
            self._request_detail_section(ViewId.DEVICES, message.device_uid, message.section)

    @on(DeviceDetailView.SessionPageRequested)
    def device_session_page_requested(self, message: DeviceDetailView.SessionPageRequested) -> None:
        """Navigate from the last successful page in this device's Sessions tab."""
        uid = message.device_uid
        if self.view != ViewId.DEVICES or self.uid != uid:
            return
        current = self.detail_results.get((self.project_uid, ViewId.DEVICES, uid, "sessions"))
        if current is None or current.page_num is None:
            return
        if message.forward and current.has_more is not True:
            return
        target = current.page_num + (1 if message.forward else -1)
        if target >= 1:
            self._request_detail_section(ViewId.DEVICES, uid, "sessions", page_num=target)

    @on(FleetDetailView.SectionSelected)
    def fleet_detail_section_selected(self, message: FleetDetailView.SectionSelected) -> None:
        """Load a fleet tab through the app-owned service and worker."""
        if self.view == ViewId.FLEETS and message.fleet_uid == self.uid:
            self._request_detail_section(ViewId.FLEETS, message.fleet_uid, message.section)

    @on(FleetDetailView.DevicePageRequested)
    def fleet_device_page_requested(self, message: FleetDetailView.DevicePageRequested) -> None:
        """Navigate from this fleet's last successful member-device page."""
        uid = message.fleet_uid
        if self.view != ViewId.FLEETS or self.uid != uid:
            return
        current = self.detail_results.get((self.project_uid, ViewId.FLEETS, uid, "devices"))
        if current is None or current.page_num is None:
            return
        if message.forward and current.has_more is not True:
            return
        target = current.page_num + (1 if message.forward else -1)
        if target >= 1:
            self._request_detail_section(ViewId.FLEETS, uid, "devices", page_num=target)

    @on(FleetDetailView.EventPageRequested)
    def fleet_event_page_requested(self, message: FleetDetailView.EventPageRequested) -> None:
        """Use retained pages before fetching a new fleet event cursor."""
        uid = message.fleet_uid
        if self.view != ViewId.FLEETS or self.uid != uid:
            return
        pager = self._cursor_histories.get(self._fleet_event_history_key(uid))
        if pager is None:
            return
        if not (pager.can_next if message.forward else pager.can_previous):
            return
        self.generation += 1
        self.workers.cancel_group(self, "view")
        page = pager.forward() if message.forward else pager.previous()
        if page is not None:
            self._render_fleet_events(uid)
            self._status("Cached fleet events")
        else:
            self._request_detail_section(ViewId.FLEETS, uid, "events", cursor=pager.next_cursor)

    def _restore_or_load(self) -> None:
        self.workers.cancel_group(self, "view")
        self.loading = False
        self.generation += 1
        try:
            self.query_one("#search", Input).value = ""
        except NoMatches:
            # Panel transitions can temporarily replace the workspace DOM.
            pass
        state = self.current_state
        self.result = state.result or PageResult()
        self._render_rows()
        if self.view == ViewId.SIMULATION:
            self.query_one(SimulationPanel).refresh_data()
        elif self.view == ViewId.OVERVIEW and self._panels_ready:
            self.query_one(OverviewPanel).set_scope(self.project_uid)
        elif self.view == ViewId.OPERATIONS and self._panels_ready:
            panel = self.query_one(OperationsPanel)
            panel.set_scope(self.project_uid)
            panel.activate()
        elif self.view == ViewId.ACCOUNT and self._panels_ready:
            self.query_one(AccountPanel).refresh_data()
        elif self.view == ViewId.DEVICES and self.uid and self._panels_ready:
            self._sync_view_host()
            detail = self.query_one(DeviceDetailView)
            key = (self.project_uid, self.uid)
            detail.set_device(self.device_records.get(key, {"uid": self.uid}))
            self._apply_device_detail_cache(self.uid)
            if key not in self.device_records:
                self._request_detail_section(ViewId.DEVICES, self.uid, "device")
        elif self.view == ViewId.FLEETS and self.uid and self._panels_ready:
            self._sync_view_host()
            detail = self.query_one(FleetDetailView)
            detail.set_fleet(
                self.fleet_records.get((self.project_uid, self.uid), {"uid": self.uid})
            )
            self._apply_fleet_detail_cache(self.uid)
        elif self.view == ViewId.DEVICES and self.operation == "devices" and self._panels_ready:
            self._sync_view_host()
            self.query_one(DeviceListView).set_result(self.result)
            if state.result is None:
                self.fetch()
        elif self.view == ViewId.FLEETS and self.operation == "fleets" and self._panels_ready:
            self._sync_view_host()
            self.query_one(FleetListView).set_result(self.result)
            if state.result is None:
                self.fetch()
        elif state.result is None:
            self.fetch()
        else:
            self._status(f"Cached read · checked {state.result.checked_at:%H:%M:%S} UTC")

    def _status(self, text: str) -> None:
        scope = (
            "Simulation project"
            if self.simulation_project is not None
            else "Local simulation"
            if self.view == ViewId.SIMULATION
            else "Account"
            if self.view == ViewId.ACCOUNT
            else self.project_uid or "No project"
        )
        self.query_one("#status", Static).update(safe_text(f"{scope} / {self.operation} · {text}"))

    @work(exclusive=True, group="view", exit_on_error=False)
    async def fetch(self, *, cursor: str | None = None) -> None:
        """Apply a read only if its location generation is still current."""
        if self.service is None or (not self.project_uid and self.view != ViewId.ACCOUNT):
            self._status("Choose a project or connect first")
            return
        generation = self.generation
        state = self.current_state
        request_cursor = cursor if cursor is not None else state.cursor
        self.loading = True
        self._status("Reading… previous data may be stale")
        try:
            operation = "events" if self.operation == "overview" else self.operation
            query = state.query
            if self.view == ViewId.DEVICES and self.uid and self.operation == "events":
                query = query.devices(self.uid)
            page = await self.service.read(
                operation,
                project_uid=self.project_uid,
                uid=self.uid,
                query=query,
                cursor=request_cursor,
                page_num=state.page_num,
            )
            if generation != self.generation:
                return
            if self._uses_cursor_paging():
                pager = self._cursor_history()
                if request_cursor == "0" and pager.current is not None:
                    # Validate the replacement before discarding last-good history.
                    pager = CursorHistory(capacity=pager.capacity)
                try:
                    pager.append(request_cursor, page)
                except NotehubResponseError:
                    self._status("Cursor unavailable or repeated. Refresh with r to restart.")
                    return
                self._cursor_histories[self._cursor_history_key()] = pager
            self.result = page
            self.states[self._key()] = replace(state, cursor=request_cursor, result=page)
            self._render_rows()
            self._status(f"Checked {page.checked_at:%H:%M:%S} UTC · API order")
        except asyncio.CancelledError:
            raise
        except NotehubResponseError:
            if generation == self.generation:
                self._status("Cursor unavailable or repeated. Refresh with r to restart.")
        except NotehubError as error:
            if generation == self.generation:
                await self._failure(error)
        except Exception as error:
            if generation == self.generation:
                self._status(f"Read unavailable ({type(error).__name__}); retry or change scope")
        finally:
            if generation == self.generation:
                self.loading = False

    async def _failure(self, error: NotehubError) -> None:
        if isinstance(error, NotehubAuthenticationError):
            await self.disconnect()
            self._status("Authentication rejected. Reconnect with a valid token.")
        elif isinstance(error, NotehubPermissionError):
            self._status("Permission denied for this read. Choose another section.")
        elif isinstance(error, NotehubRateLimitError):
            self._status("Rate limited. Requests are paused by the session pacer; retry later.")
        elif isinstance(error, NotehubAPIError) and error.status_code == 404:
            self._status("Resource not found. Check the selected project or record scope.")
        elif isinstance(error, NotehubAPIError) and error.status_code >= 500:
            self._status("Notehub service unavailable; previous data retained. Retry with r.")
        else:
            status = getattr(error, "status_code", None)
            self._status(
                f"Read failed ({status or type(error).__name__}); previous data retained. Retry with r."
            )

    def _render_rows(self) -> None:
        workspace_controls = (
            "#records",
            "#search",
            "#page-info",
            "#query-summary",
            "#previous",
            "#next",
            "#inspector",
        )
        if not self.is_mounted or not all(self.query(selector) for selector in workspace_controls):
            return
        table = self.query_one("#records", DataTable)
        table.clear(columns=True)
        table.add_columns("Record", "Source / file", "Captured / activity", "UID")
        search = self.query_one("#search", Input).value.casefold()
        for row, key in zip(self.result.rows, self.result.row_keys, strict=True):
            if search and search not in str(row).casefold():
                continue
            table.add_row(
                safe_text(record_label(row)),
                safe_text(row.get("file", row.get("device", ""))),
                safe_text(row.get("when", row.get("last_activity", "not reported"))),
                safe_text(row.get("event", row.get("uid", "not reported"))),
                key=key,
            )
        state = self.current_state
        if state.selected_key in table.rows:
            table.move_cursor(row=table.get_row_index(state.selected_key))
        table.scroll_to(y=state.scroll_y, animate=False)
        self.query_one("#page-info", Static).update(f"{table.row_count} rows on this page")
        self.query_one("#query-summary", Static).update(
            safe_text(f"Filters: {dict(state.query) or 'none'}")
        )
        if self._uses_cursor_paging():
            pager = self._cursor_history()
            self.query_one("#previous", Button).disabled = not pager.can_previous
            self.query_one("#next", Button).disabled = not pager.can_next
        else:
            self.query_one("#previous", Button).disabled = state.page_num <= 1
            self.query_one("#next", Button).disabled = self.result.has_more is not True
        self.query_one("#inspector", RecordInspector).set_record(self.selected_record or {})
        if self._panels_ready:
            if self.view == ViewId.DEVICES and self.operation == "devices":
                self.query_one(DeviceListView).set_result(self.result)
            elif self.view == ViewId.FLEETS and self.operation == "fleets":
                self.query_one(FleetListView).set_result(self.result)
        self._update_signals()

    @property
    def selected_record(self) -> dict[str, Any] | None:
        """Resolve selected row identity independently of row position."""
        table = self.query_one("#records", DataTable)
        if not table.row_count:
            return None
        key = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        return next(
            (
                row
                for row, row_key in zip(self.result.rows, self.result.row_keys, strict=True)
                if row_key == key
            ),
            None,
        )

    @on(DataTable.RowHighlighted)
    def highlight(self, event: DataTable.RowHighlighted) -> None:
        """Inspect a highlighted record without a redundant API read."""
        if event.data_table.id != "records":
            return
        try:
            inspector = self.query_one("#inspector", RecordInspector)
        except NoMatches:
            # A screen transition can dispatch a final row event after workspace removal.
            return
        inspector.set_record(self.selected_record or {})

    @on(Input.Changed, "#search")
    def search_changed(self) -> None:
        """Filter only the already loaded page."""
        self._render_rows()

    @on(DataTable.RowSelected)
    def open_record(self, event: DataTable.RowSelected) -> None:
        """Follow resource context or open the parsed record inspector."""
        if event.data_table.id != "records":
            return
        row = self.selected_record
        if not row:
            return
        if self.operation in {
            "devices",
            "fleet_devices",
            "fleets",
            "organizations",
            "billing_accounts",
        } and row.get("uid"):
            self._save_selection()
            self.history.append((self.view, self.operation, self.uid))
            self.uid = str(row["uid"])
            self.operation = {
                "devices": "device",
                "fleet_devices": "device",
                "fleets": "fleet_devices",
                "organizations": "organization",
                "billing_accounts": "billing_account",
            }[self.operation]
            if self.operation == "device":
                self.view = ViewId.DEVICES
            self._configure_sections()
            self._restore_or_load()
        else:
            from .screens.record import RecordScreen

            self.push_screen(RecordScreen(row))

    def action_refresh(self) -> None:
        """Restart paging and request current data once."""
        if self.view == ViewId.SIMULATION:
            self.query_one(SimulationPanel).refresh_data()
            return
        if self.view == ViewId.DEVICES and self.uid and self._panels_ready:
            active = self.query_one(DeviceDetailView).query_one(TabbedContent).active
            section = active.removeprefix("device-") if active else "device"
            if section == "overview":
                section = "device"
            self._request_detail_section(ViewId.DEVICES, self.uid, section, refresh=True)
            return
        if self.view == ViewId.FLEETS and self.uid and self._panels_ready:
            active = self.query_one(FleetDetailView).query_one(TabbedContent).active
            section = active.removeprefix("fleet-") if active else "overview"
            if section != "overview":
                self._request_detail_section(ViewId.FLEETS, self.uid, section, refresh=True)
            else:
                self._status("Fleet overview uses the selected project record.")
            return
        if self.view == ViewId.OPERATIONS and self._panels_ready:
            self.query_one(OperationsPanel).refresh_data()
            return
        if self.view == ViewId.ACCOUNT and self._panels_ready:
            self.query_one(AccountPanel).refresh_data()
            return
        if self.loading:
            return
        self.states[self._key()] = replace(self.current_state, cursor="0", page_num=1)
        self.generation += 1
        if self._uses_cursor_paging():
            self.fetch(cursor="0")
        else:
            self.fetch()

    def action_filters(self) -> None:
        """Edit a draft event query without triggering intermediate requests."""
        if self.operation not in {"events", "overview", "fleet_events"}:
            return

        def apply(query: Query | None) -> None:
            if query is not None:
                self.states[self._key()] = replace(self.current_state, query=query)
                self._discard_other_cursor_queries()
                self.action_refresh()

        self.push_screen(FilterScreen(self.current_state.query), apply)

    def action_device(self) -> None:
        """Follow a selected event's reported device."""
        row = self.selected_record or {}
        if not row.get("device"):
            self._status("No device UID reported for this record")
            return
        self._save_selection()
        self.history.append((self.view, self.operation, self.uid))
        self.uid = str(row["device"])
        self.view, self.operation = ViewId.DEVICES, "device"
        self._configure_sections()
        self._sync_view_host()
        self._restore_or_load()

    def action_search(self) -> None:
        """Focus current-page search."""
        self.query_one("#search", Input).focus()

    async def action_back(self) -> None:
        """Restore the previous contextual location."""
        if self.history:
            self.view, self.operation, self.uid = self.history.pop()
            self._configure_sections()
            self._sync_view_host()
            self._restore_or_load()
        else:
            self.query_one("#search", Input).value = ""
            self.query_one("#records").focus()

    def action_help(self) -> None:
        """Display keyboard help without leaving the current context."""
        self.push_screen(
            TextDialog(
                "Keyboard guide",
                "Ctrl+P commands\n1-6 workspaces\nArrows move; Enter inspect\nf event filters; / search current page\nd related device; r refresh\nEsc back; q quit\n\nReads are manual; activity is not proof a device is online.",
            )
        )

    def action_signals(self) -> None:
        """Toggle instrumentation without issuing requests."""
        self.signals_visible = not self.signals_visible
        self._update_signals()

    def _update_signals(self) -> None:
        widget = self.query_one("#signals-strip", SignalStrip)
        widget.display = self.signals_visible
        widget.set_data(self.activity, self.result.rows)

    def action_inbox(self) -> None:
        """Open bounded session notifications."""
        self.push_screen(NotificationInboxScreen(self.notifications), self._open_notification)

    def _open_notification(self, entry: object | None) -> None:
        if entry is None or not getattr(entry, "target_uid", None):
            return
        project_uid = getattr(entry, "project_uid", None)
        if project_uid and project_uid != self.project_uid:
            self.generation += 1
            self.project_uid = project_uid
            self.query_one("#project", Select).value = project_uid
        target_kind, target_uid = (
            getattr(entry, "target_kind", None),
            getattr(entry, "target_uid", None),
        )
        if target_kind == "device":
            self.uid, self.view, self.operation = target_uid, ViewId.DEVICES, "device"
            self._configure_sections()
            self._sync_view_host()
            self._restore_or_load()
        elif target_kind == "event":
            self.action_navigate("events")
            self.states[self._key()] = replace(
                self.current_state, query=Query().events(str(target_uid))
            )
            self.action_refresh()

    def feedback(self, message: str) -> None:
        """Record non-sensitive feedback without stealing focus."""
        notify_safe(
            self,
            self.notifications,
            "information",
            message,
            project_uid=self.project_uid,
            toasts_enabled=self.toasts_enabled,
        )

    @on(Button.Pressed)
    async def button_pressed(self, event: Button.Pressed) -> None:
        """Route visible controls through the same actions as keyboard commands."""
        name = event.button.id or ""
        if name.startswith("nav-"):
            self.action_navigate(name[4:])
        elif name == "resize-help":
            self.action_help()
        elif name == "resize-quit":
            await self.action_quit()
        elif name in {"filters", "refresh", "signals", "inbox"}:
            getattr(self, f"action_{name}")()
        elif name == "toasts":
            self.toasts_enabled = not self.toasts_enabled
            event.button.label = f"Toasts: {'On' if self.toasts_enabled else 'Off'}"
        elif name == "connect":
            try:
                self.live_service = TUIReadService(
                    self.session.connect(self.query_one("#token", Input).value)
                )
                if self.simulation_project is None:
                    self.service = self.live_service
                self.query_one("#token", Input).value = ""
                self.query_one("#login").display = False
                await self._install_panels()
                self.load_projects()
            except (ValueError, NotehubError):
                self._status("Invalid token; check credentials and reconnect")
        elif name == "disconnect":
            await self.disconnect()
        elif name == "copy":
            row = self.selected_record or {}
            uid = row.get("event", row.get("uid"))
            if uid:
                self.push_screen(CopyScreen(str(uid), feedback=self.feedback))
        elif name in {"export", "export-page"}:
            from .presentation import sanitize_record

            data = (
                sanitize_record(self.selected_record or {})
                if name == "export"
                else [sanitize_record(r) for r in self.result.rows]
            )
            self.push_screen(ExportScreen(data, feedback=self.feedback))
        elif name in {"next", "previous"}:
            self._page(name == "next")
        elif name == "signals-settings":
            self.push_screen(SignalSettingsScreen(self.signal_selection), self._set_signals)
        elif name == "related-events" and self.uid:
            uid, view = self.uid, self.view
            self.history.append((self.view, self.operation, self.uid))
            self.action_navigate("events")
            query = Query().devices(uid) if view == ViewId.DEVICES else Query().fleets(uid)
            self.states[self._key()] = replace(self.current_state, query=query)
            self._discard_other_cursor_queries()
            self.action_refresh()

    def _page(self, forward: bool) -> None:
        state = self.current_state
        if self.loading:
            return
        if self._uses_cursor_paging():
            pager = self._cursor_history()
            if forward:
                cached = pager.forward()
                if cached is not None:
                    cursor = pager.current_cursor
                    if cursor is None:
                        self._status("No event page is available in this session history.")
                        return
                    self.result = cached
                    self.states[self._key()] = replace(state, cursor=cursor, result=cached)
                    self._render_rows()
                    self._status(f"Cached page · checked {cached.checked_at:%H:%M:%S} UTC")
                    return
                cursor = pager.next_cursor
                if cursor is None:
                    self._status("Cursor unavailable or repeated. Refresh to restart.")
                    return
                self.generation += 1
                self.fetch(cursor=cursor)
                return
            page = pager.previous()
            if page is None:
                self._status("No earlier event page is retained in this session.")
                return
            cursor = pager.current_cursor
            if cursor is None:
                self._status("No event page is available in this session history.")
                return
            self.result = page
            self.states[self._key()] = replace(state, cursor=cursor, result=page)
            self._render_rows()
            self._status(f"Cached page · checked {page.checked_at:%H:%M:%S} UTC")
            return
        else:
            self.states[self._key()] = replace(
                state, page_num=max(1, state.page_num + (1 if forward else -1))
            )
        self.generation += 1
        self.fetch()

    async def disconnect(self) -> None:
        """Cancel session work and erase cached response state."""
        self.generation += 1
        await self._cancel_and_wait(list(self.workers))
        self.loading = False
        await self._remove_panels()
        if self.simulation_project is not None:
            await self.simulation_project.close()
            self.simulation_project = None
            panel = self.query_one(SimulationPanel)
            panel.set_project_active(False)
            panel.start_scenario(panel.scenario_name)
        self.live_service = None
        await self.session.disconnect()
        self.service = None
        self.activity.reset()
        self.signals_visible = False
        self._update_signals()
        self.states.clear()
        self._cursor_histories.clear()
        self.device_records.clear()
        self.fleet_records.clear()
        self.detail_results.clear()
        self.history.clear()
        self.notifications.clear()
        self.result = PageResult()
        self.project_uid = self.options.project_uid
        self.live_projects.clear()
        self._project_option_value = None
        self.query_one("#login").display = True
        self._set_project_options([])
        self.query_one("#project", Select).value = Select.NULL
        self._render_rows()

    async def on_unmount(self) -> None:
        """Release owned transport when Textual ends the session."""
        await self._cancel_and_wait(list(self.workers))
        if self.simulation_project is not None:
            await self.simulation_project.close()
            self.simulation_project = None
        await self.session.disconnect()

    def _set_signals(self, selected: tuple[SignalKind, ...] | None) -> None:
        if selected is None:
            return
        self.signal_selection = selected
        self.query_one("#signals-strip", SignalStrip).configure(selected)
        self._update_signals()


def create_app(
    *, client: NotehubClient | None = None, options: TUIOptions | None = None
) -> NotehubApp:
    """Build a workbench with an optional borrowed client."""
    return NotehubApp(client=client, options=options)
