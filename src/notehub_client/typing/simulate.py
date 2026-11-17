"""Structural scenario construction contracts for simulation integrations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..simulate.behaviors import StepContext, StepResult
    from ..simulate.scenario import Scenario

__all__ = ["Behavior", "BehaviorFactory", "ScenarioSource"]


class Behavior(Protocol):
    """A device model invoked only by an explicit simulation step."""

    def __call__(self, context: StepContext, /) -> StepResult:
        """Describe the next device transition without mutating simulation state."""
        ...


class BehaviorFactory(Protocol):
    """Construct an independent behavior for a device in each run."""

    def __call__(self, config: Mapping[str, Any], /, *, seed: int) -> Behavior:
        """Build a fresh callable using immutable configuration and a stable seed."""
        ...


@runtime_checkable
class ScenarioSource(Protocol):
    """An application value capable of supplying reusable simulation conditions."""

    def to_scenario(self) -> Scenario:
        """Return an immutable scenario definition, without starting a run."""
        ...
