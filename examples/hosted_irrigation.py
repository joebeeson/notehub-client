"""Run a typed irrigation controller against a local Notehub simulation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from notehub_client import hosting, simulate
from notehub_client.catalog import Catalog, Contract, EventSelector
from notehub_client.filters import EventFilters
from notehub_client.payloads import PayloadDecoder
from notehub_client.simulate.behaviors import StepContext, StepResult
from notehub_client.typing import Behavior

PROJECT = "app:pivot-demo"
FLEET = "fleet:pivot-east"
SENSOR = "dev:water-level"
PUMP = "dev:irrigation-pump"


@dataclass(frozen=True)
class WaterLevel:
    """Current water level in metres."""

    water_level_m: float


@dataclass(frozen=True)
class PumpStopRequested:
    """Application decision to stop the irrigation pump."""

    pump_uid: str
    observed_level_m: float
    threshold_m: float


class PivotController:
    """Configured farm controller with state local to this application object."""

    def __init__(self, *, pump_uid: str, high_water_m: float) -> None:
        self.pump_uid = pump_uid
        self.high_water_m = high_water_m
        self.stop_requested = False

    async def __call__(self, context: hosting.ComponentContext) -> None:
        """Handle water-level events and request a pump stop at most once."""
        async for event in context.events:
            reading = context.payloads.decode(event, as_type=WaterLevel).body
            if reading.water_level_m <= self.high_water_m or self.stop_requested:
                continue
            await context.client.notes.add_qi(
                PROJECT,
                self.pump_uid,
                "commands.qi",
                {"action": "stop"},
            )
            self.stop_requested = True
            await context.emit(
                PumpStopRequested(self.pump_uid, reading.water_level_m, self.high_water_m)
            )


def pump_behavior(config: Mapping[str, Any], *, seed: int) -> Behavior:
    """Consume stop commands and update the pump's simulated running reading."""
    del seed
    if config:
        raise ValueError("pump behavior takes no configuration")

    def apply(context: StepContext) -> StepResult:
        stopped = any(
            command["file"] == "commands.qi" and command["body"].get("action") == "stop"
            for command in context.commands
        )
        consumed = tuple(
            command["note"]
            for command in context.commands
            if command["file"] == "commands.qi" and command["body"].get("action") == "stop"
        )
        return StepResult(readings={"running": False} if stopped else {}, consumed=consumed)

    return apply


def make_decoder() -> PayloadDecoder:
    """Bind the simulated telemetry wire contract to the application type."""
    return PayloadDecoder(
        catalog=Catalog(
            (
                Contract(
                    "water-level",
                    "1",
                    EventSelector(
                        product="product:pivot",
                        file="water.qo",
                        discriminator="/body/schema_version",
                        value=1,
                    ),
                    binding="water-level.v1",
                ),
            )
        ),
        bindings={"water-level.v1": WaterLevel},
    )


async def main() -> None:
    """Exercise observation, decision, command delivery, and pump application."""
    scenario = (
        simulate.Scenario()
        .with_project(PROJECT)
        .with_fleet(PROJECT, FLEET, label="Pivot East")
        .with_device(
            PROJECT,
            SENSOR,
            fleet_uids=(FLEET,),
            product_uid="product:pivot",
            readings={"water_level_m": 0.0},
        )
        .with_device(
            PROJECT,
            PUMP,
            fleet_uids=(FLEET,),
            product_uid="product:pivot",
            readings={"running": True},
        )
        .with_behavior(PROJECT, PUMP, pump_behavior)
    )

    emissions: list[hosting.ComponentEmission] = []

    async def collect(emission: hosting.ComponentEmission) -> None:
        emissions.append(emission)

    with scenario.start() as run:
        sensor = run.device(PROJECT, SENSOR)
        pump = run.device(PROJECT, PUMP)
        # Simulation sync publishes these Notecard-originated Notes to event history.
        for value in (1.0, 3.2, 3.4):
            sensor.queue("water.qo", {"schema_version": 1, "water_level_m": value})
            sensor.sync()

        async with run.client(payloads=make_decoder()) as client:
            controller = PivotController(pump_uid=PUMP, high_water_m=2.5)
            await hosting.ComponentHost(client).run(
                controller,
                name="pivot-east-irrigation",
                scope=hosting.ComponentScope(project_uid=PROJECT, fleet_uid=FLEET),
                events=client.events.iter(
                    PROJECT,
                    filters=EventFilters(
                        files=("water.qo",),
                        device_uids=(SENSOR,),
                        fleet_uids=(FLEET,),
                    ),
                ),
                emit=collect,
            )
            print(f"Controller requested stop once: {controller.stop_requested}")
            print(f"Application emissions: {[item.payload for item in emissions]}")

            # Sending the cloud command is separate from device delivery and action.
            pump.sync()
            pump.step()
            pump_record = cast(dict[str, object], await client.devices.get(PROJECT, PUMP))
            print(f"Pump running after simulated command handling: {pump_record['running']}")


if __name__ == "__main__":
    asyncio.run(main())
