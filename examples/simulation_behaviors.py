"""Run a deterministic thermostat without hardware: uv run python examples/simulation_behaviors.py."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from random import Random
from typing import Any

from notehub_client import simulate
from notehub_client.simulate.behaviors import StepContext, StepResult
from notehub_client.typing import Behavior


@dataclass
class Thermostat:
    """An application-owned model which learns its target from delivered commands."""

    temperature: float
    target: float
    random: Random

    def __call__(self, context: StepContext) -> StepResult:
        """Move toward the target and acknowledge only recognized commands."""
        target = self.target
        consumed = []
        for command in context.commands:
            if command["file"] == "commands.qi" and "target" in command["body"]:
                target = float(command["body"]["target"])
                consumed.append(command["note"])
        temperature = self.temperature + (target - self.temperature) * 0.25
        temperature += self.random.uniform(-0.01, 0.01)
        result = (
            StepResult(consumed=tuple(consumed))
            .with_readings(temperature=temperature, voltage=3.7)
            .with_note("temperature.qo", {"celsius": temperature, "target": target})
        )
        self.temperature, self.target = temperature, target
        return result


def thermostat(config: Mapping[str, Any], *, seed: int) -> Behavior:
    """Create fresh model and random state for each simulation run."""
    return Thermostat(
        float(config.get("temperature", 18)),
        float(config.get("target", 20)),
        Random(seed),  # noqa: S311 - reproducible simulation
    )


async def main() -> None:
    """Deliver a target command, simulate three samples, and read normal API events."""
    project, uid = "app:demo", "dev:thermostat"
    scenario = (
        simulate.Scenario()
        .with_project(project)
        .with_device(project, uid, readings={"temperature": 18.0, "voltage": 3.7})
        .with_behavior(project, uid, thermostat)
    )
    with scenario.start(seed=42) as run:
        device = run.device(project, uid)
        async with run.client() as client:
            await client.notes.add_qi(device.note("commands.qi"), {"target": 23})
            device.sync()
            for _ in range(3):
                run.advance(timedelta(minutes=1))
                device.step()
                device.sync()
            for event in (await client.events.list(project))["events"]:
                print(event["body"])


if __name__ == "__main__":
    asyncio.run(main())
