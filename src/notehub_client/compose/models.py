"""Address models for Notehub operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._validation import require_identifier

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["DeviceTarget", "NoteTarget"]


@dataclass(frozen=True, slots=True)
class DeviceTarget:
    """Project and device address for device-level operations."""

    project_uid: str
    device_uid: str

    def __post_init__(self) -> None:
        require_identifier(self.project_uid, "project_uid")
        require_identifier(self.device_uid, "device_uid")

    def __rich_repr__(self) -> Iterator[object]:
        yield "project_uid", self.project_uid
        yield "device_uid", self.device_uid


@dataclass(frozen=True, slots=True)
class NoteTarget(DeviceTarget):
    """Project, device, notefile, and optional note ID for note operations."""

    notefile: str
    note_id: str | None = None

    def __post_init__(self) -> None:
        DeviceTarget.__post_init__(self)
        require_identifier(self.notefile, "notefile")
        if self.note_id is not None:
            require_identifier(self.note_id, "note_id")

    def __rich_repr__(self) -> Iterator[object]:
        yield "project_uid", self.project_uid
        yield "device_uid", self.device_uid
        yield "notefile", self.notefile
        yield "note_id", self.note_id, None
