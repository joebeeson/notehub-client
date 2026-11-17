"""Named, packaged TOML examples for offline workflows."""

from __future__ import annotations

from importlib.resources import as_file, files

from .scenario import Scenario

__all__ = ["available", "named"]

_NAMES = ("field_lab", "telemetry", "commands", "environment", "sensor")


def available() -> tuple[str, ...]:
    """List the supported packaged scenario names."""
    return _NAMES


def named(name: str) -> Scenario:
    """Load a fresh immutable scenario from packaged TOML data."""
    if name not in _NAMES:
        raise ValueError(f"unknown scenario name; choose from {', '.join(_NAMES)}")
    resource = files("notehub_client.simulate").joinpath("scenarios", f"{name}.toml")
    with as_file(resource) as path:
        return Scenario.from_toml(path)
