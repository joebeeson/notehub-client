"""Public values shared by hosted application components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["ComponentEmission", "ComponentScope"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ComponentScope:
    """Project context and optional fleet or device identity for one run."""

    project_uid: str
    fleet_uid: str | None = None
    device_uid: str | None = None

    def __post_init__(self) -> None:
        for name in ("project_uid", "fleet_uid", "device_uid"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{name} must be a nonempty string or None")

    def __rich_repr__(self) -> Iterator[object]:
        yield "project_uid", self.project_uid
        yield "fleet_uid", self.fleet_uid, None
        yield "device_uid", self.device_uid, None


@dataclass(frozen=True, slots=True)
class ComponentEmission:
    """An application event emitted by one hosted component run."""

    run_id: int
    name: str
    scope: ComponentScope
    payload: object
