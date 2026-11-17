"""Local scenario runner for exploring Notehub device workflows in the TUI."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, DataTable, Label, Select, Static, TabbedContent, TabPane

from ....simulate import Scenario, Simulation, available, named
from ..presentation import safe_text


class SimulationPanel(Vertical):
    """Run a deterministic scenario entirely in process, with explicit controls."""

    class ScenarioStarted(Message):
        """A new run replaced the scenario currently shown by the panel."""

        def __init__(self, scenario_name: str, simulation: Simulation) -> None:
            super().__init__()
            self.scenario_name = scenario_name
            self.simulation = simulation

    DEFAULT_CSS = """
    SimulationPanel { height: 1fr; padding: 1; }
    SimulationPanel #simulation-title { height: 1; color: $success; text-style: bold; }
    SimulationPanel #simulation-status { height: 2; color: $text-muted; }
    SimulationPanel #simulation-scenario { width: 1fr; }
    SimulationPanel #simulation-device { width: 1fr; }
    SimulationPanel TabbedContent { height: 1fr; }
    SimulationPanel DataTable { height: 1fr; }
    SimulationPanel .simulation-note { height: auto; color: $text-muted; padding: 1 0; }
    """

    def __init__(self, scenario_name: str = "field_lab", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.scenario_names = available()
        if scenario_name not in self.scenario_names:
            scenario_name = self.scenario_names[0]
        self.scenario_name = scenario_name
        self.scenario: Scenario = named(scenario_name)
        self.seed = 73
        self.simulation = self.scenario.start(seed=self.seed)
        self.selected_device = self._device_keys()[0] if self._device_keys() else None
        self._selecting = False
        self._project_active = False

    def _device_keys(self) -> tuple[tuple[str, str], ...]:
        return tuple((device.project_uid, device.uid) for device in self.scenario.devices)

    def _device_options(self) -> list[tuple[str, str]]:
        labels = {
            (device.project_uid, device.uid): device.serial_number or device.uid
            for device in self.scenario.devices
        }
        return [(labels[key], "\x1f".join(key)) for key in self._device_keys()]

    def start_scenario(self, scenario_name: str) -> Simulation:
        """Replace the local run and return it for the project reader to share."""
        if scenario_name not in self.scenario_names:
            raise ValueError("Unknown simulation scenario")
        self._reset(scenario_name)
        return self.simulation

    def set_project_active(self, active: bool) -> None:
        """Mark whether the app's project reader shares this run's lifetime."""
        self._project_active = active

    def compose(self) -> ComposeResult:
        """Show a local-only lab, explicit scenario controls, and run state."""
        yield Label("SIMULATION LAB · LOCAL ONLY · NO NETWORK", id="simulation-title")
        with Horizontal(id="simulation-controls"):
            yield Select(
                [(name.replace("_", " ").title(), name) for name in self.scenario_names],
                value=self.scenario_name,
                id="simulation-scenario",
            )
            yield Select(
                self._device_options(),
                value="\x1f".join(self.selected_device) if self.selected_device else Select.NULL,
                prompt="Choose device",
                id="simulation-device",
            )
        with Horizontal(id="simulation-actions"):
            yield Button("Reset run", id="simulation-reset")
            yield Button("Advance 5 min", id="simulation-advance")
            yield Button("Step behaviors", id="simulation-step", variant="primary")
            yield Button("Sync device", id="simulation-sync")
        yield Static("Starting local simulation…", id="simulation-status")
        with TabbedContent(initial="simulation-overview"):
            with TabPane("Overview", id="simulation-overview"):
                yield Static("", id="simulation-summary")
                yield Label(
                    "Advance, step, and sync are separate actions. A sync transfers queues; "
                    "it does not run device behavior.",
                    classes="simulation-note",
                )
            with TabPane("Devices", id="simulation-devices"):
                yield DataTable(id="simulation-device-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Events", id="simulation-events"):
                yield DataTable(id="simulation-event-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Queues", id="simulation-queues"):
                yield DataTable(id="simulation-queue-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        """Set up tables and paint the freshly created deterministic run."""
        self.query_one("#simulation-device-table", DataTable).add_columns(
            "Device", "Fleet", "Temperature", "Steps", "Last reported activity"
        )
        self.query_one("#simulation-event-table", DataTable).add_columns(
            "Received", "Device", "File", "Event", "Body preview"
        )
        self.query_one("#simulation-queue-table", DataTable).add_columns(
            "Device", "Outbound .qo", "Cloud .qi", "Delivered .qi"
        )
        self._refresh()

    def refresh_data(self) -> None:
        """Refresh visible local state without advancing or stepping the run."""
        self._refresh()

    def _reset(self, scenario_name: str) -> None:
        previous = self.simulation
        if not self._project_active:
            previous.close()
        self.scenario_name = scenario_name
        self.scenario = named(scenario_name)
        self.simulation = self.scenario.start(seed=self.seed)
        keys = self._device_keys()
        self.selected_device = keys[0] if keys else None
        self._selecting = True
        scenario_picker = self.query_one("#simulation-scenario", Select)
        device_picker = self.query_one("#simulation-device", Select)
        scenario_picker.value = scenario_name
        device_picker.set_options(self._device_options())
        device_picker.value = (
            "\x1f".join(self.selected_device) if self.selected_device else Select.NULL
        )
        self._selecting = False
        self._refresh()
        self._status(f"Reset to {scenario_name.replace('_', ' ')} · seed {self.seed}")

    def _status(self, message: str) -> None:
        self.query_one("#simulation-status", Static).update(safe_text(message))

    def _refresh(self) -> None:
        snapshot = self.simulation.snapshot()
        devices = snapshot["devices"]
        events = tuple(snapshot["events"])
        device_table = self.query_one("#simulation-device-table", DataTable)
        device_table.clear()
        queue_table = self.query_one("#simulation-queue-table", DataTable)
        queue_table.clear()
        definitions = {(d.project_uid, d.uid): d for d in self.scenario.devices}
        for key, state in devices.items():
            project_uid, uid = key
            definition = definitions[key]
            temperature = state["readings"].get("temperature", "not reported")
            device_table.add_row(
                safe_text(definition.serial_number or uid),
                safe_text(", ".join(definition.fleet_uids) or "not assigned"),
                safe_text(temperature),
                safe_text(state["steps"]),
                safe_text(
                    state["sessions"][-1].get("when", "not synced")
                    if state["sessions"]
                    else "not synced"
                ),
                key="\x1f".join(key),
            )
            queue_table.add_row(
                safe_text(definition.serial_number or uid),
                safe_text(len(state["outbound"])),
                safe_text(len(state["inbound"])),
                safe_text(len(state["device_inbound"])),
                key="\x1f".join(key),
            )
        event_table = self.query_one("#simulation-event-table", DataTable)
        event_table.clear()
        for index, event in enumerate(events):
            body = event.get("body")
            preview = str(body)[:80] if isinstance(body, Mapping) else "not reported"
            event_table.add_row(
                safe_text(event.get("received", "not reported")),
                safe_text(event.get("device", "not reported")),
                safe_text(event.get("file", "not reported")),
                safe_text(event.get("event", "not reported")),
                safe_text(preview),
                key=str(event.get("event", f"anonymous:{index}")),
            )
        self.query_one("#simulation-summary", Static).update(
            safe_text(
                f"Scenario: {self.scenario_name.replace('_', ' ')}\n"
                f"Clock: {snapshot['now'].isoformat()}\n"
                f"Projects: {len(self.scenario.projects)} · Fleets: {len(self.scenario.fleets)} · "
                f"Devices: {len(devices)} · Received events: {len(events)}\n"
                "All state is synthetic and held only in this process."
            )
        )
        self.query_one("#simulation-step", Button).disabled = not self.scenario.behaviors
        self.query_one("#simulation-sync", Button).disabled = self.selected_device is None
        if not self.is_mounted:
            return
        device_picker = self.query_one("#simulation-device", Select)
        if device_picker.value is Select.NULL and self.selected_device:
            self._selecting = True
            device_picker.set_options(self._device_options())
            device_picker.value = "\x1f".join(self.selected_device)
            self._selecting = False

    @on(Select.Changed, "#simulation-scenario")
    def scenario_changed(self, event: Select.Changed) -> None:
        """Start a fresh run when the user selects another packaged scenario."""
        if self._selecting or event.value is Select.NULL:
            return
        name = str(event.value)
        if name in self.scenario_names and name != self.scenario_name:
            self._reset(name)
            self.post_message(self.ScenarioStarted(name, self.simulation))

    @on(Select.Changed, "#simulation-device")
    def device_changed(self, event: Select.Changed) -> None:
        """Choose the device whose local queue will be synchronized."""
        if self._selecting or event.value is Select.NULL:
            return
        project_uid, uid = str(event.value).split("\x1f", maxsplit=1)
        self.selected_device = (project_uid, uid)
        self.query_one("#simulation-sync", Button).disabled = False

    @on(Button.Pressed, "#simulation-reset")
    def reset_pressed(self) -> None:
        """Discard the local run and start the selected scenario again."""
        self._reset(self.scenario_name)
        self.post_message(self.ScenarioStarted(self.scenario_name, self.simulation))

    @on(Button.Pressed, "#simulation-advance")
    def advance_pressed(self) -> None:
        """Advance only the simulation clock, without stepping or syncing."""
        self.simulation.advance(timedelta(minutes=5))
        self._refresh()
        self._status("Advanced simulation clock by five minutes")

    @on(Button.Pressed, "#simulation-step")
    def step_pressed(self) -> None:
        """Run each bound behavior once and report generated Notes."""
        try:
            results = self.simulation.step()
        except (TypeError, ValueError):
            self._status("A behavior failed; inspect the scenario and reset the local run")
            return
        produced = sum(len(result.outbound) for result in results.values())
        self._refresh()
        self._status(f"Stepped {len(results)} behavior(s) · queued {produced} outbound Note(s)")

    @on(Button.Pressed, "#simulation-sync")
    def sync_pressed(self) -> None:
        """Synchronize the selected simulated device's local queues."""
        if self.selected_device is None:
            self._status("Choose a simulated device first")
            return
        project_uid, uid = self.selected_device
        result = self.simulation.device(project_uid, uid).sync()
        self._refresh()
        self._status(f"Local sync complete · sent {result.sent} · received {result.received}")

    async def on_unmount(self) -> None:
        """Close this isolated run when the workbench exits."""
        self.simulation.close()


__all__ = ["SimulationPanel"]
