"""Stateless Notehub domain facades sharing the owning client's transport."""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING

from ..helpers import (
    encode_path_segments,
)

if TYPE_CHECKING:
    from ..typing import (
        JSONObject,
        JSONValue,
    )
    from .base import RequestClient

LOGGER = getLogger(__name__)


class NotesFacade:
    """Operations for the notes domain."""

    def __init__(self, client: RequestClient) -> None:
        self._client = client

    async def add_qi(
        self, project_uid: str, device_uid: str, notefile: str, body: JSONObject
    ) -> JSONValue:
        """Add a note to a device's queue-in notefile."""
        result = await self._client.request(
            "POST",
            encode_path_segments("projects", project_uid, "devices", device_uid, "notes", notefile),
            json={"body": body},
        )
        LOGGER.info(
            "Notehub queue note added: project_uid=%r device_uid=%r notefile=%r",
            project_uid,
            device_uid,
            notefile,
        )
        return result

    async def add_db(
        self, project_uid: str, device_uid: str, notefile: str, note_id: str, body: JSONObject
    ) -> JSONValue:
        """Add a note with the given ID to a device's database notefile."""
        result = await self._client.request(
            "POST",
            encode_path_segments(
                "projects", project_uid, "devices", device_uid, "notes", notefile, note_id
            ),
            json={"body": body},
        )
        LOGGER.info(
            "Notehub database note added: project_uid=%r device_uid=%r notefile=%r note_id=%r",
            project_uid,
            device_uid,
            notefile,
            note_id,
        )
        return result

    async def update_db(
        self, project_uid: str, device_uid: str, notefile: str, note_id: str, body: JSONObject
    ) -> JSONValue:
        """Replace a database note's body for the given device and note ID."""
        result = await self._client.request(
            "PUT",
            encode_path_segments(
                "projects", project_uid, "devices", device_uid, "notes", notefile, note_id
            ),
            json={"body": body},
        )
        LOGGER.info(
            "Notehub database note updated: project_uid=%r device_uid=%r notefile=%r note_id=%r",
            project_uid,
            device_uid,
            notefile,
            note_id,
        )
        return result

    async def delete(
        self, project_uid: str, device_uid: str, notefile: str, note_id: str
    ) -> JSONValue:
        """Delete the identified note from a device's notefile."""
        result = await self._client.request(
            "DELETE",
            encode_path_segments(
                "projects", project_uid, "devices", device_uid, "notes", notefile, note_id
            ),
        )
        LOGGER.info(
            "Notehub database note deleted: project_uid=%r device_uid=%r notefile=%r note_id=%r",
            project_uid,
            device_uid,
            notefile,
            note_id,
        )
        return result
