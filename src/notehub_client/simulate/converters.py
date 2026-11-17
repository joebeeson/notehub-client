"""Public adapters for application-owned scenario sources."""

from __future__ import annotations

from collections.abc import Mapping
from functools import singledispatch

from ..typing.simulate import ScenarioSource
from .scenario import Scenario

__all__ = ["resolve_scenario", "scenario_value"]


@singledispatch
def scenario_value(value: object) -> object:
    """Adapt a Scenario, versioned mapping, or structural to_scenario() source.

    Register third-party value types here when they cannot implement the protocol.
    Conversion is explicit; strings are never implicitly treated as paths/names.
    """
    if isinstance(value, Scenario):
        return value
    if isinstance(value, ScenarioSource):
        return value.to_scenario()
    if isinstance(value, Mapping):
        return Scenario.from_mapping(value)
    raise TypeError("scenario must be a Scenario, mapping, or implement to_scenario()")


def resolve_scenario(value: object) -> Scenario:
    """Adapt a value and enforce that the converter returned a Scenario."""
    result = scenario_value(value)
    if not isinstance(result, Scenario):
        raise TypeError("scenario converter must return a Scenario")
    return result
