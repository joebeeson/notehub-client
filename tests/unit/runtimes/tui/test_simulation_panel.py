"""Pilot coverage for the credential-free, local simulation workspace."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from textual.widgets import DataTable, Select, Static

from notehub_client.runtimes.tui.app import NotehubApp
from notehub_client.runtimes.tui.demo import DEMO_PROJECT_UID, DemoReadService
from notehub_client.runtimes.tui.screens.simulation import SimulationPanel
from notehub_client.runtimes.tui.service import SimulationProjectService
from notehub_client.runtimes.tui.state import TUIOptions, ViewId


@pytest.mark.asyncio
async def test_simulation_lab_runs_locally_without_api_credentials() -> None:
    app = NotehubApp(options=TUIOptions())
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause(0.1)
        panel = app.query_one(SimulationPanel)
        assert app.service is None
        assert app.session.client is None

        await pilot.click("#nav-simulation")
        await pilot.pause()
        assert app.view is ViewId.SIMULATION
        assert (
            app.query_one("#simulation-title", Static).render().plain.startswith("SIMULATION LAB")
        )
        assert app.query_one("#simulation-event-table", DataTable).row_count == 3

        initial_time = panel.simulation.now
        await pilot.click("#simulation-advance")
        assert panel.simulation.now > initial_time
        await pilot.click("#simulation-step")
        assert sum(state["steps"] for state in panel.simulation.snapshot()["devices"].values()) == 3
        await pilot.click("#simulation-sync")
        await pilot.pause()
        assert app.query_one("#simulation-event-table", DataTable).row_count >= 4
        assert app.service is None
        assert app.session.client is None

    assert panel.simulation.closed


@pytest.mark.asyncio
async def test_simulation_scenario_change_restarts_a_deterministic_run() -> None:
    app = NotehubApp(options=TUIOptions())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        panel = app.query_one(SimulationPanel)
        previous = panel.simulation
        picker = app.query_one("#simulation-scenario")
        picker.value = "commands"
        await pilot.pause()

        assert previous.closed
        assert panel.scenario_name == "commands"
        assert panel.simulation is not previous
        assert panel.simulation.scenario == panel.scenario


@pytest.mark.asyncio
async def test_reset_replays_the_same_seeded_initial_scenario() -> None:
    app = NotehubApp(options=TUIOptions())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        panel = app.query_one(SimulationPanel)
        initial = panel.simulation.snapshot()
        panel.simulation.step()
        await pilot.click("#nav-simulation")
        await pilot.click("#simulation-reset")
        await pilot.pause()

        assert panel.simulation.snapshot() == initial


@pytest.mark.asyncio
async def test_packaged_simulation_is_selectable_as_an_active_project() -> None:
    app = NotehubApp(options=TUIOptions())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        picker = app.query_one("#project", Select)
        simulation_option = f"{app.SIMULATION_PROJECT_PREFIX}field_lab"
        assert simulation_option in {value for _, value in app._simulation_options()}

        picker.value = simulation_option
        await pilot.pause(0.2)

        assert isinstance(app.service, SimulationProjectService)
        assert app.project_uid == "app:coastal-field-lab"
        assert app.session.client is None
        assert app.service.simulation is app.query_one(SimulationPanel).simulation

        app.action_navigate("events")
        await pilot.pause(0.2)
        assert app.result.rows
        assert {row["event"] for row in app.result.rows} >= {
            "evt:north-001",
            "evt:south-001",
        }

        previous_project = app.simulation_project
        await pilot.click("#nav-simulation")
        await pilot.click("#simulation-reset")
        await pilot.pause(0.2)
        assert app.simulation_project is not previous_project
        assert app.simulation_project is not None
        assert app.simulation_project.simulation is app.query_one(SimulationPanel).simulation

        await app.disconnect()
        assert app.service is None
        assert app.simulation_project is None
        assert app.query_one(SimulationPanel).simulation.snapshot()

        picker.value = f"{app.SIMULATION_PROJECT_PREFIX}field_lab"
        await pilot.pause(0.2)
        assert isinstance(app.service, SimulationProjectService)


@pytest.mark.asyncio
async def test_switching_to_simulation_and_back_preserves_live_reader() -> None:
    app = NotehubApp(options=TUIOptions(demo=True))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        picker = app.query_one("#project", Select)
        picker.value = DEMO_PROJECT_UID
        await pilot.pause(0.1)
        live_service = app.live_service
        assert isinstance(live_service, DemoReadService)

        with patch.object(live_service, "read", wraps=live_service.read) as live_read:
            picker.value = f"{app.SIMULATION_PROJECT_PREFIX}field_lab"
            await pilot.pause(0.2)
            active_simulation = app.simulation_project
            assert active_simulation is not None
            assert app.service is active_simulation
            assert app.live_service is live_service

            picker.value = DEMO_PROJECT_UID
            await pilot.pause(0.2)
            assert app.service is live_service
            assert app.simulation_project is None
            assert app.view is ViewId.OVERVIEW
            assert app.query_one("#sections").display is False
            assert live_read.await_count >= 2
            assert all(
                call.kwargs.get("project_uid") == DEMO_PROJECT_UID
                for call in live_read.await_args_list
            )
            with pytest.raises(RuntimeError, match="closed"):
                active_simulation.simulation.snapshot()


@pytest.mark.asyncio
async def test_lab_sync_updates_the_active_simulation_project_event_view() -> None:
    app = NotehubApp(options=TUIOptions())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        picker = app.query_one("#project", Select)
        picker.value = f"{app.SIMULATION_PROJECT_PREFIX}field_lab"
        await pilot.pause(0.2)
        app.action_navigate("events")
        await pilot.pause(0.2)
        initial_count = len(app.result.rows)

        await pilot.click("#nav-simulation")
        await pilot.click("#simulation-sync")
        await pilot.pause(0.1)
        app.action_navigate("events")
        app.action_refresh()
        await pilot.pause(0.2)

        assert len(app.result.rows) == initial_count + 1
        assert any(row.get("event") for row in app.result.rows)


@pytest.mark.asyncio
async def test_reconnect_after_simulation_does_not_offer_synthetic_uid_as_live_project() -> None:
    app = NotehubApp(options=TUIOptions())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        app.query_one("#project", Select).value = f"{app.SIMULATION_PROJECT_PREFIX}field_lab"
        await pilot.pause(0.2)
        await app.disconnect()

        app.query_one("#token").value = "test-token"
        with (
            patch.object(app.session, "connect", return_value=object()),
            patch(
                "notehub_client.runtimes.tui.app.TUIReadService",
                return_value=DemoReadService(),
            ),
        ):
            app.query_one("#connect").press()
            await pilot.pause(0.2)

        assert app.live_projects
        assert "app:coastal-field-lab" not in {uid for _, uid in app.live_projects}


@pytest.mark.asyncio
async def test_reset_drains_inflight_simulation_read_before_closing_shared_run() -> None:
    app = NotehubApp(options=TUIOptions())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.1)
        app.query_one("#project", Select).value = f"{app.SIMULATION_PROJECT_PREFIX}field_lab"
        await pilot.pause(0.2)
        previous = app.simulation_project
        assert previous is not None

        class DelayedReader:
            def __init__(self) -> None:
                self.started = asyncio.Event()
                self.cancelled = asyncio.Event()
                self.release = asyncio.Event()

            async def read(self, operation: str, **kwargs: object):
                self.started.set()
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise
                return await previous.reader.read(operation, **kwargs)

        delayed = DelayedReader()
        previous.reader = delayed  # type: ignore[assignment]
        app.action_navigate("events")
        await asyncio.wait_for(delayed.started.wait(), timeout=1)

        await pilot.click("#nav-simulation")
        await pilot.click("#simulation-reset")
        await pilot.pause(0.2)

        assert delayed.cancelled.is_set()
        assert app.simulation_project is not previous
        assert app.simulation_project is not None
        assert app.simulation_project.simulation is app.query_one(SimulationPanel).simulation
        with pytest.raises(RuntimeError, match="closed"):
            previous.simulation.snapshot()
